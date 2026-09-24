using System.Security.Cryptography;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.Unlocks;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;
using SlayTheModel.Search;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using CombatSolver.Api;

// One engine process owns exactly one native session. Cloning is deterministic
// reconstruction plus input replay, never a shallow copy of game singletons.
public sealed class NativeSession(Node host) : ICardSelector, IReplayEnvironment<SearchAction>
{
    private static readonly string AssemblyHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(RunManager).Assembly.Location)));
    public NativeCombatCheckpoint? Checkpoint { get; set; }
    public int EntryHp { get; set; } = 80;
    public bool ChoiceFixture { get; set; }
    public string[] ChoiceFixtureCards { get; set; } =
        ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
    public HashSet<string> ChoiceFixtureUpgradedCards { get; set; } = [];
    public string Seed { get; set; } = "SLAYMODEL1";
    public string EncounterId { get; set; } = "CULTISTS_NORMAL";
    private Player _player = null!;
    private CombatState _state = null!;
    private TaskCompletionSource<IEnumerable<CardModel>>? _choice;
    private CardModel[] _options = [];
    private int _min;
    private int _max;
    private GameAction? _action;
    private IDisposable? _selector;
    private CancellationToken _activeCancellation;
    public int Hp => _player.Creature.CurrentHp;
    public int Round => _state.RoundNumber;
    public bool Terminal => _player.Creature.IsDead || CombatManager.Instance.IsOverOrEnding;
    public bool Won => Terminal && !_player.Creature.IsDead && !_state.Enemies.Any(enemy => enemy.IsAlive);
    public int InitialEnemyEffectiveHp { get; private set; }
    public int EnemyDamageLost { get; private set; }

    public void BeginTrajectoryAtCurrentState()
    {
        if (_state == null || Terminal || HasPendingChoice || Actions().Count == 0)
            throw new InvalidOperationException("A mid-combat trajectory must begin at a settled legal decision.");
        EntryHp = Hp;
        InitialEnemyEffectiveHp = _state.Enemies.Sum(enemy => Math.Max(enemy.CurrentHp, 0));
        EnemyDamageLost = 0;
    }

    public async Task SetInitialHpFixtureAsync(int hp, CancellationToken cancellation)
    {
        if (_state == null || Terminal || HasPendingChoice || hp < 1 || hp > _player.Creature.MaxHp)
            throw new ArgumentOutOfRangeException(nameof(hp), "Low-HP fixture requires a legal live combat root.");
        await CreatureCmd.SetCurrentHp(_player.Creature, hp);
        await SettleAsync(cancellation);
        if (Hp != hp || Terminal || HasPendingChoice)
            throw new InvalidDataException("Native low-HP fixture did not settle at a legal decision.");
        BeginTrajectoryAtCurrentState();
    }
    public long Transitions { get; private set; }
    public CombatState CombatStateForSimulation => _state;
    public bool HasPendingChoice => _choice != null;
    public string ChoiceSignature => _choice == null
        ? ""
        // The native selector may retain its requested maximum even when fewer
        // cards exist. Search exposes only realizable subsets, so compare the
        // effective bounds and distinct model IDs on both sides. For example,
        // Neow's Fury requests 0-2 cards but a one-card discard pile permits 0-1.
        : FormatChoiceSignature(_min, _max, _options);
    public Task RestoreAsync(IReadOnlyList<SearchAction> prefix, CancellationToken cancellation) => RestoreAsync(Seed, prefix, cancellation);
    public Task ApplyAsync(SearchAction action, CancellationToken cancellation) => StepAsync(action, cancellation);
    public IReadOnlyList<SearchAction> LegalActions() => Actions();
    public string StateKey() => Fingerprint();

    internal static string FormatChoiceSignature(
        int minSelect, int maxSelect, IReadOnlyCollection<CardModel> options)
        => $"{Math.Min(minSelect, options.Count)}:{Math.Min(maxSelect, options.Count)}:"
            + string.Join(',', options.Select(card => card.Id.Entry).Distinct().Order());
    public IReadOnlyList<string> ActionsForDiagnostics()
        => Actions().Select(DescribeAction).ToArray();

    public SearchAction ToLiveSearchAction(CombatSolverMctsAction action)
    {
        NativeMctsAction predicted = action.Native;
        // A live selector is already pending after the trigger card has been
        // executed. The MCTS result at this point is the choice-layer action,
        // not another PlayCard transition. Prefer the live pending state and
        // require a concrete selected-card payload so nested choice paths are
        // never silently converted into a duplicate card play.
        if (_choice != null)
        {
            if (predicted.SelectedCards is null)
                throw new InvalidDataException($"Pending live choice action lacks selected-card payload: {predicted.Key}");
            int[] indices = NativeMctsSimulationApi.ResolveLiveSelection(_options, predicted);
            if (indices.Length < Math.Min(_min, _options.Length)
                || indices.Length > Math.Min(_max, _options.Length))
                throw new InvalidDataException($"Pending live choice action selected {indices.Length} cards, expected {_min}..{_max}: {predicted.Key}");
            return new SearchAction(predicted.Key, Selection: indices);
        }
        if (predicted.ChoiceKey != null)
            throw new InvalidDataException($"Choice action was supplied without a live pending selector: {predicted.Key}");
        if (predicted.Kind == "EndTurn")
        {
            var end = new CombatActionDescriptor(CombatActionKind.EndTurn, _player.NetId);
            return new SearchAction(predicted.Key, end);
        }
        if (predicted.Kind != "PlayCard")
            throw new InvalidOperationException($"Unsupported prediction action {predicted.Kind}.");
        var card = NativeMctsSimulationApi.ResolveLiveCard(_state, predicted);
        var play = new CombatActionDescriptor(
            CombatActionKind.PlayCard,
            _player.NetId,
            NetCombatCard.FromModel(card).CombatCardIndex,
            TargetCreatureId: predicted.TargetCombatId);
        if (!card.CanPlay()) throw new InvalidOperationException($"Predicted card {predicted.CardId} is no longer playable.");
        if (predicted.TargetCombatId is uint targetId)
        {
            var target = _state.Creatures.Single(creature => creature.CombatId == targetId);
            if (!card.CanPlayTargeting(target))
                throw new InvalidOperationException($"Predicted target {targetId} is no longer legal.");
        }
        return new SearchAction(predicted.Key, play);
    }

    public void ValidateSimulationActions(IReadOnlyList<CombatSolverMctsAction> actions)
    {
        foreach (var action in actions) _ = ToLiveSearchAction(action);
    }

    public double EvaluateTerminal() => Won
        ? 0.5 + Math.Atan((Hp - EntryHp) / 20.0) / Math.PI
        : -1.0 + 0.25 * Math.Clamp(EnemyDamageLost / (double)Math.Max(InitialEnemyEffectiveHp, 1), 0, 1);
    public double EvaluateUnresolved() => -0.5
        + 0.25 * Math.Clamp(EnemyDamageLost / (double)Math.Max(InitialEnemyEffectiveHp, 1), 0, 1);
    public SearchAction RolloutAction(IReadOnlyList<SearchAction> actions, Random random) =>
        random.Next(2) == 0 ? Heuristic(actions) : AttackFirst(actions);

    public async Task ResetAsync(string seed, CancellationToken cancellation)
    {
        _activeCancellation = cancellation;
        cancellation.ThrowIfCancellationRequested();
        var pendingChoice = _choice;
        _choice = null;
        pendingChoice?.TrySetCanceled();
        await DrainActiveActionAsync();
        _selector?.Dispose();
        RunManager.Instance.CleanUp(false);
        LocalContext.NetId = 1;
        _action = null;
        if (Checkpoint is null)
        {
            _player = Player.CreateForNewRun<Ironclad>(UnlockState.all, 1);
            if (ChoiceFixture)
            {
                _player.Deck.Clear();
                foreach (string entry in ChoiceFixtureCards)
                {
                    var canonical = ModelDb.AllCards.Single(card => card.Id.Entry == entry);
                    var card = canonical.ToMutable();
                    if (ChoiceFixtureUpgradedCards.Contains(entry))
                    {
                        HarmonyLib.AccessTools.Method(card.GetType(), "UpgradeInternal").Invoke(card, null);
                        HarmonyLib.AccessTools.Method(card.GetType(), "FinalizeUpgradeInternal").Invoke(card, null);
                    }
                    _player.Deck.AddInternal(card);
                }
            }
            var run = RunState.CreateForTest([_player], seed: seed);
            RunManager.Instance.SetUpTest(run, new NetSingleplayerGameService());
            _selector = CardSelectCmd.PushSelector(this);
            var encounter = ModelDb.All.OfType<EncounterModel>().Single(candidate =>
                candidate.Id.Entry.Equals(EncounterId, StringComparison.OrdinalIgnoreCase)
                || candidate.GetType().Name.Equals(EncounterId, StringComparison.OrdinalIgnoreCase));
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter.ToMutable());
        }
        else
        {
            await RestoreCheckpointAsync(Checkpoint);
        }
        _state = CombatManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("Combat not created.");
        InitialEnemyEffectiveHp = _state.Enemies.Sum(enemy => Math.Max(enemy.CurrentHp, 0));
        EnemyDamageLost = 0;
        await SettleAsync(cancellation);
    }

    private async Task DrainActiveActionAsync()
    {
        if (_action != null)
            await ObserveCleanupAsync(_action.CompletionTask, "Native action did not stop during reconstruction.");
        var executor = RunManager.Instance.ActionExecutor;
        if (executor != null)
            await ObserveCleanupAsync(executor.FinishedExecutingActions(), "Native action queue did not stop during reconstruction.");
        _action = null;
    }

    private static async Task ObserveCleanupAsync(Task task, string timeoutMessage)
    {
        try { await task.WaitAsync(TimeSpan.FromSeconds(3)); }
        catch (TimeoutException) { throw new TimeoutException(timeoutMessage); }
        catch (OperationCanceledException) { }
        catch { /* An interrupted rollout may fault; completion, not success, is required here. */ }
    }

    private async Task RestoreCheckpointAsync(NativeCombatCheckpoint checkpoint)
    {
        if (AssemblyHash != checkpoint.AssemblyHash) throw new InvalidDataException("Checkpoint game assembly differs.");
        var save = NativeCombatCheckpoint.Decode<MegaCrit.Sts2.Core.Saves.SerializableRun>(checkpoint.RunPacket);
        var run = RunState.FromSerializable(save);
        run.ActFloor = checkpoint.ActFloor;
        _player = run.Players.Single();
        LocalContext.NetId = _player.NetId;
        var manager = RunManager.Instance;
        // Version-pinned native initialization without new-run hooks or save reloads.
        // No ShouldSave=true path is used in this isolated process.
        HarmonyLib.AccessTools.Property(typeof(RunManager), "State").SetValue(manager, run);
        var net = new NetSingleplayerGameService();
        HarmonyLib.AccessTools.Method(typeof(RunManager), "InitializeShared").Invoke(manager,
            [net, new MegaCrit.Sts2.Core.Multiplayer.Game.PeerInput.PeerInputSynchronizer(net), false,
                null, 0L, 0L, 0L, 0]);
        HarmonyLib.AccessTools.Method(typeof(RunManager), "InitializeRunLobby").Invoke(manager,
            [net, run, Array.Empty<RunLobbyPlayer>()]);
        manager.CombatStateSynchronizer.IsDisabled = true;
        manager.ActionQueueSet.FastForwardNextActionId(checkpoint.NextActionId);
        manager.ActionQueueSynchronizer.FastForwardHookId(checkpoint.NextHookId);
        manager.PlayerChoiceSynchronizer.FastForwardChoiceIds(checkpoint.ChoiceIds);
        manager.RewardsSetSynchronizer.FastForwardRewardIds(checkpoint.RewardIds);
        _selector = CardSelectCmd.PushSelector(this);
        var room = CombatRoom.FromSerializable(
            NativeCombatCheckpoint.Decode<MegaCrit.Sts2.Core.Saves.Runs.SerializableRoom>(checkpoint.RoomPacket), run);
        run.PushRoom(room);
        await room.EnterInternal(run, false);
    }

    public async Task RestoreAsync(string seed, IReadOnlyList<SearchAction> prefix, CancellationToken cancellation)
    {
        await ResetAsync(seed, cancellation);
        foreach (var action in prefix) await StepAsync(action, cancellation);
    }

    public IReadOnlyList<SearchAction> Actions()
    {
        if (Terminal) return [];
        if (_choice != null)
        {
            var choices = new List<SearchAction>();
            for (var count = Math.Min(_min, _options.Length); count <= Math.Min(_max, _options.Length); count++)
                Enumerate([], 0, count, choices);
            return choices;
        }
        return CombatCaptureService.GetLegalActions(_state).Select(action =>
            new SearchAction($"{action.Kind}:{action.CombatCardIndex}:{action.TargetCreatureId}", action)).ToArray();
    }

    private void Enumerate(List<int> selected, int start, int remaining, List<SearchAction> result)
    {
        _activeCancellation.ThrowIfCancellationRequested();
        if (remaining == 0)
        {
            var indices = selected.ToArray();
            result.Add(new SearchAction("choose:" + string.Join(",", indices), Selection: indices));
            return;
        }
        for (var i = start; i <= _options.Length - remaining; i++)
        {
            selected.Add(i);
            Enumerate(selected, i + 1, remaining - 1, result);
            selected.RemoveAt(selected.Count - 1);
        }
    }

    public async Task StepAsync(SearchAction input, CancellationToken cancellation)
    {
        _activeCancellation = cancellation;
        cancellation.ThrowIfCancellationRequested();
        var legal = Actions();
        if (!legal.Any(action => action.Combat == input.Combat
            && (action.Selection ?? []).Order().SequenceEqual((input.Selection ?? []).Order())))
            throw new InvalidOperationException("Illegal replay action " + input.Key
                + $" selection=[{string.Join(',', input.Selection ?? [])}]"
                + $" pending={_choice != null} min={_min} max={_max} options={_options.Length}"
                + $" legal=[{string.Join(';', legal.Select(DescribeAction))}]");
        Transitions++;
        if (input.Selection is { } indices)
        {
            var pending = _choice ?? throw new InvalidOperationException("No pending selection.");
            var selected = indices.Select(index => _options[index]).ToArray();
            _choice = null;
            pending.SetResult(selected);
        }
        else
        {
            _action = CombatActionExecutor.CreateGameAction(_state, input.Combat!);
            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(_action);
        }
        int enemyHpBefore = _state.Enemies.Sum(enemy => Math.Max(enemy.CurrentHp, 0));
        try { await SettleAsync(cancellation); }
        catch (OperationCanceledException) when (cancellation.IsCancellationRequested)
        {
            var pendingChoice = _choice;
            _choice = null;
            pendingChoice?.TrySetCanceled(cancellation);
            await DrainActiveActionAsync();
            // Completion tasks can schedule additional continuations onto
            // Godot's synchronization context. Flush them before a later
            // reconstruction reuses the process, otherwise an old cancelled
            // choice can mutate the newly restored combat on slower hosts.
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await DrainActiveActionAsync();
            throw;
        }
        int enemyHpAfter = _state.Enemies.Sum(enemy => Math.Max(enemy.CurrentHp, 0));
        EnemyDamageLost += Math.Max(0, enemyHpBefore - enemyHpAfter);
    }

    private static string DescribeAction(SearchAction action)
    {
        if (action.Selection is { } selection)
            return $"choice:[{string.Join(',', selection)}]";
        if (action.Combat is not { } combat) return action.Key;
        return $"{combat.Kind}:player={combat.ActorPlayerId}:card={combat.CombatCardIndex?.ToString() ?? "-"}"
            + $":target={combat.TargetCreatureId?.ToString() ?? "-"}:potion={combat.PotionIndex?.ToString() ?? "-"}";
    }

    private async Task SettleAsync(CancellationToken cancellation)
    {
        var deadline = System.Diagnostics.Stopwatch.StartNew();
        while (true)
        {
            cancellation.ThrowIfCancellationRequested();
            if (_action?.Exception is { } error) throw new InvalidOperationException("Native action failed", error);
            var executor = RunManager.Instance.ActionExecutor;
            if (executor.FinishedExecutingActions().Exception is { } queueError)
                throw new InvalidOperationException("Native action queue failed", queueError);
            if (_choice != null || (Terminal && !executor.IsRunning)) return;
            var manager = CombatManager.Instance;
            // The native single-player turn loop enqueues phase-two readiness.
            // Do not bypass it: its ordering is part of deterministic replay.
            if (_player.PlayerCombatState?.Phase == PlayerTurnPhase.Play
                && !manager.PlayerActionsDisabled
                && !RunManager.Instance.ActionExecutor.IsRunning
                && (_action == null || _action.CompletionTask.IsCompleted)
                && !manager.IsPlayerReadyToEndTurn(_player)) return;
            if (deadline.Elapsed > TimeSpan.FromSeconds(3)) throw new TimeoutException("Native combat did not reach a decision.");
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }

    public string Fingerprint()
    {
        if (Terminal) return $"terminal:{Won}:{Hp}";
        var writer = new PacketWriter();
        var run = RunManager.Instance.DebugOnlyGetState()!;
        writer.Write(NetFullCombatState.FromRun(run, null));
        var payload = writer.Buffer.Take(writer.BytePosition).ToArray();
        return Convert.ToHexString(SHA256.HashData(payload)) + ":" +
            (_choice == null ? "play" : $"choice:{_min}:{_max}:" + string.Join(",", _options.Select(card => card.Id.Entry)));
    }

    public SearchAction Heuristic(IReadOnlyList<SearchAction> actions)
    {
        if (_choice != null) return actions[0];
        var incoming = _state.Enemies.Where(enemy => enemy.IsAlive).Sum(enemy =>
            enemy.Monster?.NextMove.Intents.OfType<AttackIntent>().Sum(intent => intent.GetTotalDamage([_player.Creature], enemy)) ?? 0);
        var deficit = Math.Max(0, incoming - _player.Creature.Block);
        double Score(SearchAction action)
        {
            if (action.Combat?.Kind == CombatActionKind.EndTurn) return -1000;
            var card = _player.PlayerCombatState!.Hand.Cards.Single(candidate =>
                NetCombatCard.FromModel(candidate).CombatCardIndex == action.Combat!.CombatCardIndex);
            var target = _state.Creatures.FirstOrDefault(creature => creature.CombatId == action.Combat!.TargetCreatureId);
            var damage = 0m;
            if (card.DynamicVars.TryGetValue("Damage", out var variable) && variable is DamageVar damageVar)
            {
                damageVar.UpdateCardPreview(card, CardPreviewMode.Normal, target, true);
                damage = damageVar.PreviewValue;
            }
            // This is a heuristic, not a general lethal proof for arbitrary card text.
            // Recognize the starter single-hit attacks; all outcomes still use native logic.
            if (target != null && (card.Id.Entry == "STRIKE_IRONCLAD" || card.Id.Entry == "BASH")
                && target.Powers.Count == 0 && damage >= target.CurrentHp + target.Block) return 10000;
            if (card.GainsBlock && deficit > 0) return 1000;
            return card.Type == CardType.Attack ? 100 + (double)damage : card.GainsBlock ? -10 : 0;
        }
        return actions.OrderByDescending(Score).First();
    }

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        if (_choice != null) throw new InvalidOperationException("Overlapping selections.");
        _options = options.ToArray();
        _min = minSelect;
        _max = maxSelect;
        _choice = new TaskCompletionSource<IEnumerable<CardModel>>(TaskCreationOptions.RunContinuationsAsynchronously);
        return _choice.Task;
    }

    public SearchAction AttackFirst(IReadOnlyList<SearchAction> actions)
    {
        if (_choice != null) return actions[0];
        return actions.OrderBy(action => action.Combat?.Kind == CombatActionKind.EndTurn ? 10 :
            _player.PlayerCombatState!.Hand.Cards.Single(card => NetCombatCard.FromModel(card).CombatCardIndex == action.Combat!.CombatCardIndex).Type
                == CardType.Attack ? 0 : 1).First();
    }

    public SearchAction ActionForCard(string entry) => Actions().First(action => action.Combat?.Kind == CombatActionKind.PlayCard
        && _player.PlayerCombatState!.Hand.Cards.Any(card => card.Id.Entry == entry && NetCombatCard.FromModel(card).CombatCardIndex == action.Combat.CombatCardIndex));

    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options, IReadOnlyList<CardRewardAlternative> alternatives)
        => throw new NotSupportedException("Run rewards are outside the combat worker.");
}
