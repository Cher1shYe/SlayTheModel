using SlayTheModel.Search;

var environment = new ToyOracleEnvironment();
var search = new UctSearch<ToyState, ToyAction>(
    environment,
    new MctsOptions
    {
        Simulations = 2_000,
        MaxRolloutDepth = 8,
        RandomSeed = 7,
    });

var result = search.Search(new ToyState());

if (result.BestAction != ToyAction.Invest)
{
    throw new InvalidOperationException(
        $"Expected omniscient search to choose {ToyAction.Invest}, got {result.BestAction}.");
}

Console.WriteLine($"best={result.BestAction}");
Console.WriteLine($"simulations={result.Simulations}");
Console.WriteLine($"transitions={result.StateTransitions}");

foreach (var action in result.RootActions)
{
    Console.WriteLine(
        $"action={action.Action} visits={action.Visits} mean={action.MeanValue:F4} best={action.BestValue:F4}");
}

internal enum ToyAction
{
    CashOut,
    Invest,
    OpenKnownGoodChest,
    OpenKnownBadChest,
}

internal sealed class ToyState
{
    public int Phase { get; set; }

    public double Reward { get; set; }
}

internal sealed class ToyOracleEnvironment : IOmniscientEnvironment<ToyState, ToyAction>
{
    private static readonly ToyAction[] RootActions = [ToyAction.CashOut, ToyAction.Invest];
    private static readonly ToyAction[] FutureActions =
        [ToyAction.OpenKnownGoodChest, ToyAction.OpenKnownBadChest];

    public ToyState Clone(ToyState state) => new() { Phase = state.Phase, Reward = state.Reward };

    public IReadOnlyList<ToyAction> GetLegalActions(ToyState state) => state.Phase switch
    {
        0 => RootActions,
        1 => FutureActions,
        _ => Array.Empty<ToyAction>(),
    };

    public void ApplyAction(ToyState state, ToyAction action)
    {
        switch (state.Phase, action)
        {
            case (0, ToyAction.CashOut):
                state.Reward = 1;
                state.Phase = 2;
                break;
            case (0, ToyAction.Invest):
                state.Phase = 1;
                break;
            case (1, ToyAction.OpenKnownGoodChest):
                state.Reward = 5;
                state.Phase = 2;
                break;
            case (1, ToyAction.OpenKnownBadChest):
                state.Reward = -3;
                state.Phase = 2;
                break;
            default:
                throw new InvalidOperationException($"Illegal toy action {action} in phase {state.Phase}.");
        }
    }

    public bool IsTerminal(ToyState state) => state.Phase == 2;

    public double Evaluate(ToyState state) => state.Reward;

    public ToyAction SelectRolloutAction(
        ToyState state,
        IReadOnlyList<ToyAction> legalActions,
        Random random)
    {
        // The toy oracle knows which future branch is good. The real STS2 rollout policy
        // will receive the complete ordered piles and RNG streams instead.
        return state.Phase == 1
            ? ToyAction.OpenKnownGoodChest
            : legalActions[random.Next(legalActions.Count)];
    }
}
