using SlayTheModel.Search;

sealed class Fixture : IPolicyValueReplayEnvironment<string, string>
{
    private readonly Dictionary<string, string[]> actions = new()
    {
        ["root"] = ["a", "b", "c"],
        ["a"] = ["terminal"], ["b"] = ["terminal"], ["c"] = ["terminal"],
    };
    private readonly Dictionary<string, double> values;
    public string State { get; private set; } = "root";
    public Fixture(Dictionary<string, double> values) => this.values = values;
    public Task RestoreAsync(IReadOnlyList<string> prefix, CancellationToken cancellation)
    {
        State = "root";
        foreach (var action in prefix) Apply(action);
        return Task.CompletedTask;
    }
    public Task ApplyAsync(string action, CancellationToken cancellation) { Apply(action); return Task.CompletedTask; }
    private void Apply(string action) => State = action == "terminal" ? "terminal" : action;
    public IReadOnlyList<string> LegalActions() => State == "terminal" ? [] : actions[State];
    public string StateKey() => State;
    public bool Terminal => State == "terminal";
    public double EvaluateTerminal() => values.GetValueOrDefault(State, 0);
    public double EvaluateUnresolved() => 0;
    public string RolloutAction(IReadOnlyList<string> legal, Random random) => legal[0];
    public string PolicyObservation() => State;
}

static class Program
{
    private static PolicyValuePrediction Prediction(string state, IReadOnlyList<string> legal,
        double[] rootLogits, Dictionary<string, double> childValues)
        => state == "root"
            ? new PolicyValuePrediction(rootLogits, 0)
            : new PolicyValuePrediction(new double[legal.Count], childValues.GetValueOrDefault(state));

    private static async Task<IReadOnlyList<RootActionStatistics<string>>> SearchAsync(
        double[] logits, Dictionary<string, double> values)
    {
        using var cts = new CancellationTokenSource();
        var fixture = new Fixture(values);
        var tree = new PolicyValueMcts<string, string>(fixture,
            (state, legal) => Prediction(state, legal, logits, values), seed: 7);
        var result = await tree.SearchAsync([], "root", TimeSpan.FromMilliseconds(100),
            TimeSpan.FromMilliseconds(100), cts.Token);
        if (result.NetworkPriorCalls <= 0 || result.NetworkValueCalls <= 0 || result.NetworkFallbacks != 0)
            throw new InvalidOperationException("Network outputs were not used in the tree.");
        return result.Statistics;
    }

    private static async Task CheckSimulationCapAsync()
    {
        var fixture = new Fixture(new() { ["a"] = 0, ["b"] = 0, ["c"] = 0 });
        var policy = new PolicyValueMcts<string, string>(fixture,
            (state, legal) => Prediction(state, legal, [0, 0, 0], new() { ["a"] = 0, ["b"] = 0, ["c"] = 0 }), seed: 3);
        var policyResult = await policy.SearchAsync([], "root", TimeSpan.FromSeconds(1),
            TimeSpan.FromSeconds(1), maxSimulations: 7);
        if (policyResult.CompletedSimulations != 7)
            throw new InvalidOperationException($"Policy/value simulation cap was not exact: {policyResult.CompletedSimulations}");

        var pure = new ReplayMcts<string>(fixture, seed: 3);
        var pureResult = await pure.SearchAsync([], "root", TimeSpan.FromSeconds(1),
            TimeSpan.FromSeconds(1), maxSimulations: 7);
        if (pureResult.CompletedSimulations != 7)
            throw new InvalidOperationException($"Pure MCTS simulation cap was not exact: {pureResult.CompletedSimulations}");
    }

    public static async Task Main()
    {
        await CheckSimulationCapAsync();
        var prior = await SearchAsync([8, 0, 0], new() { ["a"] = 0, ["b"] = 0, ["c"] = 0 });
        var flat = await SearchAsync([0, 0, 0], new() { ["a"] = 0, ["b"] = 0, ["c"] = 0 });
        if (prior.Single(x => x.Action == "a").Visits <= prior.Single(x => x.Action == "b").Visits)
            throw new InvalidOperationException("Prior did not change root visit allocation.");
        if (prior.Select(x => x.Visits).SequenceEqual(flat.Select(x => x.Visits)))
            throw new InvalidOperationException("Prior produced the same visit allocation as flat policy.");

        var valueA = await SearchAsync([0, 0, 0], new() { ["a"] = 1, ["b"] = -1, ["c"] = -1 });
        if (valueA.Single(x => x.Action == "a").MeanValue <= valueA.Single(x => x.Action == "b").MeanValue)
            throw new InvalidOperationException("Leaf value did not affect backup means.");
        Console.WriteLine($"POLICY_VALUE_TREE_CHECK priorA={prior.Single(x => x.Action == "a").Visits} priorB={prior.Single(x => x.Action == "b").Visits} valueMeanA={valueA.Single(x => x.Action == "a").MeanValue:F3} valueMeanB={valueA.Single(x => x.Action == "b").MeanValue:F3}");
    }
}
