using SlayTheModel.Search;
using CombatSolver.Api;
using System.Text.Json;

internal static class RewardVerification
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        await InputsAsync(native, cancellation);
        foreach (var encounter in new[] { "CULTISTS_NORMAL", "KAISER_CRAB_BOSS", "QUEEN_BOSS" })
        {
            native.Checkpoint = null;
            native.ChoiceFixture = false;
            native.EncounterId = encounter;
            await native.ResetAsync("REWARD-" + encounter, cancellation);
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(native.CombatStateForSimulation, native.Hp);
            var shortBudget = TimeSpan.FromMilliseconds(300);
            var legacy = new LegacyReward(environment);
            var flat = await new ReplayMcts<CombatSolverMctsAction>(legacy, seed: 41)
                .SearchAsync([], environment.RootKey, shortBudget, shortBudget, cancellation, maxDepth: 1);
            var shaped = await new ReplayMcts<CombatSolverMctsAction>(environment, seed: 41)
                .SearchAsync([], environment.RootKey, shortBudget, shortBudget, cancellation, maxDepth: 1);
            if (flat.Statistics.Any(item => Math.Abs(item.MeanValue + 0.5) > 1e-9)
                || shaped.Statistics.Max(item => item.MeanValue) <= shaped.Statistics.Min(item => item.MeanValue))
                throw new InvalidDataException($"{encounter}: depth-limited enemy damage did not break the old flat reward.");

            await environment.RestoreAsync([], cancellation);
            var rootProgress = environment.EnemyDamageFraction;
            var predicted = environment.PredictSuccessor(shaped.Action);
            await environment.ApplyAsync(shaped.Action, cancellation);
            var predictedProgress = environment.EnemyDamageFraction;
            await native.StepAsync(native.ToLiveSearchAction(shaped.Action), cancellation);
            if (Math.Abs(predictedProgress - native.EnemyDamageFraction) > 1e-9
                || predictedProgress <= rootProgress
                || predicted.ContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                throw new InvalidDataException($"{encounter}: shaped action/progress diverged from native execution.");
            await environment.RestoreAsync([], cancellation);
            if (environment.EnemyDamageFraction != rootProgress)
                throw new InvalidDataException("Reward leaked between replay branches.");
            environment.Promote(shaped.Action);
            if (Math.Abs(environment.EnemyDamageFraction - predictedProgress) > 1e-9)
                throw new InvalidDataException("Root promotion changed reward normalization.");

            // Normal-depth searches from the same post-action root and equal
            // time budgets exercise the production path; report, don't infer
            // whole-fight win-rate improvements from a single decision.
            var budget = TimeSpan.FromSeconds(2);
            var oldFull = await new ReplayMcts<CombatSolverMctsAction>(legacy, seed: 41)
                .SearchAsync([], environment.RootKey, budget, budget, cancellation);
            var newFull = await new ReplayMcts<CombatSolverMctsAction>(environment, seed: 41)
                .SearchAsync([], environment.RootKey, budget, budget, cancellation);
            Godot.GD.Print("SLAY_WORKER_REWARD_MATCH " + JsonSerializer.Serialize(new
            {
                encounter, predictedProgress, nativeProgress = native.EnemyDamageFraction,
                cutoffAction = shaped.Action.Native.CardId,
                oldAction = oldFull.Action.Key, newAction = newFull.Action.Key,
                oldSimulations = oldFull.CompletedSimulations, newSimulations = newFull.CompletedSimulations,
                oldMeans = oldFull.Statistics.Select(item => item.MeanValue),
                newMeans = newFull.Statistics.Select(item => item.MeanValue),
            }));
        }
        native.EncounterId = "CULTISTS_NORMAL";
    }

    private static async Task InputsAsync(NativeSession native, CancellationToken cancellation)
    {
        native.Checkpoint = null;
        native.EncounterId = "CULTISTS_NORMAL";
        await native.ResetAsync("REWARD-INPUTS", cancellation);
        await native.StepAsync(native.Actions().Single(action => action.Combat?.Kind == SlayTheModel.Sts2.Protocol.CombatActionKind.EndTurn), cancellation);
        var combat = native.CombatStateForSimulation;
        var player = combat.Players.Single();
        await MegaCrit.Sts2.Core.Commands.CreatureCmd.SetMaxHp(player.Creature, 100);
        await MegaCrit.Sts2.Core.Commands.CreatureCmd.SetCurrentHp(player.Creature, 40);
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(combat, 80); // Deliberately stale combat-entry HP.
        simulation.BeginRollout();
        if (simulation.RewardContextKey != "40") throw new InvalidDataException("H0 must be rollout root HP.");
        var defend = simulation.LegalActions().First(action => action.Native.CardId == "DEFEND_IRONCLAD");
        await simulation.ApplyAsync(defend, cancellation);
        await native.StepAsync(native.ToLiveSearchAction(defend), cancellation);
        using var projected = NativeMctsSimulationApi.Capture(combat);
        var description = projected.DescribeCurrent();
        if (description.PlayerMaxHp != 100 || player.Creature.Block <= 0 || description.IncomingDamage <= 0)
            throw new InvalidDataException("Risk fixture must include block and incoming damage.");
        var expected = CombatRolloutReward.Evaluate(false, false, 40, 100, 40,
            simulation.EnemyDamageFraction, description.IncomingDamage);
        if (Math.Abs(simulation.EvaluateCutoff() - expected) > 1e-9)
            throw new InvalidDataException("Simulation reward input wiring differs.");
        var end = simulation.LegalActions().Single(action => action.Native.Kind == "EndTurn");
        await simulation.ApplyAsync(end, cancellation);
        await native.StepAsync(native.ToLiveSearchAction(end), cancellation);
        if (40 - native.Hp != description.IncomingDamage
            || simulation.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(combat))
            throw new InvalidDataException("Projected actual damage differs from blocked native attack.");
        Godot.GD.Print($"SLAY_WORKER_REWARD_INPUTS_MATCH H0=40 maxHp=100 blockedIncoming={description.IncomingDamage} full continuation matched");
    }

    private sealed class LegacyReward(CombatSolverReplayEnvironment inner) : IReplayEnvironment<CombatSolverMctsAction>
    {
        public Task RestoreAsync(IReadOnlyList<CombatSolverMctsAction> prefix, CancellationToken cancellation) => inner.RestoreAsync(prefix, cancellation);
        public Task ApplyAsync(CombatSolverMctsAction action, CancellationToken cancellation) => inner.ApplyAsync(action, cancellation);
        public IReadOnlyList<CombatSolverMctsAction> LegalActions() => inner.LegalActions();
        public string StateKey() => inner.StateKey();
        public bool Terminal => inner.Terminal;
        public void BeginRollout() => inner.BeginRollout();
        public string RewardContextKey => inner.RewardContextKey;
        public bool CanEvaluate => inner.CanEvaluate;
        public double EvaluateTerminal() { var value = inner.EvaluateTerminal(); return value > 0 ? value : -1; }
        public double EvaluateCutoff() => -0.5;
        public CombatSolverMctsAction RolloutAction(IReadOnlyList<CombatSolverMctsAction> actions, Random random) => inner.RolloutAction(actions, random);
    }
}
