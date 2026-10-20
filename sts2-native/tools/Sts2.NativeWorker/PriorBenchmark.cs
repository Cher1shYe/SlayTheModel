using System.Diagnostics;
using System.Text.Json;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Search;

internal static class PriorBenchmark
{
    internal static async Task RunAsync(NativeSession native, string output, CancellationToken cancellation)
    {
        string Required(string name) => Environment.GetEnvironmentVariable(name) ?? throw new InvalidOperationException(name);
        string source = Required("STS2_PRIOR_SOURCE");
        string repo = Required("STS2_PRIOR_REPO");
        using var prior = new StarterPriorClient(Path.Combine(source, ".venv-az/Scripts/python.exe"),
            Path.Combine(repo, "scripts/starter_prior_server.py"), source, Required("STS2_PRIOR_MODEL"));
        int seed = int.Parse(Environment.GetEnvironmentVariable("STS2_PRIOR_SEED") ?? "1");
        int hp = int.Parse(Environment.GetEnvironmentVariable("STS2_PRIOR_HP") ?? "80");
        int budgetMs = int.Parse(Environment.GetEnvironmentVariable("STS2_PRIOR_BUDGET_MS") ?? "100");
        native.EncounterId = Environment.GetEnvironmentVariable("STS2_PRIOR_ENCOUNTER") ?? "BYRDONIS_ELITE";
        native.Checkpoint = null;
        native.EnterRoomForVerification = async (run, encounter) =>
        {
            var player = run.Players.Single();
            foreach (var relic in player.Relics.ToArray()) player.RemoveRelicInternal(relic, silent: true);
            await CreatureCmd.SetCurrentHp(player.Creature, hp);
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
        };
        var results = new List<object>();
        // Rotate order across paired seeds; all arms get identical native roots and budgets.
        string[] arms = seed % 2 == 0 ? ["learned", "uniform", "uct"] : ["uct", "uniform", "learned"];
        foreach (string arm in arms)
        {
            await native.ResetAsync($"PRIOR-PAIR-{seed}", cancellation);
            using var env = new CombatSolverReplayEnvironment();
            env.Capture(native.CombatStateForSimulation, hp);
            Func<IReadOnlyList<CombatSolverMctsAction>, CancellationToken, Task<IReadOnlyList<double>>>? provider = arm switch
            {
                "uct" => null,
                "uniform" => (actions, ct) => Task.FromResult<IReadOnlyList<double>>(actions.Select(_ => 1d / actions.Count).ToArray()),
                _ => (actions, ct) => prior.PredictAsync(env.ExportStarterPriorObservation(hp), ct)
            };
            var shortBudget = TimeSpan.FromMilliseconds(budgetMs);
            if (provider != null) await provider(env.LegalActions(), cancellation);
            // Warm each arm on this root; no action executes and measurements exclude warmup.
            await new ReplayMcts<CombatSolverMctsAction>(env, seed: 17, policyPrior: provider)
                .SearchAsync([], env.RootKey, TimeSpan.FromMilliseconds(500), TimeSpan.FromMilliseconds(500), cancellation);
            var speeds = new List<object>();
            for (int i = 0; i < 3; i++)
            {
                long before = env.Transitions;
                long calls = prior.Calls;
                var result = await new ReplayMcts<CombatSolverMctsAction>(env, seed: seed + i, policyPrior: provider)
                    .SearchAsync([], env.RootKey, TimeSpan.FromMilliseconds(250), TimeSpan.FromMilliseconds(250), cancellation);
                speeds.Add(new { result.CompletedSimulations, result.ElapsedMilliseconds,
                    transitions = env.Transitions-before, calls = prior.Calls-calls,
                    simsPerSecond = result.CompletedSimulations*1000d/result.ElapsedMilliseconds });
            }
            long beginCalls = prior.Calls, beginTransitions = env.Transitions;
            double beginWall = prior.WallMs, beginEncode = prior.EncodeMs, beginInfer = prior.InferMs;
            var tree = new ReplayMcts<CombatSolverMctsAction>(env, seed: seed, policyPrior: provider);
            int decisions = 0, simulations = 0;
            double searchMs = 0;
            var actionsTaken = new List<object>();
            var wall = Stopwatch.StartNew();
            while (!native.Terminal && decisions < 100 && native.Round <= 40)
            {
                env.SetRootPlayerHp(native.Hp);
                var result = await tree.SearchAsync([], env.RootKey, shortBudget, shortBudget, cancellation);
                var expected = env.PredictSuccessor(result.Action);
                await native.StepAsync(native.ToLiveSearchAction(result.Action), cancellation);
                if (!native.Terminal && expected.ContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                    throw new InvalidDataException("Prior benchmark native continuation mismatch.");
                env.Promote(result.Action);
                tree.Advance(result.Action);
                decisions++;
                simulations += result.CompletedSimulations;
                searchMs += result.ElapsedMilliseconds;
                actionsTaken.Add(new { action=result.Action.Key, result.CompletedSimulations,
                    policy = result.Statistics.Select(stat => new { key=stat.Action.Key, stat.Visits, stat.MeanValue,
                        probability = (double)stat.Visits / result.Statistics.Sum(s => s.Visits) }),
                    priors = result.RootPriors?.Select(p => new { key=p.Key.Key, probability=p.Value }) });
            }
            var row = new { arm, seed, encounter=native.EncounterId, initialHp=hp, budgetMs,
                native.Won, native.Terminal, finalHp=native.Hp, round=native.Round, decisions,
                utility=env.EvaluateTerminal(), simulations, searchMs, wallMs=wall.Elapsed.TotalMilliseconds,
                transitions=env.Transitions-beginTransitions, priorCalls=prior.Calls-beginCalls,
                priorWallMs=prior.WallMs-beginWall, encodeMs=prior.EncodeMs-beginEncode, inferMs=prior.InferMs-beginInfer,
                speeds, actionsTaken };
            results.Add(row);
            File.WriteAllText(output, JsonSerializer.Serialize(new { modelSha256=prior.ModelIdentity,
                informationMode="full-state", adapter="native-starter-prior-v1", results }, new JsonSerializerOptions { WriteIndented=true }));
            Godot.GD.Print($"PRIOR_ARM {arm} seed={seed} hp={hp} won={native.Won} finalHp={native.Hp} decisions={decisions} sims={simulations} searchMs={searchMs:F0}");
        }
        native.EnterRoomForVerification = null;
    }
}
