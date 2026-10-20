using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;

internal static class MinionRewardVerification
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        await Reset(native, "QUEEN_BOSS", cancellation);
        var combat = native.CombatStateForSimulation;
        var minion = combat.Enemies.Single(enemy => !enemy.IsPrimaryEnemy);
        var queen = combat.Enemies.Single(enemy => enemy.IsPrimaryEnemy);
        var cohort = Capture(combat);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(combat, native.Hp);
        await Strike(native, environment, minion, cancellation);
        AssertProgress(native, environment, cohort);
        var afterMinion = environment.EnemyDamageFraction;
        if (afterMinion <= 0) throw new InvalidDataException("Queen minion must contribute to endpoint progress.");
        environment.Capture(combat, native.Hp);
        AssertProgress(native, environment, cohort);
        await Strike(native, environment, queen, cancellation);
        AssertProgress(native, environment, cohort);
        if (environment.EnemyDamageFraction <= afterMinion)
            throw new InvalidDataException("Queen and minion damage must both contribute.");

        await CreatureCmd.SetCurrentHp(minion, 1);
        environment.Capture(combat, native.Hp);
        var beforeKill = environment.EnemyDamageFraction;
        await Strike(native, environment, minion, cancellation);
        AssertProgress(native, environment, cohort);
        var total = cohort.Sum(enemy => (double)enemy.MaxHp);
        if (minion.IsAlive || native.Terminal || environment.Terminal
            || Math.Abs(environment.EnemyDamageFraction - beforeKill - 1 / total) > 1e-9
            || Math.Abs(native.EnemyDamageFraction - environment.EnemyDamageFraction) > 1e-9)
            throw new InvalidDataException("Minion death must count its final missing HP once, including after roster removal.");
        Godot.GD.Print($"SLAY_WORKER_MINION_REWARD_MATCH QUEEN_BOSS totalHp={total}: minion and queen count together; death counts once");
        Cleanup(native);
    }

    internal static async Task LateSummonsAsync(NativeSession native, CancellationToken cancellation)
    {
        foreach (var encounter in new[] { "OVICOPTER_NORMAL", "FOGMOG_NORMAL", "FABRICATOR_NORMAL" })
        {
            await Reset(native, encounter, cancellation);
            var combat = native.CombatStateForSimulation;
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(combat, native.Hp);
            var initialCohort = Capture(combat);
            for (var turn = 0; turn < 4 && !combat.Enemies.Any(enemy => !enemy.IsPrimaryEnemy); turn++)
            {
                await EndTurn(native, environment, cancellation);
                AssertProgress(native, environment, initialCohort);
            }
            var minion = combat.Enemies.First(enemy => enemy.IsAlive && !enemy.IsPrimaryEnemy);
            // Capture an actual post-summon decision root: its minions must count.
            var cohort = Capture(combat);
            environment.Capture(combat, native.Hp);
            var before = environment.EnemyDamageFraction;
            await Strike(native, environment, minion, cancellation);
            AssertProgress(native, environment, cohort);
            var firstHit = environment.EnemyDamageFraction;
            if (firstHit <= before) throw new InvalidDataException("Captured summon damage must count.");
            environment.Capture(combat, native.Hp);
            AssertProgress(native, environment, cohort);
            if (minion.IsDead)
            {
                // A root captured at zero HP must retain the reviving identity.
                await EndTurn(native, environment, cancellation);
                AssertProgress(native, environment, cohort);
                if (!minion.IsAlive || environment.EnemyDamageFraction >= firstHit)
                    throw new InvalidDataException("Revival must remove the previous life's missing-HP reward.");
                await Strike(native, environment, minion, cancellation);
                AssertProgress(native, environment, cohort);
                if (Math.Abs(environment.EnemyDamageFraction - firstHit) > 1e-9)
                    throw new InvalidDataException("Killing the same illusion twice accumulated damage reward.");
                Godot.GD.Print($"SLAY_WORKER_REVIVAL_REWARD_MATCH {encounter}: first death={firstHit}, second death={environment.EnemyDamageFraction}; no cumulative damage");
            }
            else
            {
                await Strike(native, environment, minion, cancellation);
                AssertProgress(native, environment, cohort);
            }
            Godot.GD.Print($"SLAY_WORKER_LATE_SUMMON_REWARD_MATCH {encounter}: captured summons use final HP, including across recapture");
        }
        Cleanup(native);
    }

    private static (Creature Identity, int MaxHp)[] Capture(MegaCrit.Sts2.Core.Combat.CombatState combat)
        => combat.Enemies.Select(enemy => (enemy, enemy.MaxHp)).ToArray();

    private static async Task Reset(NativeSession native, string encounter, CancellationToken cancellation)
    {
        native.Checkpoint = null;
        native.ChoiceFixture = true;
        native.ChoiceFixtureCards = Enumerable.Repeat("STRIKE_IRONCLAD", 5).ToArray();
        native.EncounterId = encounter;
        await native.ResetAsync("ENDPOINT-REWARD-" + encounter, cancellation);
    }

    private static void Cleanup(NativeSession native)
    {
        native.ChoiceFixture = false;
        native.ChoiceFixtureCards = ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        native.EncounterId = "CULTISTS_NORMAL";
    }

    private static async Task Strike(NativeSession native, CombatSolverReplayEnvironment environment,
        Creature target, CancellationToken cancellation)
    {
        var action = environment.LegalActions().First(action =>
            action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == target.CombatId);
        await environment.ApplyAsync(action, cancellation);
        await native.StepAsync(native.ToLiveSearchAction(action), cancellation);
    }

    private static async Task EndTurn(NativeSession native, CombatSolverReplayEnvironment environment, CancellationToken cancellation)
    {
        var action = environment.LegalActions().Single(action => action.Native.Kind == "EndTurn");
        await environment.ApplyAsync(action, cancellation);
        await native.StepAsync(native.ToLiveSearchAction(action), cancellation);
    }

    private static void AssertProgress(NativeSession native, CombatSolverReplayEnvironment environment,
        (Creature Identity, int MaxHp)[] cohort)
    {
        var total = cohort.Sum(enemy => (double)enemy.MaxHp);
        var remaining = cohort.Sum(enemy => (double)Math.Clamp(enemy.Identity.CurrentHp, 0, enemy.MaxHp));
        var expected = (total - remaining) / total;
        if (Math.Abs(environment.EnemyDamageFraction - expected) > 1e-9)
            throw new InvalidDataException($"Endpoint progress mismatch: expected={expected}, predicted={environment.EnemyDamageFraction}");
        if (environment.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
            throw new InvalidDataException("Endpoint reward fixture diverged from native continuation state.");
    }
}
