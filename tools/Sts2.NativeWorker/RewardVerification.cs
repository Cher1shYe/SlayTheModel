using CombatSolver.Api;
using SlayTheModel.Search;
using System.Text.Json;

internal static class RewardVerification
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
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
                .SearchAsync([], environment.RootKey, shortBudget, shortBudget,
                    cancellation, maxDepth: 1);
            var shaped = await new ReplayMcts<CombatSolverMctsAction>(environment, seed: 41)
                .SearchAsync([], environment.RootKey, shortBudget, shortBudget,
                    cancellation, maxDepth: 1);
            if (flat.Statistics.Any(item => Math.Abs(item.MeanValue + 0.5) > 1e-9)
                || shaped.Statistics.Max(item => item.MeanValue)
                <= shaped.Statistics.Min(item => item.MeanValue))
            {
                throw new InvalidDataException(
                    $"{encounter}: depth-limited enemy damage did not break the old flat reward.");
            }

            await environment.RestoreAsync([], cancellation);
            var rootProgress = environment.EnemyDamageFraction;
            var predicted = environment.PredictSuccessor(shaped.Action);
            await environment.ApplyAsync(shaped.Action, cancellation);
            var predictedProgress = environment.EnemyDamageFraction;
            await native.StepAsync(native.ToLiveSearchAction(shaped.Action), cancellation);
            if (Math.Abs(predictedProgress - native.EnemyDamageFraction) > 1e-9
                || predictedProgress <= rootProgress
                || predicted.ContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                    native.CombatStateForSimulation))
            {
                throw new InvalidDataException(
                    $"{encounter}: shaped action/progress diverged from native execution.");
            }

            await environment.RestoreAsync([], cancellation);
            if (environment.EnemyDamageFraction != rootProgress)
                throw new InvalidDataException("Reward leaked between replay branches.");
            environment.Promote(shaped.Action);
            if (Math.Abs(environment.EnemyDamageFraction - predictedProgress) > 1e-9)
                throw new InvalidDataException("Root promotion changed reward normalization.");

            // This exercises the production depth and reports mechanism data.
            // A single decision is not evidence of whole-run win-rate gains.
            var budget = TimeSpan.FromSeconds(2);
            var oldFull = await new ReplayMcts<CombatSolverMctsAction>(legacy, seed: 41)
                .SearchAsync([], environment.RootKey, budget, budget, cancellation);
            var newFull = await new ReplayMcts<CombatSolverMctsAction>(environment, seed: 41)
                .SearchAsync([], environment.RootKey, budget, budget, cancellation);
            Godot.GD.Print("SLAY_WORKER_REWARD_MATCH " + JsonSerializer.Serialize(new
            {
                encounter,
                predictedProgress,
                nativeProgress = native.EnemyDamageFraction,
                cutoffAction = shaped.Action.Native.CardId,
                oldAction = oldFull.Action.Key,
                newAction = newFull.Action.Key,
                oldSimulations = oldFull.CompletedSimulations,
                newSimulations = newFull.CompletedSimulations,
                oldMeans = oldFull.Statistics.Select(item => item.MeanValue),
                newMeans = newFull.Statistics.Select(item => item.MeanValue),
            }));
        }

        native.EncounterId = "CULTISTS_NORMAL";
    }

    private sealed class LegacyReward(CombatSolverReplayEnvironment inner)
        : IReplayEnvironment<CombatSolverMctsAction>
    {
        public Task RestoreAsync(
            IReadOnlyList<CombatSolverMctsAction> prefix,
            CancellationToken cancellation) => inner.RestoreAsync(prefix, cancellation);

        public Task ApplyAsync(
            CombatSolverMctsAction action,
            CancellationToken cancellation) => inner.ApplyAsync(action, cancellation);

        public IReadOnlyList<CombatSolverMctsAction> LegalActions() => inner.LegalActions();
        public string StateKey() => inner.StateKey();
        public bool Terminal => inner.Terminal;
        public double EvaluateTerminal()
        {
            var value = inner.EvaluateTerminal();
            return value > 0 ? value : -1;
        }
        public double EvaluateCutoff() => -0.5;
        public CombatSolverMctsAction RolloutAction(
            IReadOnlyList<CombatSolverMctsAction> actions,
            Random random) => inner.RolloutAction(actions, random);
    }
}
