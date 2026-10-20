using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Models.Powers;

namespace CombatSolver.Api;

public sealed partial class NativeMctsSimulationSession
{
    // Diagnostic only: branch mutations must not touch parent/sibling/live states.
    public void VerifyFatalBoundaryForTesting()
    {
        var parent = (CombatPredictionSimulator)root.Simulator;
        var branch = parent.Fork();
        var sibling = parent.Fork();
        var combat = (SimulatedCombatState)branch.State.CombatState;
        var enemies = combat.KnownEnemies.ToArray();
        var target = enemies.First(e => combat.GetPower<ReattachPower>(e) != null);
        var others = enemies.Where(e => e != target && combat.GetAmount<ReattachPower>(e) > 0).ToArray();
        if (others.Length == 0) throw new InvalidOperationException("Reattach fixture requires multiple segments.");
        var liveHp = enemies.Select(e => e.CurrentHp).ToArray();
        branch.State.GetCreature(target).CurrentHp = 0;
        if (CorePowerSupport.TargetDeathTriggersFatal(branch, combat, target))
            throw new InvalidOperationException("Surviving branch segment must prevent Fatal.");
        foreach (var other in others) branch.State.GetCreature(other).CurrentHp = 0;
        if (!CorePowerSupport.TargetDeathTriggersFatal(branch, combat, target))
            throw new InvalidOperationException("All branch segments dead must permit Fatal independently of live HP.");
        var descendant = branch.Fork();
        if (!CorePowerSupport.TargetDeathTriggersFatal(descendant, (SimulatedCombatState)descendant.State.CombatState, target))
            throw new InvalidOperationException("Fatal state lost through Fork.");
        if (CorePowerSupport.TargetDeathTriggersFatal(sibling, (SimulatedCombatState)sibling.State.CombatState, target))
            throw new InvalidOperationException("Sibling was contaminated by branch deaths.");
        if (others.Any(e => parent.State.GetCreature(e).IsDead || sibling.State.GetCreature(e).IsDead))
            throw new InvalidOperationException("Parent/sibling state changed.");
        if (!liveHp.SequenceEqual(enemies.Select(e => e.CurrentHp)))
            throw new InvalidOperationException("Diagnostic mutated live HP.");
    }
}
