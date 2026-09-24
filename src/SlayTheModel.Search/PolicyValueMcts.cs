using System.Diagnostics;

namespace SlayTheModel.Search;

public interface IPolicyValueReplayEnvironment<TAction, TObservation>
    : IReplayEnvironment<TAction>
    where TAction : notnull
{
    TObservation PolicyObservation();
}

public sealed record PolicyValuePrediction(IReadOnlyList<double> Logits, double Value);

public sealed record PolicyValueTimedSearchResult<TAction>(
    TAction Action,
    int CompletedSimulations,
    int RetainedVisits,
    double ElapsedMilliseconds,
    bool Rebuilt,
    IReadOnlyList<RootActionStatistics<TAction>> Statistics,
    int NetworkPriorCalls,
    int NetworkValueCalls,
    int NetworkFallbacks)
    where TAction : notnull;

/// <summary>
/// AlphaZero-style tree search. ReplayMcts remains the explicit pure-MCTS fallback.
/// Values use the single combat player's utility perspective and are not negated per ply.
/// </summary>
public sealed class PolicyValueMcts<TAction, TObservation>(
    IPolicyValueReplayEnvironment<TAction, TObservation> environment,
    Func<TObservation, IReadOnlyList<TAction>, PolicyValuePrediction> evaluator,
    int seed = 1,
    double exploration = 1.41421356237)
    where TAction : notnull
{
    private sealed class Edge(TAction action, double prior)
    {
        public TAction Action { get; } = action;
        public double Prior { get; } = prior;
        public Node? Child { get; set; }
        public int Visits { get; set; }
        public double Sum { get; set; }
        public double Best { get; set; } = double.NegativeInfinity;
        public double Mean => Visits == 0 ? 0 : Sum / Visits;
    }

    private sealed class Node(string key)
    {
        public string Key { get; } = key;
        public List<Edge> Edges { get; } = [];
        public int Visits { get; set; }
    }

    private readonly Random random = new(seed);
    private Node? root;

    public async Task<PolicyValueTimedSearchResult<TAction>> SearchAsync(
        IReadOnlyList<TAction> prefix,
        string expectedStateKey,
        TimeSpan initialBudget,
        TimeSpan continuationBudget,
        CancellationToken cancellation = default,
        int maxDepth = 200,
        int? maxSimulations = null)
    {
        if (initialBudget <= TimeSpan.Zero || continuationBudget <= TimeSpan.Zero || maxDepth <= 0
            || maxSimulations is <= 0)
            throw new ArgumentOutOfRangeException(nameof(initialBudget));
        bool rebuilt = root?.Key != expectedStateKey;
        if (rebuilt) root = null;
        await environment.RestoreAsync(prefix, cancellation);
        if (environment.StateKey() != expectedStateKey)
            throw new InvalidDataException($"Native reconstruction differs from requested root: expected={expectedStateKey} actual={environment.StateKey()}");
        root ??= new Node(expectedStateKey);
        var watch = Stopwatch.StartNew();
        var budget = rebuilt ? initialBudget : continuationBudget;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(budget);
        int completed = 0, priorCalls = 0, valueCalls = 0, fallbacks = 0;
        try
        {
            while (watch.Elapsed < budget && (!maxSimulations.HasValue || completed < maxSimulations.Value))
            {
                deadline.Token.ThrowIfCancellationRequested();
                await environment.RestoreAsync(prefix, deadline.Token);
                if (environment.StateKey() != expectedStateKey)
                    throw new InvalidDataException("Native reconstruction changed during policy/value search.");
                if (environment.Terminal) throw new InvalidOperationException("Cannot search a terminal state.");
                var node = root;
                var path = new List<(Node Node, Edge? Edge)> { (node, null) };
                int depth = 0;
                double value;
                while (true)
                {
                    deadline.Token.ThrowIfCancellationRequested();
                    if (environment.Terminal)
                    {
                        value = environment.EvaluateTerminal();
                        break;
                    }
                    if (depth >= maxDepth)
                    {
                        value = environment.EvaluateUnresolved();
                        break;
                    }
                    if (node.Edges.Count == 0)
                    {
                        var actions = environment.LegalActions();
                        if (actions.Count == 0) throw new InvalidDataException("Nonterminal policy node has no legal actions.");
                        var prediction = evaluator(environment.PolicyObservation(), actions);
                        ValidatePrediction(prediction, actions.Count);
                        priorCalls++;
                        valueCalls++;
                        var priors = Softmax(prediction.Logits);
                        node.Edges.AddRange(actions.Select((action, index) => new Edge(action, priors[index])));
                        value = prediction.Value;
                        break;
                    }
                    var edge = Select(node);
                    await environment.ApplyAsync(edge.Action, deadline.Token);
                    edge.Child ??= new Node(environment.StateKey());
                    if (environment.StateKey() != edge.Child.Key)
                        throw new InvalidDataException("A policy/value tree edge diverged after replay.");
                    node = edge.Child;
                    path.Add((node, edge));
                    depth++;
                }
                if (!double.IsFinite(value) || value < -1 || value > 1)
                    throw new InvalidDataException("Policy/value utility must be finite and in [-1, 1].");
                foreach (var (visitedNode, incoming) in path)
                {
                    visitedNode.Visits++;
                    if (incoming is not null)
                    {
                        incoming.Visits++;
                        incoming.Sum += value;
                        incoming.Best = Math.Max(incoming.Best, value);
                    }
                }
                completed++;
            }
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested && deadline.IsCancellationRequested) { }
        cancellation.ThrowIfCancellationRequested();
        var stats = root.Edges.Where(edge => edge.Visits > 0)
            .OrderByDescending(edge => edge.Visits)
            .ThenByDescending(edge => edge.Mean)
            .Select(edge => new RootActionStatistics<TAction>(edge.Action, edge.Visits, edge.Mean, edge.Best))
            .ToArray();
        if (stats.Length == 0) throw new TimeoutException("No completed policy/value rollout within the search budget.");
        return new PolicyValueTimedSearchResult<TAction>(stats[0].Action, completed, root.Visits,
            watch.Elapsed.TotalMilliseconds, rebuilt, stats, priorCalls, valueCalls, fallbacks);
    }

    private Edge Select(Node node)
    {
        double logVisits = Math.Log(Math.Max(1, node.Visits));
        return node.Edges.MaxBy(edge => edge.Visits == 0
            ? double.PositiveInfinity
            : edge.Mean + exploration * edge.Prior * Math.Sqrt(logVisits) / (1 + edge.Visits))!;
    }

    private static void ValidatePrediction(PolicyValuePrediction prediction, int actionCount)
    {
        if (prediction.Logits.Count != actionCount || prediction.Logits.Any(value => !double.IsFinite(value))
            || !double.IsFinite(prediction.Value) || prediction.Value < -1 || prediction.Value > 1)
            throw new InvalidDataException("Policy/value evaluator returned an invalid shape or utility.");
    }

    private static double[] Softmax(IReadOnlyList<double> logits)
    {
        double max = logits.Max();
        var exp = logits.Select(value => Math.Exp(Math.Clamp(value - max, -80, 80))).ToArray();
        double total = exp.Sum();
        if (!(total > 0) || !double.IsFinite(total)) throw new InvalidDataException("Policy prior normalization failed.");
        return exp.Select(value => value / total).ToArray();
    }
}
