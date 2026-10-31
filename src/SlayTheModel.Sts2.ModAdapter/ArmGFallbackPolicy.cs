using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>Resolve an ArmG result without ever executing a stale or illegal action.</summary>
internal static class ArmGFallbackPolicy
{
    private static readonly FirstLegalOutsideCombatPolicy Fallback = new();

    internal static OutsideCombatActionDescriptor FirstLegal(OutsideCombatDecisionPoint decision) =>
        Fallback.SelectAction(decision);

    internal static OutsideCombatActionDescriptor? Select(
        OutsideCombatDecisionPoint decision, ArmGResponse response,
        bool autoMode, bool allowApproximate, out bool usedFallback)
    {
        usedFallback = false;
        if (!string.Equals(response.StateFingerprint, decision.StateFingerprint, StringComparison.Ordinal))
            throw new InvalidDataException("ArmG response belongs to a stale decision.");
        if (response.Status is "unsupported" or "error")
        {
            if (!autoMode) return null;
            usedFallback = true;
            return FirstLegal(decision);
        }
        var selected = ArmGDecisionGuard.Select(decision, response, autoMode, allowApproximate);
        if (selected is null && autoMode)
        {
            // The configured inference cannot be used, but the user's auto
            // mode still requires a legal action and must not stall the run.
            usedFallback = true;
            return FirstLegal(decision);
        }
        return selected;
    }
}
