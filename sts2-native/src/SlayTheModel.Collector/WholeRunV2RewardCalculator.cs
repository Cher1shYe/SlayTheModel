namespace SlayTheModel.Collector;

/// <summary>
/// The seven persistent run measurements used by the whole-run-v2 step reward.
/// Producers may carry unavailable measurements as null, but must not turn them
/// into a zero delta when publishing a training reward.
/// </summary>
public sealed record WholeRunV2Metrics(
    int? CurrentHp,
    int? Gold,
    int? ActIndex,
    int? TotalFloor,
    int? DeckSize,
    int? RelicCount,
    int? PotionCount);

/// <summary>Shared, game-independent whole-run-v2 reward contract.</summary>
public static class WholeRunV2RewardCalculator
{
    public const string Version = "whole-run-v2";

    private static readonly HashSet<string> ComponentNames = new(StringComparer.Ordinal)
    {
        "act_delta",
        "deck_size_delta",
        "floor_delta",
        "gold_delta",
        "hp_delta",
        "potion_count_delta",
        "relic_count_delta",
        "terminal",
    };

    public static bool HasMetrics(WholeRunV2Metrics? metrics) => metrics is
    {
        CurrentHp: not null,
        Gold: not null,
        ActIndex: not null,
        TotalFloor: not null,
        DeckSize: not null,
        RelicCount: not null,
        PotionCount: not null,
    };

    public static IReadOnlyDictionary<string, double> Compute(
        WholeRunV2Metrics before,
        WholeRunV2Metrics after)
    {
        ArgumentNullException.ThrowIfNull(before);
        ArgumentNullException.ThrowIfNull(after);
        if (!HasMetrics(before) || !HasMetrics(after))
        {
            throw new InvalidDataException(
                "whole-run-v2 requires all before and after run metrics.");
        }

        return new SortedDictionary<string, double>(StringComparer.Ordinal)
        {
            ["act_delta"] = after.ActIndex!.Value - before.ActIndex!.Value,
            ["deck_size_delta"] = after.DeckSize!.Value - before.DeckSize!.Value,
            ["floor_delta"] = after.TotalFloor!.Value - before.TotalFloor!.Value,
            ["gold_delta"] = after.Gold!.Value - before.Gold!.Value,
            ["hp_delta"] = after.CurrentHp!.Value - before.CurrentHp!.Value,
            ["potion_count_delta"] = after.PotionCount!.Value - before.PotionCount!.Value,
            ["relic_count_delta"] = after.RelicCount!.Value - before.RelicCount!.Value,
            ["terminal"] = 0,
        };
    }

    public static void ValidateComponents(IReadOnlyDictionary<string, double> components)
    {
        ArgumentNullException.ThrowIfNull(components);
        if (components.Count != ComponentNames.Count
            || components.Keys.Any(key => !ComponentNames.Contains(key))
            || components.Values.Any(value => !double.IsFinite(value)))
        {
            throw new InvalidDataException(
                "whole-run-v2 reward must contain exactly its eight finite components.");
        }
    }
}
