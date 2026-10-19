using System.Diagnostics;
using SlayTheModel.Search;

// Per-search wall-time attribution; no changes to actions, state, or budgets.
internal sealed class ReplayTimingEnvironment(CombatSolverReplayEnvironment inner)
    : IReplayEnvironment<CombatSolverMctsAction>
{
    public double RestoreMs { get; private set; }
    public double ApplyMs { get; private set; }
    public int Restores { get; private set; }
    public int Applies { get; private set; }
    public async Task RestoreAsync(IReadOnlyList<CombatSolverMctsAction> prefix, CancellationToken ct)
    {
        long start=Stopwatch.GetTimestamp();
        try { await inner.RestoreAsync(prefix,ct); }
        finally { RestoreMs+=Stopwatch.GetElapsedTime(start).TotalMilliseconds; Restores++; }
    }
    public async Task ApplyAsync(CombatSolverMctsAction action, CancellationToken ct)
    {
        long start=Stopwatch.GetTimestamp();
        try { await inner.ApplyAsync(action,ct); }
        finally { ApplyMs+=Stopwatch.GetElapsedTime(start).TotalMilliseconds; Applies++; }
    }
    public IReadOnlyList<CombatSolverMctsAction> LegalActions()=>inner.LegalActions();
    public string StateKey()=>inner.StateKey();
    public bool Terminal=>inner.Terminal;
    public bool CanEvaluate=>inner.CanEvaluate;
    public string RewardContextKey=>inner.RewardContextKey;
    public void BeginRollout()=>inner.BeginRollout();
    public double EvaluateTerminal()=>inner.EvaluateTerminal();
    public double EvaluateCutoff()=>inner.EvaluateCutoff();
    public CombatSolverMctsAction RolloutAction(IReadOnlyList<CombatSolverMctsAction> actions,Random random)
        =>inner.RolloutAction(actions,random);
}
