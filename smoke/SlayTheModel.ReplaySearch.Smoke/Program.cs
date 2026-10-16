using SlayTheModel.Search;

var environment = new ReplayToy();
var tree = new ReplayMcts<int>(environment);
// Leave enough room for first-run JIT on slower or heavily loaded machines.
// The environment itself is deterministic; this is not a throughput benchmark.
var budget = TimeSpan.FromMilliseconds(250);
var first = await tree.SearchAsync([], "0", budget, budget);
if (first.CompletedSimulations == 0 || !first.Rebuilt || first.Action != 1)
    throw new Exception("Expected completed search choosing the high-value branch.");
tree.Advance(first.Action);
var second = await tree.SearchAsync([1], "1", budget, budget);
if (second.Rebuilt || second.RetainedVisits == 0 || second.Action != 1)
    throw new Exception("Expected subtree statistics to survive root advancement.");
tree.Reset();
try
{
    await tree.SearchAsync([], "wrong", budget, budget);
    throw new Exception("A mismatched reconstruction must fail.");
}
catch (InvalidDataException) { }
using var cancelled = new CancellationTokenSource();
cancelled.Cancel();
try
{
    await tree.SearchAsync([], "0", budget, budget, cancelled.Token);
    throw new Exception("Caller cancellation must propagate.");
}
catch (OperationCanceledException) { }
environment.Stall = true;
tree.Reset();
try
{
    await tree.SearchAsync([], "0", budget, budget);
    throw new Exception("An interrupted rollout must not become a usable action.");
}
catch (TimeoutException) { }
foreach (var dead in new[] { false, true })
{
    var result = await new ReplayMcts<int>(new ProgressToy(dead)).SearchAsync([], "root", budget, budget, maxDepth: 1);
    if (dead && result.Statistics.Any(stat => stat.MeanValue != -1))
        throw new Exception("Death must be -1 regardless of damage.");
    if (!dead && result.Action != 1) throw new Exception("Cutoff must reward effective damage.");
}
static void Equal(double actual, double expected)
{
    if (Math.Abs(actual - expected) > 1e-9) throw new Exception($"Reward {actual} != {expected}");
}
Equal(CombatRolloutReward.Evaluate(true, false, 50, 100, 80, 1, 0), 0.95);
Equal(CombatRolloutReward.Evaluate(true, false, 100, 100, 80, 1, 0), 1);
Equal(CombatRolloutReward.Evaluate(false, true, 0, 100, 80, 1, 100), -1);
Equal(CombatRolloutReward.Evaluate(false, false, 80, 100, 80, 0, 0), -0.1);
Equal(CombatRolloutReward.Evaluate(false, false, 40, 100, 80, 0.5, 20), 0.35 - 0.275 - 0.0625 - 0.0625);
Equal(CombatRolloutReward.Evaluate(false, false, 100, 100, 80, 0.5, 0), 0.4875);
Equal(CombatRolloutReward.Evaluate(false, false, 160, 200, 80, 0.5, 0), 0.625);
Equal(CombatRolloutReward.Evaluate(false, false, 160, 200, 80, 1, 0), 0.8);
Equal(CombatRolloutReward.Evaluate(false, false, 1, 100, 80, 0, 1000), -0.8);
Equal(CombatRolloutReward.Evaluate(false, false, 1, 100, 0, 0, 0), 0.175);
var safer = await new ReplayMcts<int>(new HealthTradeoffToy()).SearchAsync([], "root", budget, budget, maxDepth: 1);
if (safer.Action != 1) throw new Exception("Cutoff must prefer lower player loss.");
var risk = await new ReplayMcts<int>(new RiskToy()).SearchAsync([], "root", budget, budget, maxDepth: 1);
if (risk.Action != 1) throw new Exception("Equal damage/HP must prefer lower imminent risk.");
var timed = await new ReplayMcts<int>(new AtomicTimeoutToy()).SearchAsync([], "root", budget, budget);
Equal(timed.Statistics.Single().MeanValue, 0.35);
if (timed.CompletedSimulations != 1) throw new Exception("Atomic completed timeout must be scored once.");
environment.Stall = false;
var contextTree = new ReplayMcts<int>(environment);
await contextTree.SearchAsync([], "0", budget, budget);
environment.RewardContextKey = "new-start-hp";
var changed = await contextTree.SearchAsync([], "0", budget, budget);
if (!changed.Rebuilt || changed.RetainedVisits != 0) throw new Exception("Changed HP baseline must invalidate old reward statistics.");
Console.WriteLine("replay search: formula, death, healing, clamps, risk, timeout, cancellation, context invalidation and reuse passed");
sealed class HealthTradeoffToy : IReplayEnvironment<int>
{
    private int action = -1;
    public bool Terminal => false;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation) { action = -1; return Task.CompletedTask; }
    public Task ApplyAsync(int value, CancellationToken cancellation) { action = value; return Task.CompletedTask; }
    public IReadOnlyList<int> LegalActions() => [0, 1];
    public string StateKey() => action < 0 ? "root" : action.ToString();
    public double EvaluateTerminal() => throw new InvalidOperationException("This fixture only exercises cutoff evaluation.");
    public double EvaluateCutoff() => CombatRolloutReward.Evaluate(false, false, action == 0 ? 40 : 80, 80, 80, action == 0 ? 0.5 : 0.4, 0);
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => actions[0];
}

sealed class ProgressToy(bool dead) : IReplayEnvironment<int>
{
    private int _action = -1;
    public bool Terminal => dead && _action >= 0;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation) { _action = -1; return Task.CompletedTask; }
    public Task ApplyAsync(int action, CancellationToken cancellation) { _action = action; return Task.CompletedTask; }
    public IReadOnlyList<int> LegalActions() => [0, 1];
    public string StateKey() => _action < 0 ? "root" : _action.ToString();
    public double EvaluateTerminal() => CombatRolloutReward.Evaluate(false, dead, dead ? 0 : 30, 80, 80, _action == 1 ? 0.9 : 0.1, 0);
    public double EvaluateCutoff() => EvaluateTerminal();
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => actions[0];
}

sealed class ReplayToy : IReplayEnvironment<int>
{
    private int _state;
    public bool Stall;
    public string RewardContextKey { get; set; } = "";
    public bool Terminal => _state >= 2;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        _state = prefix.Sum();
        return Task.CompletedTask;
    }
    public async Task ApplyAsync(int action, CancellationToken cancellation)
    {
        if (Stall) await Task.Delay(Timeout.Infinite, cancellation);
        _state = action == 0 ? 3 : _state + 1;
    }
    public IReadOnlyList<int> LegalActions() => Terminal ? [] : [0, 1];
    public string StateKey() => _state.ToString();
    public double EvaluateTerminal() => _state == 2 ? 1 : -1;
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => 1;
}

sealed class AtomicTimeoutToy : IReplayEnvironment<int>
{
    private bool moved;
    public bool Terminal => false;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation) { moved = false; return Task.CompletedTask; }
    public async Task ApplyAsync(int action, CancellationToken cancellation)
    {
        // An atomic transition completes after the deadline; it is safe to evaluate.
        await Task.Delay(350);
        moved = true;
    }
    public IReadOnlyList<int> LegalActions() => [0];
    public string StateKey() => moved ? "after" : "root";
    public double EvaluateTerminal() => throw new InvalidOperationException();
    public double EvaluateCutoff() => CombatRolloutReward.Evaluate(false, false, 80, 80, 80, 0.5, 0);
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => 0;
}

sealed class RiskToy : IReplayEnvironment<int>
{
    private int action = -1;
    public bool Terminal => false;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation) { action = -1; return Task.CompletedTask; }
    public Task ApplyAsync(int value, CancellationToken cancellation) { action = value; return Task.CompletedTask; }
    public IReadOnlyList<int> LegalActions() => [0, 1];
    public string StateKey() => action < 0 ? "root" : action.ToString();
    public double EvaluateTerminal() => throw new InvalidOperationException();
    public double EvaluateCutoff() => CombatRolloutReward.Evaluate(false, false, 40, 80, 40, 0.5, action == 0 ? 40 : 0);
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => 0;
}
