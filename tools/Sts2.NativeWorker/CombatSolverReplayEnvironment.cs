using CombatSolver.Api;
using SlayTheModel.Search;

public sealed record CombatSolverMctsAction(NativeMctsAction Native)
{
    public string Key => Native.Key;
}

public sealed class CombatSolverReplayEnvironment : IReplayEnvironment<CombatSolverMctsAction>, IDisposable
{
    private NativeMctsSimulationSession? session;
    private int entryHp;
    private NativeMctsState state = null!;
    private string rootKey = "";
    private string rootActions = "";
    private readonly List<CombatSolverMctsAction> promotedPrefix = [];
    private long transitions;

    public void Capture(MegaCrit.Sts2.Core.Combat.CombatState combat, int capturedEntryHp)
    {
        session?.Dispose();
        entryHp = capturedEntryHp;
        session = NativeMctsSimulationApi.Capture(combat);
        state = session.RestoreRoot();
        rootKey = state.Key;
        rootActions = string.Join(" | ", state.LegalActions.Select(action => action.Key));
        promotedPrefix.Clear();
    }

    public string RootKey => rootKey;
    public bool Terminal => state.Terminal;
    public long Transitions => transitions;
    public string CurrentContinuationKey
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured.")).ContinuationKey;
    public string CurrentContinuationStateText
        => (session ?? throw new InvalidOperationException("Combat Solver root has not been captured.")).ContinuationStateText;
    public string ChoiceSignature => PendingChoiceSignature();
    public string ChoiceDiagnostics
        => session == null || session.ChoiceDiagnostics.Count == 0
            ? "<none>"
            : string.Join(" | ", session.ChoiceDiagnostics);

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
        cancellation.ThrowIfCancellationRequested();
        var active = session ?? throw new InvalidOperationException("Combat Solver root has not been captured.");
        state = active.RestoreRoot();
        foreach (var action in promotedPrefix)
        {
            cancellation.ThrowIfCancellationRequested();
            state = active.Apply(action.Native);
        }
        foreach (var action in prefix)
        {
            cancellation.ThrowIfCancellationRequested();
            state = active.Apply(action.Native);
        }
        if (prefix.Count == 0 && promotedPrefix.Count == 0 && rootKey.Length > 0 && state.Key != rootKey)
            throw new InvalidDataException($"Combat Solver root action set changed. expected={rootKey} actual={state.Key} expectedActions={rootActions} actualActions={string.Join(" | ", state.LegalActions.Select(action => action.Key))}");
        return Task.CompletedTask;
    }

    public Task ApplyAsync(CombatSolverMctsAction action, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        state = (session ?? throw new InvalidOperationException("Combat Solver root has not been captured."))
            .Apply(action.Native);
        transitions++;
        return Task.CompletedTask;
    }

    public IReadOnlyList<CombatSolverMctsAction> LegalActions()
        => state.LegalActions.Select(static action => new CombatSolverMctsAction(action)).ToArray();

    public string StateKey() => state.Key;

    public double EvaluateTerminal()
        => state.Won ? 0.5 + Math.Atan((state.PlayerHp - entryHp) / 20.0) / Math.PI : -1;

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
}
