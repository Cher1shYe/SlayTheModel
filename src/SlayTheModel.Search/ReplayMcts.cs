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
    double EvaluateTerminal();
    TAction RolloutAction(IReadOnlyList<TAction> actions, Random random);
}

public sealed record TimedSearchResult<TAction>(TAction Action, int CompletedSimulations,
    int RetainedVisits, double ElapsedMilliseconds, bool Rebuilt, IReadOnlyList<RootActionStatistics<TAction>> Statistics) where TAction : notnull;

public sealed class ReplayMcts<TAction>(IReplayEnvironment<TAction> environment, int seed = 1)
    where TAction : notnull
{
    private sealed class Node(string key, IReadOnlyList<TAction> actions)
    {
        public string Key { get; } = key;
        public List<TAction> Unexpanded { get; } = [.. actions];
        public Dictionary<TAction, Node> Children { get; } = [];
        public int Visits;
        public double Sum;
        public double Best = double.NegativeInfinity;
        public double Mean => Visits == 0 ? 0 : Sum / Visits;
    }

    private readonly Random _random = new(seed);
    private Node? _root;

    public void Advance(TAction action)
    {
        _root = _root != null && _root.Children.TryGetValue(action, out var child) ? child : null;
    }

    public void Reset() => _root = null;

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
                _root ??= new Node(expectedStateKey, environment.LegalActions());
                var node = _root;
                var path = new List<Node> { node };
                var depth = 0;
                while (!environment.Terminal && depth < maxDepth)
                {
                    deadline.Token.ThrowIfCancellationRequested();
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
                while (!environment.Terminal && depth++ < maxDepth)
                {
                    deadline.Token.ThrowIfCancellationRequested();
                    var actions = environment.LegalActions();
                    if (actions.Count == 0) throw new InvalidDataException("Rollout has no legal action.");
                    await environment.ApplyAsync(environment.RolloutAction(actions, _random), deadline.Token);
                }
                deadline.Token.ThrowIfCancellationRequested();
                // Depth-limited rollouts are unresolved, never a zero-loss victory.
                var value = environment.Terminal ? environment.EvaluateTerminal() : -0.5;
                if (!double.IsFinite(value) || value < -1 || value > 1)
                    throw new InvalidDataException("Expected a finite utility in [-1, 1].");
                foreach (var visited in path)
                {
                    visited.Visits++;
                    visited.Sum += value;
                    visited.Best = Math.Max(visited.Best, value);
                }
                completed++;
            }
        }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested && deadline.IsCancellationRequested) { }
        cancellation.ThrowIfCancellationRequested();
        var stats = _root?.Children.Where(pair => pair.Value.Visits > 0)
            .OrderByDescending(pair => pair.Value.Visits).ThenByDescending(pair => pair.Value.Mean)
            .Select(pair => new RootActionStatistics<TAction>(pair.Key, pair.Value.Visits, pair.Value.Mean, pair.Value.Best)).ToArray() ?? [];
        if (stats.Length == 0) throw new TimeoutException("No completed valid rollout within the search budget.");
        return new TimedSearchResult<TAction>(stats[0].Action, completed, retained, watch.Elapsed.TotalMilliseconds, rebuilt, stats);
    }
}
