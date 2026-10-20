namespace SlayTheModel.Search;

/// <summary>
/// A mutable, cloneable, single-agent environment. Hidden information and RNG state
/// may be present in <typeparamref name="TState"/> for omniscient search.
/// </summary>
public interface IOmniscientEnvironment<TState, TAction>
    where TState : class
    where TAction : notnull
{
    TState Clone(TState state);

    IReadOnlyList<TAction> GetLegalActions(TState state);

    void ApplyAction(TState state, TAction action);

    bool IsTerminal(TState state);

    /// <summary>
    /// Returns utility from the fixed root player's perspective. Higher is always better.
    /// This is used for both terminal states and depth-limited leaves.
    /// </summary>
    double Evaluate(TState state);

    TAction SelectRolloutAction(
        TState state,
        IReadOnlyList<TAction> legalActions,
        Random random);
}
