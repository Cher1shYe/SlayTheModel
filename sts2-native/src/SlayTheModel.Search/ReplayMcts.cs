using System.Diagnostics;

namespace SlayTheModel.Search;

/// <summary>A persistent UCT tree for an isolated, replay-restored native environment.</summary>
public interface IReplayEnvironment<TAction> where TAction : notnull
{
    Task RestoreAsync(IReadOnlyList<TAction> prefix, CancellationToken cancellation);
    Task ApplyAsync(TAction action, CancellationToken cancellation);
    IReadOnlyList<TAction> LegalActions();
    string StateKey();
    bool Terminal { get; }
    void BeginRollout() { }
    string RewardContextKey => "";
    bool CanEvaluate => true;
    double EvaluateTerminal();
    double EvaluateCutoff() => -0.5;
    TAction RolloutAction(IReadOnlyList<TAction> actions, Random random);
}

public sealed record TimedSearchResult<TAction>(TAction Action, int CompletedSimulations,
    int RetainedVisits, double ElapsedMilliseconds, bool Rebuilt, IReadOnlyList<RootActionStatistics<TAction>> Statistics,
    IReadOnlyDictionary<TAction, double>? RootPriors = null) where TAction : notnull
{
    public int LeafBackups { get; init; }
    public int TerminalBackups { get; init; }
    public double MeanBackupDepth { get; init; }
}

public sealed class ReplayMcts<TAction>(IReplayEnvironment<TAction> environment, int seed = 1,
    Func<IReadOnlyList<TAction>, CancellationToken, Task<IReadOnlyList<double>>>? policyPrior = null,
    double cPuct = 1.5,
    Func<int, CancellationToken, Task<double>>? leafValue = null,
    Func<IReadOnlyList<TAction>, int, CancellationToken, Task<(IReadOnlyList<double> Priors, double Value)>>? policyValue = null)
    where TAction : notnull
{
    private sealed class Node(string key, IReadOnlyList<TAction> actions)
    {
        public string Key { get; } = key;
        public List<TAction> Unexpanded { get; } = [.. actions];
        public IReadOnlyList<TAction> Actions { get; } = actions;
        public Dictionary<TAction, double>? Priors;
        public Dictionary<TAction, Node> Children { get; } = [];
        public double? NetworkValue;
        public int Visits;
        public double Sum;
        public double Best = double.NegativeInfinity;
        public double Mean => Visits == 0 ? 0 : Sum / Visits;
    }

    private readonly Random _random = new(seed);
    private Node? _root;
    private string? _rewardContext;

    public void Advance(TAction action)
    {
        _root = _root != null && _root.Children.TryGetValue(action, out var child) ? child : null;
    }

    public void Reset() => _root = null;

    private async Task<Node> CreateNodeAsync(string key, IReadOnlyList<TAction> actions, CancellationToken cancellation, int depth = 0)
    {
        var node = new Node(key, actions);
        if ((policyPrior == null && policyValue == null) || actions.Count == 0) return node;
        if (!double.IsFinite(cPuct) || cPuct < 0) throw new ArgumentOutOfRangeException(nameof(cPuct));
        IReadOnlyList<double> values;
        if (policyValue != null)
        {
            var joint=await policyValue(actions, depth, cancellation);
            values=joint.Priors; node.NetworkValue=joint.Value;
            if (!double.IsFinite(joint.Value) || joint.Value < -1 || joint.Value > 1)
                throw new InvalidDataException("Invalid network leaf value");
        }
        else values = await policyPrior!(actions, cancellation);
        if (values.Count != actions.Count || values.Any(p => !double.IsFinite(p) || p < 0)
            || !double.IsFinite(values.Sum()) || values.Sum() <= 0)
            throw new InvalidDataException("Prior must provide one finite nonnegative probability per legal action.");
        var total = values.Sum();
        node.Priors = actions.Select((action, i) => (action, p: values[i] / total)).ToDictionary(x => x.action, x => x.p);
        return node;
    }

    public async Task<TimedSearchResult<TAction>> SearchAsync(IReadOnlyList<TAction> prefix,
        string expectedStateKey, TimeSpan initialBudget, TimeSpan continuationBudget,
        CancellationToken cancellation = default, int maxDepth = 200)
    {
        if (initialBudget <= TimeSpan.Zero || continuationBudget <= TimeSpan.Zero || maxDepth <= 0)
            throw new ArgumentOutOfRangeException(nameof(initialBudget));
        var rebuilt = _root?.Key != expectedStateKey;
        if (rebuilt) _root = null;
        var watch = Stopwatch.StartNew();
        var budget = rebuilt ? initialBudget : continuationBudget;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        deadline.CancelAfter(budget);
        var completed = 0;
        int leafBackups=0, terminalBackups=0; long totalDepth=0;
        var retained = _root?.Visits ?? 0;
        try
        {
            while (watch.Elapsed < budget)
            {
                deadline.Token.ThrowIfCancellationRequested();
                await environment.RestoreAsync(prefix, deadline.Token);
                if (environment.StateKey() != expectedStateKey)
                    throw new InvalidDataException(
                        $"Native reconstruction differs from the requested root state. expected={expectedStateKey} actual={environment.StateKey()}");
                if (environment.Terminal) throw new InvalidOperationException("Cannot search a terminal state.");
                environment.BeginRollout();
                if (_rewardContext != environment.RewardContextKey)
                {
                    _root = null;
                    _rewardContext = environment.RewardContextKey;
                    rebuilt = true;
                    retained = 0;
                }
                _root ??= await CreateNodeAsync(expectedStateKey, environment.LegalActions(), deadline.Token);
                var node = _root;
                var path = new List<Node> { node };
                var depth = 0;
                while (!environment.Terminal && depth < maxDepth && !deadline.IsCancellationRequested)
                {
                    if (node.Priors is { } priors)
                    {
                        var selected = node.Actions.MaxBy(action =>
                        {
                            node.Children.TryGetValue(action, out var child);
                            return (child?.Mean ?? 0) + cPuct * priors[action]
                                * Math.Sqrt(1 + node.Visits) / (1 + (child?.Visits ?? 0));
                        })!;
                        await environment.ApplyAsync(selected, deadline.Token);
                        bool expanded = !node.Children.TryGetValue(selected, out var successor);
                        if (expanded)
                        {
                            successor = await CreateNodeAsync(environment.StateKey(),
                                environment.Terminal ? [] : environment.LegalActions(), deadline.Token, depth + 1);
                            node.Children.Add(selected, successor);
                        }
                        else if (environment.StateKey() != successor!.Key)
                            throw new InvalidDataException("A replayed PUCT edge diverged.");
                        node = successor!;
                        path.Add(node);
                        depth++;
                        if (expanded) break;
                        continue;
                    }
                    if (node.Unexpanded.Count > 0)
                    {
                        var index = _random.Next(node.Unexpanded.Count);
                        var action = node.Unexpanded[index];
                        await environment.ApplyAsync(action, deadline.Token);
                        // Commit expansion only after the native transition completes.
                        var child = new Node(environment.StateKey(), environment.Terminal ? [] : environment.LegalActions());
                        node.Children.Add(action, child);
                        node.Unexpanded.RemoveAt(index);
                        node = child;
                        path.Add(node);
                        depth++;
                        break;
                    }
                    if (node.Children.Count == 0) throw new InvalidDataException("Nonterminal state has no actions.");
                    var edge = node.Children.MaxBy(pair => pair.Value.Visits == 0 ? double.PositiveInfinity :
                        pair.Value.Mean + Math.Sqrt(2 * Math.Log(Math.Max(1, node.Visits)) / pair.Value.Visits));
                    await environment.ApplyAsync(edge.Key, deadline.Token);
                    node = edge.Value;
                    if (environment.StateKey() != node.Key) throw new InvalidDataException("A replayed tree edge diverged.");
                    path.Add(node);
                    depth++;
                }
                // Learned/mixed search evaluates the first completed expanded leaf.
                // Pending selectors are resolved by rollout before any value query.
                while (!environment.Terminal && depth < maxDepth && !deadline.IsCancellationRequested
                    && (policyValue == null && (leafValue == null || !environment.CanEvaluate)))
                {
                    var actions = environment.LegalActions();
                    if (actions.Count == 0) throw new InvalidDataException("Rollout has no legal action.");
                    await environment.ApplyAsync(environment.RolloutAction(actions, _random), deadline.Token);
                    depth++;
                }
                cancellation.ThrowIfCancellationRequested();
                // Score completed decision boundaries on time/depth cutoff. A cancelled
                // transition or suspended selection has no complete endpoint to score.
                if (depth == 0 || !environment.CanEvaluate) continue;
                var value = environment.Terminal ? environment.EvaluateTerminal()
                    : policyValue != null ? node.NetworkValue ?? throw new InvalidDataException("Missing expanded leaf value")
                    : leafValue == null ? environment.EvaluateCutoff()
                    : await leafValue(depth, deadline.Token);
                // Inference replies must be drained by the client, but an expired
                // request cannot contribute a partial simulation to visit targets.
                if (leafValue != null || policyValue != null) deadline.Token.ThrowIfCancellationRequested();
                if (!double.IsFinite(value) || value < -1 || value > 1)
                    throw new InvalidDataException("Expected a finite utility in [-1, 1].");
                foreach (var visited in path)
                {
                    visited.Visits++;
                    visited.Sum += value;
                    visited.Best = Math.Max(visited.Best, value);
                }
                completed++;
                if(environment.Terminal) terminalBackups++; else leafBackups++;
                totalDepth+=depth;
            }
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested && deadline.IsCancellationRequested) { }
        cancellation.ThrowIfCancellationRequested();
        var stats = _root?.Children.Where(pair => pair.Value.Visits > 0)
            .OrderByDescending(pair => pair.Value.Visits).ThenByDescending(pair => pair.Value.Mean)
            .Select(pair => new RootActionStatistics<TAction>(pair.Key, pair.Value.Visits, pair.Value.Mean, pair.Value.Best)).ToArray() ?? [];
        if (stats.Length == 0) throw new TimeoutException("No completed valid rollout within the search budget.");
        return new TimedSearchResult<TAction>(stats[0].Action, completed, retained, watch.Elapsed.TotalMilliseconds, rebuilt, stats, _root!.Priors)
        { LeafBackups=leafBackups, TerminalBackups=terminalBackups, MeanBackupDepth=(double)totalDepth/completed };
    }
}
