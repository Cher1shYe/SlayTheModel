using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Projects only the state exposed by a held relic's icon, counter, and hover
/// description. Native stack counts and relic-specific state are not display
/// features merely because they are available on the model.
/// </summary>
internal static class RelicDisplayProjector
{
    internal static RelicDisplayObservation Capture(RelicModel relic)
    {
        ArgumentNullException.ThrowIfNull(relic);

        // NRelicInventoryHolder.RefreshAmount uses this exact visibility rule.
        // ShowCounter can change with combat and relic state, so evaluate it at
        // every decision instead of maintaining a relic-type allowlist.
        var visibleCounter = RunManager.Instance.IsInProgress && relic.ShowCounter
            ? relic.DisplayAmount
            : (int?)null;

        return new RelicDisplayObservation(
            relic.Status.ToString(),
            relic.IsMelted,
            relic.IsWax,
            visibleCounter,
            ReadHoverDescription(relic));
    }

    private static string? ReadHoverDescription(RelicModel relic)
    {
        try
        {
            // The inventory holder shows relic.HoverTips on focus. HoverTip's
            // Description is the already formatted text of the primary tip,
            // including the native used-up or melted presentation.
            var description = relic.HoverTip.Description;
            return string.IsNullOrWhiteSpace(description) ? null : description;
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            // A transient localization/hover failure must not erase the
            // visible icon or counter from this decision's observation.
            return null;
        }
    }
}
