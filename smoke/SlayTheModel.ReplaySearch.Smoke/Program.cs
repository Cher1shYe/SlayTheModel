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
    var progress = new ProgressToy(dead);
    var result = await new ReplayMcts<int>(progress).SearchAsync([], "root", budget, budget, maxDepth: 1);
    if (result.Action != 1 || result.Statistics.Single(stat => stat.Action == 1).MeanValue
        <= result.Statistics.Single(stat => stat.Action == 0).MeanValue)
        throw new Exception("Enemy damage must distinguish both failed and depth-limited rollouts.");
}
var bestFailure = CombatRolloutReward.Evaluate(false, true, 0, 80, 1);
var untouchedCutoff = CombatRolloutReward.Evaluate(false, false, 1, 80, 0);
var bestCutoff = CombatRolloutReward.Evaluate(false, false, 80, 80, 1);
var costlyWin = CombatRolloutReward.Evaluate(true, false, 1, 80, 0);
if (!(bestFailure < untouchedCutoff && bestCutoff < costlyWin))
    throw new Exception("Progress must not outrank survival or a genuine victory.");
if (CombatRolloutReward.Evaluate(false, false, 50, 80, 0.2)
    >= CombatRolloutReward.Evaluate(false, false, 50, 80, 0.8))
    throw new Exception("Healing away enemy damage must reduce progress reward.");
Console.WriteLine("replay search: preference, reuse, mismatch, cancellation, interrupted rollout, damage-shaped failure/cutoff and victory ordering passed");

sealed class ProgressToy(bool dead) : IReplayEnvironment<int>
{
    private int _action = -1;
    public bool Terminal => dead && _action >= 0;
    public Task RestoreAsync(IReadOnlyList<int> prefix, CancellationToken cancellation) { _action = -1; return Task.CompletedTask; }
    public Task ApplyAsync(int action, CancellationToken cancellation) { _action = action; return Task.CompletedTask; }
    public IReadOnlyList<int> LegalActions() => [0, 1];
    public string StateKey() => _action < 0 ? "root" : _action.ToString();
    public double EvaluateTerminal() => CombatRolloutReward.Evaluate(false, dead, dead ? 0 : 30, 80, _action == 1 ? 0.9 : 0.1);
    public double EvaluateCutoff() => EvaluateTerminal();
    public int RolloutAction(IReadOnlyList<int> actions, Random random) => actions[0];
}

sealed class ReplayToy : IReplayEnvironment<int>
{
    private int _state;
    public bool Stall;
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
