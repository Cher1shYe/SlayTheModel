using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models.Powers;

internal static class FatalBoundaryVerification
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        native.ChoiceFixture = true;
        native.ChoiceFixtureCards = Enumerable.Repeat("STRIKE_IRONCLAD", 5).ToArray();
        native.EncounterId = "DECIMILLIPEDE_ELITE";
        await native.ResetAsync("FATAL-BRANCH-BOUNDARY", cancellation);
        var combat = native.CombatStateForSimulation;
        using var prediction = NativeMctsSimulationApi.Capture(combat);
        prediction.VerifyFatalBoundaryForTesting();
        var segments = combat.Enemies.Where(e => e.HasPower<ReattachPower>()).ToArray();
        var hp = segments.Select(e => e.CurrentHp).ToArray();
        // Advance live HP after capture; the frozen prediction must retain its own HP.
        try
        {
            foreach (var other in segments.Skip(1)) await CreatureCmd.SetCurrentHp(other, 0);
            prediction.VerifyFatalBoundaryForTesting();
        }
        finally
        {
            for (int i = 0; i < segments.Length; i++) await CreatureCmd.SetCurrentHp(segments[i], hp[i]);
        }
        Godot.GD.Print("FATAL_BOUNDARY_PASS branch-alive/dead; live-divergence; parent/sibling/descendant isolation");
    }
}
