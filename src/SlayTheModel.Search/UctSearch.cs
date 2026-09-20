namespace SlayTheModel.Search;

/// <summary>
/// Allocation-conscious reference UCT implementation for a deterministic,
/// full-information, single-agent environment.
/// </summary>
public sealed class UctSearch<TState, TAction>
    where TState : class
    where TAction : notnull
{
    private readonly IOmniscientEnvironment<TState, TAction> _environment;
    private readonly MctsOptions _options;
    private readonly Random _random;

    public UctSearch(
        IOmniscientEnvironment<TState, TAction> environment,
        MctsOptions? options = null)
    {
        _environment = environment ?? throw new ArgumentNullException(nameof(environment));
        _options = options ?? new MctsOptions();
        _options.Validate();
        _random = new Random(_options.RandomSeed);
    }

    public MctsResult<TAction> Search(TState rootState)
    {
        ArgumentNullException.ThrowIfNull(rootState);

        if (_environment.IsTerminal(rootState))
        {
            throw new ArgumentException("Cannot search a terminal state.", nameof(rootState));
        }

        var rootActions = SnapshotActions(rootState);
        if (rootActions.Count == 0)
        {
            throw new InvalidOperationException("Non-terminal root state has no legal actions.");
        }

        var root = new Node(parent: null, hasAction: false, action: default!, rootActions);
        long stateTransitions = 0;

        for (var simulation = 0; simulation < _options.Simulations; simulation++)
        {
            var state = _environment.Clone(rootState);
            var node = root;
            var path = new List<Node>(capacity: 32) { root };
            var depth = 0;

            while (!_environment.IsTerminal(state) && depth < _options.MaxRolloutDepth)
            {
                if (node.UnexpandedActions.Count > 0)
                {
                    var action = RemoveRandomUnexpandedAction(node);
                    _environment.ApplyAction(state, action);
                    stateTransitions++;
                    depth++;

                    var childActions = _environment.IsTerminal(state)
                        ? Array.Empty<TAction>()
                        : SnapshotActions(state);

                    var child = new Node(node, hasAction: true, action, childActions);
                    node.Children.Add(child);
                    node = child;
                    path.Add(node);
                    break;
                }

                if (node.Children.Count == 0)
                {
                    break;
                }

                node = SelectChild(node);
                _environment.ApplyAction(state, node.ActionFromParent);
                stateTransitions++;
                depth++;
                path.Add(node);
            }

            while (!_environment.IsTerminal(state) && depth < _options.MaxRolloutDepth)
            {
                var legalActions = _environment.GetLegalActions(state);
                if (legalActions.Count == 0)
                {
                    break;
                }

                var action = _environment.SelectRolloutAction(state, legalActions, _random);
                _environment.ApplyAction(state, action);
                stateTransitions++;
                depth++;
            }

            var value = _environment.Evaluate(state);
            if (!double.IsFinite(value))
            {
                throw new InvalidOperationException("Environment returned a non-finite evaluation.");
            }

            foreach (var visited in path)
            {
                visited.Visits++;
                visited.ValueSum += value;
                visited.BestValue = Math.Max(visited.BestValue, value);
            }
        }

        var orderedRootChildren = root.Children
            .OrderByDescending(child => child.Visits)
            .ThenByDescending(child => child.MeanValue)
            .ToArray();

        if (orderedRootChildren.Length == 0)
        {
            throw new InvalidOperationException("Search did not expand any root action.");
        }

        var statistics = orderedRootChildren
            .Select(child => new RootActionStatistics<TAction>(
                child.ActionFromParent,
                child.Visits,
                child.MeanValue,
                child.BestValue))
            .ToArray();

        return new MctsResult<TAction>(
            orderedRootChildren[0].ActionFromParent,
            _options.Simulations,
            stateTransitions,
            statistics);
    }

    private IReadOnlyList<TAction> SnapshotActions(TState state)
    {
        var actions = _environment.GetLegalActions(state);
        return actions.Count == 0 ? Array.Empty<TAction>() : actions.ToArray();
    }

    private TAction RemoveRandomUnexpandedAction(Node node)
    {
        var index = _random.Next(node.UnexpandedActions.Count);
        var action = node.UnexpandedActions[index];
        var lastIndex = node.UnexpandedActions.Count - 1;
        node.UnexpandedActions[index] = node.UnexpandedActions[lastIndex];
        node.UnexpandedActions.RemoveAt(lastIndex);
        return action;
    }

    private Node SelectChild(Node parent)
    {
        Node? best = null;
        var bestScore = double.NegativeInfinity;
        var logParentVisits = Math.Log(Math.Max(1, parent.Visits));

        foreach (var child in parent.Children)
        {
            var score = child.Visits == 0
                ? double.PositiveInfinity
                : child.MeanValue + _options.ExplorationConstant
                    * Math.Sqrt(logParentVisits / child.Visits);

            if (score > bestScore)
            {
                bestScore = score;
                best = child;
            }
        }

        return best ?? throw new InvalidOperationException("Expanded node has no children.");
    }

    private sealed class Node
    {
        public Node(
            Node? parent,
            bool hasAction,
            TAction action,
            IReadOnlyList<TAction> unexpandedActions)
        {
            Parent = parent;
            HasAction = hasAction;
            ActionFromParent = action;
            UnexpandedActions = new List<TAction>(unexpandedActions);
        }

        public Node? Parent { get; }

        public bool HasAction { get; }

        public TAction ActionFromParent { get; }

        public List<TAction> UnexpandedActions { get; }

        public List<Node> Children { get; } = [];

        public int Visits { get; set; }

        public double ValueSum { get; set; }

        public double BestValue { get; set; } = double.NegativeInfinity;

        public double MeanValue => Visits == 0 ? 0 : ValueSum / Visits;
    }
}
