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
    IReadOnlyList<CombatCompletedChoiceObservation> CompletedSelections)
{
    // The frame is captured at the pending boundary, before any candidate is
    // applied. Both tree evaluation and export use this one projection.
    public CombatObservation ToPolicyObservation()
    {
        ValidateFrame();
        var choice = new CombatChoiceObservation(TriggerCardId, Effect, SourcePile,
            MinCount, MaxCount, Ordered,
            Candidates.Select(candidate =>
            {
                if (string.IsNullOrWhiteSpace(candidate.ModelId)
                    || string.IsNullOrWhiteSpace(candidate.InternalStateKey))
                    throw new PredictionUnsupportedException("Choice candidate has incomplete identity.");
                return new CombatChoiceCandidateObservation(candidate.CombatCardIndex,
                    candidate.ModelId, candidate.UpgradeLevel);
            }).ToArray(),
            CompletedSelections.Select(previous => new CombatCompletedChoiceObservation(
                previous.Effect, previous.CombatCardIndices.ToArray())).ToArray());
        var observation = Observation with { Choice = choice };
        observation.Validate();
        return observation;
    }

    internal void ValidateFrame()
    {
        if (Observation.Choice != null || string.IsNullOrWhiteSpace(TriggerCardId)
            || string.IsNullOrWhiteSpace(Effect) || string.IsNullOrWhiteSpace(SourcePile)
            || Candidates is null || CompletedSelections is null)
            throw new PredictionUnsupportedException("Choice frame has incomplete or nested observation context.");
        if (MinCount < 0 || MaxCount < MinCount || MaxCount > Candidates.Count)
            throw new PredictionUnsupportedException("Choice frame cardinality is inconsistent with its candidates.");
        if (Candidates.Count == 0 && MaxCount != 0)
            throw new PredictionUnsupportedException("Choice frame has no candidates for a non-empty selection.");
        if (Candidates.Any(candidate => string.IsNullOrWhiteSpace(candidate.ModelId)
                || !candidate.ModelId.StartsWith("CARD.", StringComparison.Ordinal)
                || string.IsNullOrWhiteSpace(candidate.InternalStateKey)))
            throw new PredictionUnsupportedException("Choice candidate has incomplete identity.");
        if (Candidates.Select(candidate => candidate.CombatCardIndex).Distinct().Count()
            != Candidates.Count)
            throw new PredictionUnsupportedException("Choice candidate instance IDs are ambiguous.");
        foreach (var previous in CompletedSelections)
        {
            if (string.IsNullOrWhiteSpace(previous.Effect)
                || previous.CombatCardIndices is null
                || previous.CombatCardIndices.Distinct().Count() != previous.CombatCardIndices.Count)
                throw new PredictionUnsupportedException("Completed choice prefix is invalid.");
        }
    }

    internal IReadOnlyList<uint> ResolveSelection(NativeMctsAction action)
    {
        ValidateFrame();
        if (!string.Equals(action.ChoiceKey, action.Key, StringComparison.Ordinal))
            throw new InvalidDataException("Choice action path does not identify its pending choice layer.");
        var tokens = action.SelectedCards
            ?? throw new InvalidDataException("Choice has no selected-card payload.");
        if (tokens.Count < MinCount || tokens.Count > MaxCount)
            throw new InvalidDataException(
                $"Choice selection count {tokens.Count} is outside [{MinCount}, {MaxCount}].");

        var selected = new List<uint>(tokens.Count);
        var selectedIds = new HashSet<uint>();
        foreach (var token in tokens)
        {
            var candidate = Candidates.SingleOrDefault(item =>
                item.InternalStateKey == token.StateKey
                && item.OptionOccurrence == token.OptionOccurrence);
            if (candidate is null)
                throw new InvalidDataException(
                    $"Choice selection token {token.StateKey}#{token.OptionOccurrence} is not a candidate.");
            if (!CardIdsMatch(candidate.ModelId, token.CardId)
                || candidate.UpgradeLevel != token.UpgradeLevel)
                throw new InvalidDataException(
                    $"Choice selection token identity differs for {token.StateKey}#{token.OptionOccurrence}.");
            if (!selectedIds.Add(candidate.CombatCardIndex))
                throw new InvalidDataException("Choice selection contains a duplicate card instance.");
            selected.Add(candidate.CombatCardIndex);
        }
        return selected;
    }

    private static bool CardIdsMatch(string candidateModelId, string actionCardId)
    {
        if (string.Equals(candidateModelId, actionCardId, StringComparison.Ordinal))
            return true;
        // PlanCardChoice carries the card entry (for example ARMAMENTS), while
        // the public observation carries the typed model ID (CARD.ARMAMENTS).
        const string modelPrefix = "CARD.";
        return candidateModelId.StartsWith(modelPrefix, StringComparison.Ordinal)
            && string.Equals(candidateModelId[modelPrefix.Length..], actionCardId,
                StringComparison.Ordinal);
    }
}

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

public sealed record NativeMctsProbeBoundaryDiagnostic(
    bool PlayerDead,
    bool AllEnemiesDead,
    string? TerminalStamp,
    bool SimulatorIsInProgress,
    bool SimulatorIsEnding,
    bool SimulatorHasPendingChoice,
    bool CombatHasPendingChoice,
    string BoundaryReason);

public sealed record NativeMctsPhaseDiagnostic(double ExclusiveMilliseconds, long ExclusiveAllocatedBytes,
    double InclusiveMilliseconds, long InclusiveAllocatedBytes);

public sealed record NativeMctsDriverDiagnostics(
    bool Enabled,
    int ForkCount,
    int RootForkCount,
    int ReplayCount,
    int ChoiceBranchesEvaluated,
    int ChoiceReplayAttempts,
    int ChoiceReplayBudgetExhaustions,
    int ChoiceBranchesDroppedByBudget,
    int TransitionCount,
    int GeneratedChoiceBranches,
    int ResolvedChoiceBranches,
    IReadOnlyDictionary<string, NativeMctsPhaseDiagnostic> Phases);

/// <summary>Prediction-only API for an external MCTS host. It never runs Combat Solver's Beam search.</summary>
public sealed partial class NativeMctsSimulationSession : IDisposable
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
    public NativeMctsTrajectoryRewardContext RewardContext { get; }
    private bool disposed;
    public NativeMctsProbeBoundaryDiagnostic? LastProbeBoundary { get; private set; }

    public NativeMctsProbeBoundaryDiagnostic CurrentBoundary
    {
        get
        {
            ThrowIfDisposed();
            var simulator = (CombatPredictionSimulator)current.Simulator;
            var combat = (SimulatedCombatState)simulator.State.CombatState;
            return new NativeMctsProbeBoundaryDiagnostic(
                current.PlayerDead, current.AllEnemiesDead, current.TerminalStamp?.ToString(),
                simulator.IsInProgress, simulator.IsEnding,
                simulator.HasPendingChoice, combat.HasPendingChoice,
                current.BoundaryReason.ToString());
        }
    }

    internal NativeMctsSimulationSession(CombatRootSnapshot capturedRoot,
        NativeMctsTrajectoryRewardSeed rewardSeed)
    {
        this.capturedRoot = capturedRoot;
        string boundaryKey = Convert.ToHexString(SHA256.HashData(
            Encoding.UTF8.GetBytes(capturedRoot.ContinuationStamp.StateText)));
        if (!string.Equals(boundaryKey, rewardSeed.CaptureBoundaryKey, StringComparison.Ordinal))
            throw new InvalidDataException("Trajectory reward context does not match the captured combat boundary.");
        if (string.IsNullOrWhiteSpace(rewardSeed.TrajectoryId)
            || string.IsNullOrWhiteSpace(rewardSeed.CaptureBoundaryKey)
            || rewardSeed.CaptureId < 1
            || rewardSeed.EntryHp < 0 || rewardSeed.CapturedEnemyDamagePrefix < 0)
            throw new InvalidDataException("Trajectory reward context contains negative inputs.");
        if (rewardSeed.TrajectoryInitialEnemyEffectiveHp is < 1
            || rewardSeed.TrajectoryInitialEnemyEffectiveHp is null && rewardSeed.CaptureId != 1)
            throw new InvalidDataException("Trajectory reward denominator is missing or invalid.");
        int trajectoryInitialEnemyHp = rewardSeed.TrajectoryInitialEnemyEffectiveHp
            ?? capturedRoot.InitialEnemyEffectiveHp;
        if (trajectoryInitialEnemyHp < 1)
            throw new InvalidDataException("Captured trajectory has no positive effective enemy HP denominator.");
        RewardContext = new NativeMctsTrajectoryRewardContext(
            rewardSeed.TrajectoryId, rewardSeed.CaptureId, rewardSeed.CaptureBoundaryKey,
            rewardSeed.EntryHp, trajectoryInitialEnemyHp,
            rewardSeed.CapturedEnemyDamagePrefix);
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
        LastProbeBoundary = null;
        return currentDescription;
    }

    public IReadOnlyList<string> ChoiceDiagnostics => choiceDiagnostics;

    public NativeMctsDriverDiagnostics DiagnosticSnapshot => driver.NativeMctsDiagnostics();

    public NativeMctsState Apply(NativeMctsAction action)
    {
        ThrowIfDisposed();
        ArgumentNullException.ThrowIfNull(action);
        if (pendingChoices != null)
        {
            if (!pendingChoices.TryGetValue(action.Key, out var selectedGroup))
                throw new InvalidOperationException($"Unknown prediction choice action {action.Key}.");
            var frame = CurrentChoiceFrame;
            var selected = frame.ResolveSelection(action).ToArray();
            completedSelections.Add(new CombatCompletedChoiceObservation(frame.Effect, selected));
            foreach (var group in pendingChoices.Values.Where(group => !ReferenceEquals(group, selectedGroup)))
                ReleaseBranches(group.Branches);
            pendingChoices = null;

            int nextIndex = selectedGroup.ChoiceIndex + 1;
            var withMoreChoices = selectedGroup.Branches
                .Where(branch => ChoiceCount(branch.Action) > nextIndex)
                .GroupBy(branch => driver.NativeMctsChoiceKey(
                    branch.Action, branch.Action, nextIndex), StringComparer.Ordinal)
                .ToDictionary(group => group.Key,
                    group => new PendingChoiceGroup(group.ToArray(), nextIndex),
                    StringComparer.Ordinal);
            if (withMoreChoices.Count > 0)
            {
                ReleaseBranches(selectedGroup.Branches
                    .Where(branch => ChoiceCount(branch.Action) <= nextIndex));
                pendingChoices = withMoreChoices;
                if (!choiceFramesAfterPrefix.TryGetValue(action.Key, out var nextFrame))
                    throw new PredictionUnsupportedException(
                        $"Nested choice {action.Key} has no captured current-layer frame.");
                pendingChoiceFrame = nextFrame with { CompletedSelections = completedSelections.ToArray() };
                currentDescription = BuildPendingDescription();
                return currentDescription;
            }

            PendingChoiceBranch final = selectedGroup.Branches
                .Single(branch => ChoiceCount(branch.Action) == nextIndex);
            ReleaseBranches(selectedGroup.Branches.Where(branch => !ReferenceEquals(branch, final)));
            current = final.Snapshot;
            pendingChoiceFrame = null;
            choiceFramesAfterPrefix = new Dictionary<string, NativeMctsChoiceFrame>();
            completedSelections.Clear();
            transient.Add(current);
            currentDescription = driver.NativeMctsDescribe(current, actionCount);
            return currentDescription;
        }

        var expansion = driver.NativeMctsExpand(current, action, actionCount);
        LastProbeBoundary = expansion.ProbeBoundary;
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
            .GroupBy(branch => driver.NativeMctsChoiceKey(
                expansion.BaseAction, branch.Action, 0), StringComparer.Ordinal)
            .ToDictionary(group => group.Key,
                group => new PendingChoiceGroup(group.ToArray(), 0),
                StringComparer.Ordinal);
        pendingChoiceFrame = expansion.FirstChoiceFrame;
        if (pendingChoiceFrame is null)
            throw new PredictionUnsupportedException("Choice expansion has no captured current-layer frame.");
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
            return CurrentChoiceFrame.ToPolicyObservation();
        return driver.NativeMctsObserve(current);
    }

    public NativeMctsChoiceFrame CurrentChoiceFrame
    {
        get
        {
            if (pendingChoices == null || pendingChoiceFrame == null)
                throw new PredictionUnsupportedException(
                    "Choice layer has no captured pre-selection context.");
            pendingChoiceFrame.ValidateFrame();
            if (!CompletedSelectionsEqual(pendingChoiceFrame.CompletedSelections, completedSelections))
                throw new PredictionUnsupportedException(
                    "Choice frame completed prefix does not match the current predicted layer.");
            return pendingChoiceFrame;
        }
    }

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
            return driver.NativeMctsHash(text);
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
            driver.NativeMctsPendingStateKey(current.StateKey, actions),
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

    private static bool CompletedSelectionsEqual(
        IReadOnlyList<CombatCompletedChoiceObservation> expected,
        IReadOnlyList<CombatCompletedChoiceObservation> actual)
        => expected.Count == actual.Count
            && expected.Zip(actual).All(pair =>
                string.Equals(pair.First.Effect, pair.Second.Effect, StringComparison.Ordinal)
                && pair.First.CombatCardIndices.SequenceEqual(pair.Second.CombatCardIndices));

    private static void ReleaseBranches(IEnumerable<PendingChoiceBranch> branches)
    {
        var unique = new HashSet<SimulationSnapshot>(
            branches.Select(branch => branch.Snapshot), ReferenceEqualityComparer.Instance);
        foreach (SimulationSnapshot snapshot in unique)
            snapshot.ReleaseSimulator();
    }

    private void ThrowIfDisposed() => ObjectDisposedException.ThrowIf(disposed, this);

}

public static class NativeMctsSimulationApi
{
    private static int initialized;

    public static void Initialize()
    {
        if (Interlocked.Exchange(ref initialized, 1) != 0) return;
        Entry.InitializeSimulationRuntime();
    }

    public static NativeMctsSimulationSession Capture(
        CombatState state, NativeMctsTrajectoryRewardSeed rewardSeed)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(rewardSeed);
        Initialize();
        return new NativeMctsSimulationSession(CombatRootSnapshot.Capture(state), rewardSeed);
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
