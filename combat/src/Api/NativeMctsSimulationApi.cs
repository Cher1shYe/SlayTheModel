using MegaCrit.Sts2.Core.Combat;
using CombatSolver.Engine.InCombat.Simulation;
using CombatSolver.Engine.Common;
using System.Security.Cryptography;
using System.Text;
using SlayTheModel.Sts2.Protocol;

namespace CombatSolver.Api;

public sealed record NativeMctsSelectedCard(string CardId, int UpgradeLevel, string StateKey, int OptionOccurrence);

public sealed record NativeMctsChoiceCandidate(
    uint CombatCardIndex, string ModelId, int UpgradeLevel,
    string InternalStateKey, int OptionOccurrence);

public sealed record NativeMctsChoiceFrame(
    CombatObservation Observation, string TriggerCardId, string Effect, string SourcePile,
    int MinCount, int MaxCount, bool Ordered,
    IReadOnlyList<NativeMctsChoiceCandidate> Candidates,
    IReadOnlyList<CombatCompletedChoiceObservation> CompletedSelections);

public sealed record NativeMctsAction(
    string Key,
    string Kind,
    string CardId,
    int CardOccurrence,
    string CardStateKey,
    int CardStateOccurrence,
    int CardUpgradeLevel,
    string CardEnchantmentId,
    uint? TargetCombatId,
    string CardType = "",
    bool GainsBlock = false,
    decimal Damage = 0,
    int? TargetHp = null,
    string? ChoiceKey = null,
    IReadOnlyList<NativeMctsSelectedCard>? SelectedCards = null);

public sealed record NativeMctsState(
    string Key,
    bool Terminal,
    bool Won,
    bool Defeated,
    bool Resolved,
    int PlayerHp,
    int EnemyHpLost,
    int EnemyHpTotal,
    int IncomingDamage,
    bool PendingChoice,
    IReadOnlyList<NativeMctsAction> LegalActions);

/// <summary>Prediction-only API for an external MCTS host. It never runs Combat Solver's Beam search.</summary>
public sealed class NativeMctsSimulationSession : IDisposable
{
    private readonly CombatBeamSolver driver;
    private readonly CombatRootSnapshot capturedRoot;
    private SimulationSnapshot root;
    private SimulationSnapshot current;
    private readonly NativeMctsState rootDescription;
    private NativeMctsState currentDescription;
    private readonly List<SimulationSnapshot> transient = [];
    private sealed record PendingChoiceBranch(PlanAction Action, SimulationSnapshot Snapshot);
    private sealed record PendingChoiceGroup(IReadOnlyList<PendingChoiceBranch> Branches, int ChoiceIndex);
    private Dictionary<string, PendingChoiceGroup>? pendingChoices;
    private IReadOnlyList<string> choiceDiagnostics = [];
    private NativeMctsChoiceFrame? pendingChoiceFrame;
    private IReadOnlyDictionary<string, NativeMctsChoiceFrame> choiceFramesAfterPrefix
        = new Dictionary<string, NativeMctsChoiceFrame>();
    private readonly List<CombatCompletedChoiceObservation> completedSelections = [];
    private int actionCount;
    private readonly int initialEnemyHp;
    private bool disposed;

    internal NativeMctsSimulationSession(CombatRootSnapshot capturedRoot)
    {
        this.capturedRoot = capturedRoot;
        driver = NativeMctsSimulation.CreateDriver(capturedRoot);
        initialEnemyHp = capturedRoot.InitialEnemyEffectiveHp;
        root = driver.NativeMctsCreateRoot();
        current = root;
        rootDescription = driver.NativeMctsDescribe(root, 0);
        currentDescription = rootDescription;
    }

    public NativeMctsState RestoreRoot()
    {
        ThrowIfDisposed();
        ReleasePendingChoices();
        pendingChoiceFrame = null;
        choiceFramesAfterPrefix = new Dictionary<string, NativeMctsChoiceFrame>();
        completedSelections.Clear();
        ReleaseTransient();
        current = root;
        actionCount = 0;
        currentDescription = rootDescription;
        return currentDescription;
    }

    public IReadOnlyList<string> ChoiceDiagnostics => choiceDiagnostics;

    public NativeMctsState Apply(NativeMctsAction action)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(action);
        if (pendingChoices != null)
        {
            if (!pendingChoices.TryGetValue(action.Key, out var selectedGroup))
                throw new InvalidOperationException($"Unknown prediction choice action {action.Key}.");
            if (pendingChoiceFrame is { } frame)
            {
                var selected = (action.SelectedCards ?? throw new InvalidDataException("Choice has no selected-card payload."))
                    .Select(token => frame.Candidates.Single(candidate =>
                        candidate.InternalStateKey == token.StateKey
                        && candidate.OptionOccurrence == token.OptionOccurrence).CombatCardIndex).ToArray();
                completedSelections.Add(new CombatCompletedChoiceObservation(frame.Effect, selected));
            }
            foreach (var group in pendingChoices.Values.Where(group => !ReferenceEquals(group, selectedGroup)))
                ReleaseBranches(group.Branches);
            pendingChoices = null;

            int nextIndex = selectedGroup.ChoiceIndex + 1;
            var withMoreChoices = selectedGroup.Branches
                .Where(branch => ChoiceCount(branch.Action) > nextIndex)
                .GroupBy(branch => NativeMctsSimulation.ChoiceKey(
                    branch.Action, branch.Action, nextIndex), StringComparer.Ordinal)
                .ToDictionary(group => group.Key,
                    group => new PendingChoiceGroup(group.ToArray(), nextIndex),
                    StringComparer.Ordinal);
            if (withMoreChoices.Count > 0)
            {
                ReleaseBranches(selectedGroup.Branches
                    .Where(branch => ChoiceCount(branch.Action) <= nextIndex));
                pendingChoices = withMoreChoices;
                pendingChoiceFrame = choiceFramesAfterPrefix.TryGetValue(action.Key, out var nextFrame)
                    ? nextFrame with { CompletedSelections = completedSelections.ToArray() }
                    : null;
                currentDescription = BuildPendingDescription();
                return currentDescription;
            }

            PendingChoiceBranch final = selectedGroup.Branches
                .Single(branch => ChoiceCount(branch.Action) == nextIndex);
            ReleaseBranches(selectedGroup.Branches.Where(branch => !ReferenceEquals(branch, final)));
            current = final.Snapshot;
            pendingChoiceFrame = null;
            completedSelections.Clear();
            transient.Add(current);
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var expansion = driver.NativeMctsExpand(current, action, actionCount);
        choiceDiagnostics = expansion.ChoiceDiagnostics;
        if (expansion.Resolved.Count == 0)
            throw new InvalidOperationException($"Prediction action {action.Key} produced no resolved state.");
        if (expansion.Resolved.Count == 1 && expansion.Resolved[0].Action.Choice == null
            && expansion.Resolved[0].Action.NestedChoices is not { Count: > 0 }
            && expansion.Resolved[0].Action.TurnStartChoices is not { Count: > 0 })
        {
            current = expansion.Resolved[0].Snapshot;
            transient.Add(current);
            actionCount++;
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var branches = expansion.Resolved
            .Select(item => new PendingChoiceBranch(item.Action, item.Snapshot))
            .ToArray();
        pendingChoices = branches
            .GroupBy(branch => NativeMctsSimulation.ChoiceKey(
                expansion.BaseAction, branch.Action, 0), StringComparer.Ordinal)
            .ToDictionary(group => group.Key,
                group => new PendingChoiceGroup(group.ToArray(), 0),
                StringComparer.Ordinal);
        pendingChoiceFrame = expansion.FirstChoiceFrame;
        choiceFramesAfterPrefix = expansion.FramesAfterPrefix ?? new Dictionary<string, NativeMctsChoiceFrame>();
        actionCount++;
        currentDescription = BuildPendingDescription();
        return currentDescription;
    }

    public NativeMctsState DescribeCurrent()
    {
        ThrowIfDisposed();
        return currentDescription;
    }

    public CombatObservation ObserveCurrent()
    {
        ThrowIfDisposed();
        if (pendingChoices != null)
            return pendingChoiceFrame?.Observation ?? throw new PredictionUnsupportedException(
                "Choice layer has no captured pre-selection observation; resolved branches contain future selections.");
        return driver.NativeMctsObserve(current);
    }

    public NativeMctsChoiceFrame CurrentChoiceFrame
        => pendingChoices != null && pendingChoiceFrame != null
            ? pendingChoiceFrame
            : throw new PredictionUnsupportedException(
                "Choice layer has no captured pre-selection context.");

    public string ContinuationKey
    {
        get
        {
            var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)current.Simulator;
            string text = ContinuationStamp.CapturePredicted(
                capturedRoot.PlayerIdentity,
                simulator,
                current.Turn,
                capturedRoot.Forecast,
                capturedRoot.StartTurnNumber).StateText;
            return Hash(text);
        }
    }

    public string ContinuationStateText
    {
        get
        {
            var simulator = (CombatSolver.Engine.InCombat.Simulation.CombatPredictionSimulator)current.Simulator;
            return ContinuationStamp.CapturePredicted(
                capturedRoot.PlayerIdentity,
                simulator,
                current.Turn,
                capturedRoot.Forecast,
                capturedRoot.StartTurnNumber).StateText;
        }
    }

    private NativeMctsState BuildPendingDescription()
    {
        var actions = pendingChoices!.Select(pair =>
        {
            PendingChoiceBranch branch = pair.Value.Branches[0];
            return NativeMctsSimulation.ToPublicAction(branch.Action, pair.Key,
                choiceKey: pair.Key, choiceIndex: pair.Value.ChoiceIndex);
        }).ToArray();
        var combatState = (SimulatedCombatState)((CombatPredictionSimulator)current.Simulator).State.CombatState;
        int enemyHpLost = combatState.KnownEnemies.Sum(combatState.GetMctsCumulativeEnemyHpLost);
        return new NativeMctsState(
            NativeMctsSimulation.PendingStateKey(current.StateKey, actions),
            false, false, false, false, current.PlayerHp, enemyHpLost,
            initialEnemyHp, 0, true, actions);
    }

    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        ReleasePendingChoices();
        ReleaseTransient();
        root.ReleaseSimulator();
    }

    private void ReleaseTransient()
    {
        HashSet<SimulationSnapshot> unique = new(transient, ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique)
            snapshot.ReleaseSimulator();
        transient.Clear();
    }

    private void ReleasePendingChoices()
    {
        if (pendingChoices == null) return;
        HashSet<SimulationSnapshot> unique = new(
            pendingChoices.Values.SelectMany(candidate => candidate.Branches).Select(candidate => candidate.Snapshot),
            ReferenceEqualityComparer.Instance);
        foreach (var snapshot in unique) snapshot.ReleaseSimulator();
        pendingChoices = null;
        pendingChoiceFrame = null;
    }

    private static int ChoiceCount(PlanAction action)
        => action.GetActionChoicesInExecutionOrder().Count;

    private static void ReleaseBranches(IEnumerable<PendingChoiceBranch> branches)
    {
        var unique = new HashSet<SimulationSnapshot>(
            branches.Select(branch => branch.Snapshot), ReferenceEqualityComparer.Instance);
        foreach (SimulationSnapshot snapshot in unique)
            snapshot.ReleaseSimulator();
    }

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(disposed, this);

    private static string Hash(string value)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
}

public static class NativeMctsSimulationApi
{
    private static int initialized;

    public static void Initialize()
    {
        if (Interlocked.Exchange(ref initialized, 1) != 0) return;
        Entry.InitializeSimulationRuntime();
    }

    public static NativeMctsSimulationSession Capture(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        Initialize();
        return new NativeMctsSimulationSession(CombatRootSnapshot.Capture(state));
    }

    public static MegaCrit.Sts2.Core.Models.CardModel ResolveLiveCard(
        CombatState state, NativeMctsAction action)
    {
        var player = MegaCrit.Sts2.Core.Context.LocalContext.GetMe(state)
            ?? throw new InvalidOperationException("Local player is unavailable.");
        var hand = player.PlayerCombatState?.Hand.Cards
            ?? throw new InvalidOperationException("Live hand is unavailable.");
        int occurrence = action.CardStateOccurrence;
        foreach (var card in hand)
        {
            if (!string.Equals(CardChoiceSupport.ChoiceCardKey(card), action.CardStateKey, StringComparison.Ordinal))
                continue;
            if (occurrence-- == 0) return card;
        }
        throw new InvalidOperationException($"Live card identity {action.CardStateKey}#{action.CardStateOccurrence} is unavailable.");
    }

    public static int[] ResolveLiveSelection(
        IReadOnlyList<MegaCrit.Sts2.Core.Models.CardModel> options, NativeMctsAction action)
    {
        var result = new List<int>();
        foreach (NativeMctsSelectedCard selected in action.SelectedCards ?? [])
        {
            int occurrence = selected.OptionOccurrence;
            int found = -1;
            for (int index = 0; index < options.Count; index++)
            {
                if (!string.Equals(CardChoiceSupport.ChoiceCardKey(options[index]), selected.StateKey, StringComparison.Ordinal))
                    continue;
                if (occurrence-- == 0) { found = index; break; }
            }
            if (found < 0) throw new InvalidOperationException($"Live choice identity {selected.StateKey} is unavailable.");
            result.Add(found);
        }
        return result.ToArray();
    }

    public static string CaptureLiveContinuationKey(CombatState state)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            ContinuationStamp.CaptureLive(state).StateText)));

    public static string CaptureLiveContinuationStateText(CombatState state)
        => ContinuationStamp.CaptureLive(state).StateText;
}
