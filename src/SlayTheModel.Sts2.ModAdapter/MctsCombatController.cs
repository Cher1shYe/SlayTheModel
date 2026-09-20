using Godot;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Actions;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;
using SlayTheModel.Sts2.Protocol;
using Environment = System.Environment;
using ICardSelector = MegaCrit.Sts2.Core.TestSupport.ICardSelector;

namespace SlayTheModel.Sts2.ModAdapter;

internal sealed class MctsCombatController : ICardSelector
{
    private static readonly MctsCombatController Instance = new();
    private readonly List<SearchAction> _prefix = [];
    private readonly NativeWorkerClient _worker = new();
    private CancellationTokenSource _generation = new();
    private CombatState? _state;
    private bool _busy;
    private bool _paused;
    private bool _keyDown;
    private bool _choosing;
    private int _entryHp;
    private IDisposable? _selector;
    private ActionExecutor? _executor;
    private static bool _configured;
    private int _searches;
    private bool _faulted;

    internal static AiControlStatus GetStatus()
    {
        if (!_configured)
        {
            var firstLegal = string.Equals(Environment.GetEnvironmentVariable("SLAY_THE_MODEL_LIVE_POLICY"), "first-legal", StringComparison.OrdinalIgnoreCase);
            return new(firstLegal ? "MCTS · 未开启（联调）" : "MCTS · 未开启",
                firstLegal ? "当前运行 first-legal 联调策略。使用 -Policy mcts 启动以启用 MCTS。" : "当前没有启用 MCTS。使用 -Policy mcts 启动游戏。", "#8793a3", false);
        }
        if (Instance._state == null)
        {
            if (CombatManager.Instance.IsInProgress)
                return new("MCTS · 当前战斗不支持", "当前仅支持单人铁甲战士战斗，自动出牌未接管。", "#8793a3", false);
            return new("MCTS · 已开启 / 待命", "MCTS 已开启，进入单人铁甲战士战斗后自动接管。", "#73cba2", false);
        }
        if (Instance._paused)
            return new(Instance._faulted ? "MCTS · 异常暂停" : "MCTS · 已暂停",
                "自动出牌已暂停。点击或按 F8 恢复，重新思考当前局面。", "#f0ba65", true);
        if (Instance._searches > 0)
            return new("MCTS · 思考中…", "AI 正在思考。点击或按 F8 暂停自动出牌。", "#83bcff", true);
        return new("MCTS · 已开启", "AI 自动出牌已开启。点击或按 F8 暂停；已提交的动作会完成结算。", "#73cba2", true);
    }

    internal static void TogglePause()
    {
        if (!_configured || Instance._state == null) return;
        if (!Instance._paused) Instance.Pause("User toggle", faulted: false);
        else
        {
            Instance._paused = false;
            Instance._faulted = false;
            Console.WriteLine("[SlayTheModel] MCTS resumed; rebuilding from actual state.");
        }
    }

    public static void Initialize()
    {
        if (!string.Equals(Environment.GetEnvironmentVariable("SLAY_THE_MODEL_LIVE_POLICY"), "mcts", StringComparison.OrdinalIgnoreCase)) return;
        _configured = true;
        NativeCombatCheckpoint.EnableCapture();
        CombatManager.Instance.CombatBegan += Instance.Begin;
        CombatManager.Instance.CombatEnded += _ => Instance.End();
        Callable.From(() =>
        {
            var tree = (SceneTree)Engine.GetMainLoop();
            tree.ProcessFrame += Instance.Tick;
            tree.Root.TreeExiting += Instance.End;
        }).CallDeferred();
        Console.WriteLine("[SlayTheModel] experimental MCTS enabled; F8 pauses/resumes; first/rebuilt search=5s, continued=1s");
    }

    private void Begin(CombatState state)
    {
        End();
        if (state.Players.Count != 1 || state.Players[0].Character.Id.Entry != "IRONCLAD")
        {
            Console.WriteLine("[SlayTheModel] MCTS supports solo Ironclad only.");
            return;
        }
        _state = state;
        _entryHp = state.Players[0].Creature.CurrentHp;
        _prefix.Clear();
        _paused = false;
        _faulted = false;
        _executor = RunManager.Instance.ActionExecutor;
        _executor.BeforeActionExecuted += Record;
        _selector = CardSelectCmd.PushSelector(this);
    }

    private void End()
    {
        _generation.Cancel();
        _generation.Dispose();
        _generation = new CancellationTokenSource();
        _worker.Dispose();
        _selector?.Dispose();
        _selector = null;
        if (_executor != null) _executor.BeforeActionExecuted -= Record;
        _executor = null;
        _state = null;
    }

    private void Record(GameAction action)
    {
        if (action.State != GameActionState.WaitingForExecution) return;
        CombatActionDescriptor? descriptor = action switch
        {
            PlayCardAction play => new(CombatActionKind.PlayCard, play.OwnerId, play.NetCombatCard.CombatCardIndex, TargetCreatureId: play.TargetId),
            EndPlayerTurnAction end => new(CombatActionKind.EndTurn, end.OwnerId),
            _ => null,
        };
        if (descriptor != null) _prefix.Add(new SearchAction($"{descriptor.Kind}:{descriptor.CombatCardIndex}:{descriptor.TargetCreatureId}", descriptor));
        else if (action is UsePotionAction) Pause("Manual potion use is outside the v1 replay action set.");
    }

    private void Tick()
    {
        var down = Input.IsPhysicalKeyPressed(Key.F8);
        if (down && !_keyDown && _state != null)
        {
            TogglePause();
        }
        _keyDown = down;
        if (_paused || _busy || _choosing || _state == null) return;
        var manager = CombatManager.Instance;
        if (!manager.IsInProgress || manager.IsOverOrEnding || manager.PlayerActionsDisabled
            || RunManager.Instance.ActionExecutor.IsRunning
            || _state.Players[0].PlayerCombatState?.Phase != PlayerTurnPhase.Play
            || manager.IsPlayerReadyToEndTurn(_state.Players[0])) return;
        _ = DecideAsync(_generation.Token);
    }

    private async Task<NativeMctsResponse> SearchAsync(string stateKey, CancellationToken token)
    {
        var checkpoint = NativeCombatCheckpoint.Latest ?? throw new InvalidOperationException("No combat-entry checkpoint; enter a new battle.");
        NativeMctsResponse result;
        _searches++;
        try
        {
            result = await _worker.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, _prefix.ToArray(), stateKey, _entryHp), token);
        }
        finally { _searches--; }
        Console.WriteLine($"[SlayTheModel] MCTS simulations={result.Simulations} retained={result.RetainedVisits} ms={result.SearchMilliseconds:F0} rebuilt={result.Rebuilt} action={result.Action?.Key}");
        return result;
    }

    private async Task DecideAsync(CancellationToken token)
    {
        _busy = true;
        try
        {
            var key = NativeCombatCheckpoint.StateKey() + ":play";
            var result = await SearchAsync(key, token);
            token.ThrowIfCancellationRequested();
            if (_paused || _state == null) return;
            if (key != NativeCombatCheckpoint.StateKey() + ":play")
            {
                _worker.Dispose();
                Console.WriteLine("[SlayTheModel] actual state changed; discarding search and rebuilding.");
                return;
            }
            var action = result.Action?.Combat ?? throw new InvalidDataException("Worker returned no combat action.");
            if (!CombatCaptureService.GetLegalActions(_state).Contains(action)) throw new InvalidDataException("Worker action is no longer legal.");
            await CombatActionExecutor.ExecuteAsync(_state, action);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception exception) { Pause(exception.ToString()); }
        finally { _busy = false; }
    }

    private void Pause(string reason, bool faulted = true)
    {
        _paused = true;
        _faulted = faulted;
        _generation.Cancel();
        _generation.Dispose();
        _generation = new CancellationTokenSource();
        _worker.Dispose();
        Console.Error.WriteLine("[SlayTheModel] MCTS paused: " + reason);
    }

    public async Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        _choosing = true;
        var cards = options.ToArray();
        try
        {
            if (!_paused)
            {
                try
                {
                    var key = NativeCombatCheckpoint.StateKey() + $":choice:{minSelect}:{maxSelect}:" + string.Join(",", cards.Select(card => card.Id.Entry));
                    var response = await SearchAsync(key, _generation.Token);
                    var indices = response.Action?.Selection ?? throw new InvalidDataException("Worker returned no selection.");
                    if (indices.Distinct().Count() != indices.Length || indices.Any(i => i < 0 || i >= cards.Length)
                        || indices.Length < Math.Min(minSelect, cards.Length) || indices.Length > maxSelect)
                        throw new InvalidDataException("Worker returned an invalid selection.");
                    _prefix.Add(response.Action!);
                    return indices.Select(i => cards[i]).ToArray();
                }
                catch (OperationCanceledException) when (_paused || _state == null) { }
                catch (Exception exception) { Pause(exception.ToString()); }
            }
            if (_state == null || CombatManager.Instance.IsOverOrEnding) return [];
            // Retain a usable native UI when search is paused or a choice cannot be simulated.
            var prefs = new CardSelectorPrefs(new MegaCrit.Sts2.Core.Localization.LocString("gameplay_ui", "CHOOSE_CARD_HEADER"), minSelect, maxSelect);
            var screen = NSimpleCardSelectScreen.Create(cards, prefs);
            (NOverlayStack.Instance ?? throw new InvalidOperationException("Manual selection UI unavailable.")).Push(screen);
            var selected = (await screen.CardsSelected()).ToArray();
            var selectedIndices = selected.Select(card => Array.IndexOf(cards, card)).ToArray();
            _prefix.Add(new SearchAction("choose:" + string.Join(",", selectedIndices), Selection: selectedIndices));
            return selected;
        }
        finally { _choosing = false; }
    }

    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options, IReadOnlyList<CardRewardAlternative> alternatives)
        => throw new NotSupportedException("Run rewards are manual.");
}
