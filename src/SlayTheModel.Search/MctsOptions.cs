namespace SlayTheModel.Search;

public sealed record MctsOptions
{
    public int Simulations { get; init; } = 10_000;

    public int MaxRolloutDepth { get; init; } = 512;

    public double ExplorationConstant { get; init; } = Math.Sqrt(2.0);

    public int RandomSeed { get; init; } = 1;

    internal void Validate()
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(Simulations);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(MaxRolloutDepth);

        if (!double.IsFinite(ExplorationConstant) || ExplorationConstant < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(ExplorationConstant),
                "Exploration constant must be finite and non-negative.");
        }
    }
}
