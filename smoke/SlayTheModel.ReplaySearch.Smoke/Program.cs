using SlayTheModel.Search;

var environment = new ReplayToy();
var tree = new ReplayMcts<int>(environment);
var budget = TimeSpan.FromMilliseconds(80);
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
Console.WriteLine("replay search: preference, reuse, mismatch, cancellation, interrupted rollout passed");

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
