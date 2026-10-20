namespace SlayTheModel.Search;

public sealed record RootActionStatistics<TAction>(
    TAction Action,
    int Visits,
    double MeanValue,
    double BestValue)
    where TAction : notnull;

public sealed record MctsResult<TAction>(
    TAction BestAction,
    int Simulations,
    long StateTransitions,
    IReadOnlyList<RootActionStatistics<TAction>> RootActions)
    where TAction : notnull;
