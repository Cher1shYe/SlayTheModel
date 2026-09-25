using CombatSolver.Api;
using System.Diagnostics;
using SlayTheModel.Search;
using SlayTheModel.Sts2.Protocol;

public sealed class MctsReplayEnvironmentDiagnostics
{
    public long RestoreCalls { get; internal set; }
    public long RestoreTicks { get; internal set; }
    public long RestoreRootTicks { get; internal set; }
    public long PrefixReplayTicks { get; internal set; }
    public long PrefixReplaySteps { get; internal set; }
    public long ApplyCalls { get; internal set; }
    public long ApplyTicks { get; internal set; }
    public long ObservationCalls { get; internal set; }
    public long ObservationTicks { get; internal set; }
    public double RestoreMs => Stopwatch.GetElapsedTime(0, RestoreTicks).TotalMilliseconds;
    public double RestoreRootMs => Stopwatch.GetElapsedTime(0, RestoreRootTicks).TotalMilliseconds;
    public double PrefixReplayMs => Stopwatch.GetElapsedTime(0, PrefixReplayTicks).TotalMilliseconds;
    public double ApplyMs => Stopwatch.GetElapsedTime(0, ApplyTicks).TotalMilliseconds;
    public double ObservationMs => Stopwatch.GetElapsedTime(0, ObservationTicks).TotalMilliseconds;
}

public sealed record CombatSolverMctsAction(NativeMctsAction Native)
{
    public string Key => Native.Key;
}

public sealed class CombatSolverReplayEnvironment : IPolicyValueReplayEnvironment<CombatSolverMctsAction, CombatObservation>, IDisposable
{
    private NativeMctsSimulationSession? session;
    private int entryHp;
    private NativeMctsTrajectoryRewardContext rewardContext = null!;
    private NativeMctsState state = null!;
    private string rootKey = "";
    private IReadOnlyList<CombatSolverMctsAction> rootActions = [];
    private readonly List<CombatSolverMctsAction> promotedPrefix = [];
    private long transitions;
    public MctsReplayEnvironmentDiagnostics? Diagnostics { get; set; }
    public IReadOnlyList<string> PromotedActionKeys => promotedPrefix.Select(action => action.Key).ToArray();

    public void Capture(MegaCrit.Sts2.Core.Combat.CombatState combat,
        NativeMctsTrajectoryRewardSeed rewardSeed)
    {
        session?.Dispose();
        session = NativeMctsSimulationApi.Capture(combat, rewardSeed);
        rewardContext = session.RewardContext;
        entryHp = rewardContext.EntryHp;
        state = session.RestoreRoot();
        rootKey = state.Key;
        rootActions = SnapshotActions(state.LegalActions);
        promotedPrefix.Clear();
        transitions = 0;
    }

    public string RootKey => rootKey;
    public int CapturedEntryHp => entryHp;
    public NativeMctsTrajectoryRewardContext RewardContext => rewardContext;
    public bool HasRewardContext => session != null;
    public bool Terminal => state.Terminal;
    public long Transitions => transitions;
    public string CurrentContinuationKey
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured.")).ContinuationKey;
    public string CurrentContinuationStateText
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured.")).ContinuationStateText;
    public string ChoiceDiagnostics
        => session == null || session.ChoiceDiagnostics.Count == 0
            ? "<none>"
            : string.Join(" | ", session.ChoiceDiagnostics);
    public NativeMctsState State => state;
    public NativeMctsProbeBoundaryDiagnostic? LastProbeBoundary
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .LastProbeBoundary;
    public NativeMctsProbeBoundaryDiagnostic CurrentBoundary
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .CurrentBoundary;
    public NativeMctsDriverDiagnostics NativeDiagnosticSnapshot
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .DiagnosticSnapshot;
    public CombatObservation ObserveCurrent()
    {
        long start = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
        try
        {
            return (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
                .ObserveCurrent();
        }
        finally
        {
            if (Diagnostics is { } diagnostic)
            {
                diagnostic.ObservationCalls++;
                diagnostic.ObservationTicks += Stopwatch.GetTimestamp() - start;
            }
        }
    }
    // This is the single policy-facing projection used by both tree expansion
    // and trajectory export. It intentionally delegates to the session's
    // frame-owned observation so a pending choice cannot fall back to its
    // pre-choice base observation.
    public CombatObservation PolicyObservation() => ObserveCurrent();
    public NativeMctsChoiceFrame CurrentChoiceFrame
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .CurrentChoiceFrame;
    public IReadOnlyList<CombatSolverMctsAction> RootActions
        => rootActions;
    public string ChoiceSignature => PendingChoiceSignature();

    public bool MatchesLiveRoot(MegaCrit.Sts2.Core.Combat.CombatState combat,
        bool livePendingChoice, string liveChoiceSignature = "")
    {
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        if (livePendingChoice)
            return state.PendingChoice && PendingChoiceSignature() == liveChoiceSignature;
        if (state.PendingChoice) return false;
        return CurrentContinuationKey == NativeMctsSimulationApi.CaptureLiveContinuationKey(combat);
    }

    private string PendingChoiceSignature()
        => state.PendingChoice
            ? $"{state.LegalActions.Min(action => action.SelectedCards?.Count ?? 0)}:"
                + $"{state.LegalActions.Max(action => action.SelectedCards?.Count ?? 0)}:"
                + string.Join(',', state.LegalActions
                    .SelectMany(action => action.SelectedCards ?? [])
                    .Select(card => card.CardId).Distinct().Order())
            : "";

    public void Promote(CombatSolverMctsAction action)
    {
        promotedPrefix.Add(action);
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        rootKey = state.Key;
        rootActions = SnapshotActions(state.LegalActions);
    }

    public (string StateKey, string ContinuationKey) PredictSuccessor(CombatSolverMctsAction action)
    {
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        ApplyAsync(action, CancellationToken.None).GetAwaiter().GetResult();
        var predicted = (state.Key, (session ?? throw new InvalidOperationException()).ContinuationKey);
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        return predicted;
    }

    public string PredictSuccessorStateText(CombatSolverMctsAction action)
    {
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        ApplyAsync(action, CancellationToken.None).GetAwaiter().GetResult();
        string text = CurrentContinuationStateText;
        RestoreAsync([], CancellationToken.None).GetAwaiter().GetResult();
        return text;
    }

    public Task RestoreAsync(IReadOnlyList<CombatSolverMctsAction> prefix, CancellationToken cancellation)
    {
        long restoreStart = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
        try
        {
        cancellation.ThrowIfCancellationRequested();
        var active = session ?? throw new InvalidOperationException("Combat Solver root has not been captured.");
        long rootStart = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
        state = active.RestoreRoot();
        if (Diagnostics is { } diagnosticRoot)
            diagnosticRoot.RestoreRootTicks += Stopwatch.GetTimestamp() - rootStart;
        foreach (var action in promotedPrefix)
        {
            cancellation.ThrowIfCancellationRequested();
            long prefixStart = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
            state = active.Apply(action.Native);
            if (Diagnostics is { } diagnosticPrefix)
            {
                diagnosticPrefix.PrefixReplaySteps++;
                diagnosticPrefix.PrefixReplayTicks += Stopwatch.GetTimestamp() - prefixStart;
            }
        }
        foreach (var action in prefix)
        {
            cancellation.ThrowIfCancellationRequested();
            long prefixStart = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
            state = active.Apply(action.Native);
            if (Diagnostics is { } diagnosticPrefix)
            {
                diagnosticPrefix.PrefixReplaySteps++;
                diagnosticPrefix.PrefixReplayTicks += Stopwatch.GetTimestamp() - prefixStart;
            }
        }
        if (prefix.Count == 0 && promotedPrefix.Count == 0 && rootKey.Length > 0 && state.Key != rootKey)
            throw new InvalidDataException($"Combat Solver root action set changed. expected={rootKey} actual={state.Key} expectedActions={string.Join(" | ", rootActions.Select(action => action.Key))} actualActions={string.Join(" | ", state.LegalActions.Select(action => action.Key))}");
        return Task.CompletedTask;
        }
        finally
        {
            if (Diagnostics is { } diagnostic)
            {
                diagnostic.RestoreCalls++;
                diagnostic.RestoreTicks += Stopwatch.GetTimestamp() - restoreStart;
            }
        }
    }

    public Task ApplyAsync(CombatSolverMctsAction action, CancellationToken cancellation)
    {
        long start = Diagnostics == null ? 0 : Stopwatch.GetTimestamp();
        try
        {
        cancellation.ThrowIfCancellationRequested();
        state = (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .Apply(action.Native);
        transitions++;
        return Task.CompletedTask;
        }
        finally
        {
            if (Diagnostics is { } diagnostic)
            {
                diagnostic.ApplyCalls++;
                diagnostic.ApplyTicks += Stopwatch.GetTimestamp() - start;
            }
        }
    }

    public IReadOnlyList<CombatSolverMctsAction> LegalActions()
        => state.LegalActions.Select(static action => new CombatSolverMctsAction(action)).ToArray();

    public string StateKey() => state.Key;

    public NativeMctsTerminalRewardInputs TerminalRewardInputs()
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .TerminalRewardInputs();

    public double EvaluateTerminal() => TerminalRewardInputs().Reward;

    public NativeMctsTerminalRewardInputs UnresolvedRewardInputs()
    {
        if (state.Terminal)
            throw new InvalidOperationException("Unresolved reward requires a nonterminal simulation state.");
        int totalEnemyHpLost = rewardContext.TotalEnemyHpLost(state.EnemyHpLost);
        double progress = Math.Clamp(totalEnemyHpLost
            / (double)Math.Max(rewardContext.InitialEnemyEffectiveHp, 1), 0.0, 1.0);
        double reward = NativeMctsReward.Score(false, false, rewardContext.EntryHp,
            state.PlayerHp, totalEnemyHpLost, rewardContext.InitialEnemyEffectiveHp);
        return new NativeMctsTerminalRewardInputs(
            rewardContext.TrajectoryId, rewardContext.CaptureId,
            rewardContext.CaptureBoundaryKey, "unresolved", rewardContext.EntryHp,
            state.PlayerHp, 0, 0, 0, 0, 0, state.PlayerHp, state.EnemyHpLost,
            state.EnemyHpTotal, rewardContext.InitialEnemyEffectiveHp,
            rewardContext.CapturedEnemyDamagePrefix, totalEnemyHpLost,
            progress, reward);
    }

    public double EvaluateUnresolved() => UnresolvedRewardInputs().Reward;

    private double EnemyDamageProgress => Math.Clamp(
        state.EnemyHpLost / (double)Math.Max(state.EnemyHpTotal, 1), 0.0, 1.0);

    public CombatSolverMctsAction RolloutAction(
        IReadOnlyList<CombatSolverMctsAction> actions,
        Random random)
        => random.Next(2) == 0 ? Heuristic(actions) : AttackFirst(actions);

    private CombatSolverMctsAction Heuristic(IReadOnlyList<CombatSolverMctsAction> actions)
    {
        if (state.PendingChoice) return actions[0];
        double Score(CombatSolverMctsAction action)
        {
            var value = action.Native;
            if (value.Kind == "EndTurn") return -1000;
            if (value.TargetHp is int hp && value.Damage >= hp) return 10000;
            if (value.GainsBlock && state.IncomingDamage > 0) return 1000;
            return value.CardType == "Attack" ? 100 + (double)value.Damage : value.GainsBlock ? -10 : 0;
        }
        return actions.OrderByDescending(Score).First();
    }

    private static CombatSolverMctsAction AttackFirst(IReadOnlyList<CombatSolverMctsAction> actions)
        => actions.OrderBy(action => action.Native.Kind == "EndTurn" ? 10
            : action.Native.CardType == "Attack" ? 0 : 1).First();

    public void Dispose() => session?.Dispose();

    private static IReadOnlyList<CombatSolverMctsAction> SnapshotActions(IReadOnlyList<NativeMctsAction> actions)
        => actions.Select(static action => new CombatSolverMctsAction(action)).ToArray();
}
