using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models;
using System.Text.Json;

internal static class MinionRewardVerification
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        Godot.GD.Print("SLAY_WORKER_SECONDARY_POWERS " + string.Join(",", ModelDb.All.OfType<PowerModel>()
            .Where(power => power.OwnerIsSecondaryEnemy).Select(power => power.Id.Entry).Order()));
        var tested = 0;
        foreach (var encounter in new[] { "QUEEN_BOSS", "KAISER_CRAB_BOSS" })
        {
            native.Checkpoint = null;
            native.ChoiceFixture = true;
            native.ChoiceFixtureCards = Enumerable.Repeat("STRIKE_IRONCLAD", 5).ToArray();
            native.EncounterId = encounter;
            await native.ResetAsync("MINION-REWARD-" + encounter, cancellation);
            var combat = native.CombatStateForSimulation;
            Godot.GD.Print("SLAY_WORKER_REWARD_ROSTER " + JsonSerializer.Serialize(new
            {
                encounter, enemies = combat.Enemies.Select(enemy => new
                { id = enemy.Monster?.Id.Entry, enemy.IsPrimaryEnemy, enemy.CurrentHp, enemy.MaxHp })
            }));
            var secondary = combat.Enemies.FirstOrDefault(enemy => enemy.IsAlive && !enemy.IsPrimaryEnemy);
            if (secondary is null) continue;
            tested++;
            var primary = combat.Enemies.First(enemy => enemy.IsAlive && enemy.IsPrimaryEnemy);
            var totalPrimaryHp = combat.Enemies.Where(enemy => enemy.IsAlive && enemy.IsPrimaryEnemy)
                .Sum(enemy => (double)enemy.MaxHp);
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(combat, native.Hp);
            var secondaryStrike = environment.LegalActions().First(action =>
                action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == secondary.CombatId);
            await environment.ApplyAsync(secondaryStrike, cancellation);
            var secondaryHp = secondary.CurrentHp;
            await native.StepAsync(native.ToLiveSearchAction(secondaryStrike), cancellation);
            if (secondary.CurrentHp >= secondaryHp
                || environment.EnemyDamageFraction != 0 || native.EnemyDamageFraction != 0)
                throw new InvalidDataException($"{encounter}: damaging an existing secondary enemy must give zero progress.");
            MatchContinuation(environment, combat);

            // A fresh capture mid-fight must not convert a damaged minion to progress.
            environment.Capture(combat, native.Hp);
            if (environment.EnemyDamageFraction != 0)
                throw new InvalidDataException("Recapture included damaged secondary enemies.");
            var primaryStrike = environment.LegalActions().First(action =>
                action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == primary.CombatId);
            await environment.ApplyAsync(primaryStrike, cancellation);
            await native.StepAsync(native.ToLiveSearchAction(primaryStrike), cancellation);
            var expected = combat.Enemies.Where(enemy => enemy.IsPrimaryEnemy)
                .Sum(enemy => (double)enemy.MaxHp - enemy.CurrentHp) / totalPrimaryHp;
            if (expected <= 0 || Math.Abs(environment.EnemyDamageFraction - expected) > 1e-9
                || Math.Abs(native.EnemyDamageFraction - expected) > 1e-9)
                throw new InvalidDataException("Primary enemy damage used a denominator containing secondary HP.");
            MatchContinuation(environment, combat);

            // Put the same minion at one HP to exercise death without a long fight.
            await CreatureCmd.SetCurrentHp(secondary, 1);
            environment.Capture(combat, native.Hp);
            var beforeKill = environment.EnemyDamageFraction;
            var killingStrike = environment.LegalActions().First(action =>
                action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == secondary.CombatId);
            await environment.ApplyAsync(killingStrike, cancellation);
            await native.StepAsync(native.ToLiveSearchAction(killingStrike), cancellation);
            if (secondary.IsAlive || environment.Terminal || native.Terminal
                || Math.Abs(environment.EnemyDamageFraction - beforeKill) > 1e-9
                || Math.Abs(native.EnemyDamageFraction - beforeKill) > 1e-9)
                throw new InvalidDataException("Secondary death changed progress or incorrectly ended combat.");
            MatchContinuation(environment, combat);
            Godot.GD.Print($"SLAY_WORKER_MINION_REWARD_MATCH {encounter}: damage, recapture, primary denominator and minion death matched native");
        }
        if (tested == 0) throw new InvalidDataException("No secondary-enemy fixture was exercised.");
        native.ChoiceFixture = false;
        native.ChoiceFixtureCards = ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        native.EncounterId = "CULTISTS_NORMAL";
    }

    internal static async Task LateSummonsAsync(NativeSession native, CancellationToken cancellation)
    {
        foreach (var encounter in new[] { "OVICOPTER_NORMAL", "FOGMOG_NORMAL", "FABRICATOR_NORMAL" })
        {
            native.Checkpoint = null;
            native.ChoiceFixture = true;
            native.ChoiceFixtureCards = Enumerable.Repeat("STRIKE_IRONCLAD", 5).ToArray();
            native.EncounterId = encounter;
            await native.ResetAsync("LATE-SUMMON-" + encounter, cancellation);
            var combat = native.CombatStateForSimulation;
            if (combat.Enemies.Any(enemy => !enemy.IsPrimaryEnemy))
                throw new InvalidDataException($"{encounter}: fixture must begin before the summon.");
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(combat, native.Hp);
            for (int turn = 0; turn < 4 && !combat.Enemies.Any(enemy => !enemy.IsPrimaryEnemy); turn++)
            {
                var end = environment.LegalActions().Single(action => action.Native.Kind == "EndTurn");
                await environment.ApplyAsync(end, cancellation);
                await native.StepAsync(native.ToLiveSearchAction(end), cancellation);
                MatchContinuation(environment, combat);
                if (environment.EnemyDamageFraction != 0 || native.EnemyDamageFraction != 0)
                    throw new InvalidDataException("Summoning alone changed progress.");
            }
            var minion = combat.Enemies.FirstOrDefault(enemy => enemy.IsAlive && !enemy.IsPrimaryEnemy)
                ?? throw new InvalidDataException($"{encounter}: no live secondary was summoned within four turns.");
            var strike = environment.LegalActions().First(action =>
                action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == minion.CombatId);
            var hp = minion.CurrentHp;
            await environment.ApplyAsync(strike, cancellation);
            await native.StepAsync(native.ToLiveSearchAction(strike), cancellation);
            MatchContinuation(environment, combat);
            if (minion.CurrentHp >= hp || environment.EnemyDamageFraction != 0 || native.EnemyDamageFraction != 0)
                throw new InvalidDataException("Damaging a later summon changed progress.");
            environment.Capture(combat, native.Hp);
            if (environment.EnemyDamageFraction != 0)
                throw new InvalidDataException("Recapture started rewarding a later summon.");
            // Illusions can die in one hit and revive next turn. Exercise that
            // lifecycle before attempting another hit, instead of assuming alive.
            if (minion.IsDead)
            {
                var end = environment.LegalActions().Single(action => action.Native.Kind == "EndTurn");
                await environment.ApplyAsync(end, cancellation);
                await native.StepAsync(native.ToLiveSearchAction(end), cancellation);
                MatchContinuation(environment, combat);
                if (!minion.IsAlive || environment.EnemyDamageFraction != 0 || native.EnemyDamageFraction != 0)
                    throw new InvalidDataException("Illusion revival changed progress or did not revive.");
                environment.Capture(combat, native.Hp);
            }
            // Damage after recapture as well: a full-health minion exclusion alone
            // would not prove the new denominator/cohort remains correct.
            strike = environment.LegalActions().First(action =>
                action.Native.CardId == "STRIKE_IRONCLAD" && action.Native.TargetCombatId == minion.CombatId);
            await environment.ApplyAsync(strike, cancellation);
            await native.StepAsync(native.ToLiveSearchAction(strike), cancellation);
            MatchContinuation(environment, combat);
            if (environment.EnemyDamageFraction != 0 || native.EnemyDamageFraction != 0)
                throw new InvalidDataException("Recaptured summon damage changed progress.");
            Godot.GD.Print($"SLAY_WORKER_LATE_SUMMON_REWARD_MATCH {encounter}: summon, damage and recapture matched native; secondary={minion.Monster?.Id.Entry}");
        }
        native.ChoiceFixture = false;
        native.ChoiceFixtureCards = ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        native.EncounterId = "CULTISTS_NORMAL";
    }

    private static void MatchContinuation(CombatSolverReplayEnvironment environment, MegaCrit.Sts2.Core.Combat.CombatState combat)
    {
        if (environment.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(combat))
            throw new InvalidDataException("Minion reward fixture diverged from native continuation state.");
    }
}
