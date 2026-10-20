using System.Diagnostics;
using System.Text.Json;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Search;

internal static class NativeEvolution
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("STS2_EVOLUTION_JOB")!));
        var job = document.RootElement;
        string source = job.GetProperty("source").GetString()!;
        string repo = job.GetProperty("repo").GetString()!;
        string mode = job.GetProperty("mode").GetString()!;
        if (mode is not ("collect" or "search" or "policy" or "uniform")) throw new InvalidDataException("Unknown evolution mode");
        using var prior = new StarterPriorClient(Path.Combine(source, ".venv-az/Scripts/python.exe"),
            Path.Combine(repo, "scripts/starter_prior_server.py"), source, job.GetProperty("checkpoint").GetString()!);
        int budgetMs = job.GetProperty("budgetMs").GetInt32();
        var rows = new List<object>();
        native.EncounterId = "BYRDONIS_ELITE";
        native.Checkpoint = null;
        foreach (var entry in job.GetProperty("cases").EnumerateArray())
        {
            int seed = entry.GetProperty("seed").GetInt32(), initialHp = entry.GetProperty("hp").GetInt32();
            native.EnterRoomForVerification = async (run, encounter) =>
            {
                var player = run.Players.Single();
                foreach (var relic in player.Relics.ToArray()) player.RemoveRelicInternal(relic, silent: true);
                await CreatureCmd.SetCurrentHp(player.Creature, initialHp);
                await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
            };
            await native.ResetAsync($"EVOLVE-{seed}", cancellation);
            using var env = new CombatSolverReplayEnvironment();
            env.Capture(native.CombatStateForSimulation, initialHp);
            var actionsTaken = new List<object>();
            var rng = new Random(seed);
            Func<IReadOnlyList<CombatSolverMctsAction>, CancellationToken, Task<IReadOnlyList<double>>> provider = mode == "uniform"
                ? (actions, ct) => Task.FromResult<IReadOnlyList<double>>(actions.Select(_ => 1d / actions.Count).ToArray())
                : (actions, ct) => prior.PredictAsync(env.ExportStarterPriorObservation(initialHp), ct);
            await provider(env.LegalActions(), cancellation);
            if (mode != "policy")
                await new ReplayMcts<CombatSolverMctsAction>(env, seed: seed, policyPrior: provider).SearchAsync([], env.RootKey,
                    TimeSpan.FromMilliseconds(300), TimeSpan.FromMilliseconds(300), cancellation);
            var tree = new ReplayMcts<CombatSolverMctsAction>(env, seed: seed, policyPrior: provider);
            double searchMs = 0;
            int simulations = 0;
            long calls = prior.Calls;
            while (!native.Terminal && actionsTaken.Count < 100 && native.Round <= 40)
            {
                await env.RestoreAsync([], cancellation);
                env.SetRootPlayerHp(native.Hp);
                var observation = env.ExportStarterPriorObservation(initialHp);
                var legal = env.LegalActions();
                CombatSolverMctsAction selected;
                var targets = new Dictionary<string, double>();
                int visits = 0;
                if (mode == "policy")
                {
                    var timer = Stopwatch.StartNew();
                    var probabilities = await prior.PredictAsync(observation, cancellation);
                    selected = legal[Enumerable.Range(0, legal.Count).MaxBy(i => probabilities[i])];
                    searchMs += timer.Elapsed.TotalMilliseconds;
                }
                else
                {
                    var budget = TimeSpan.FromMilliseconds(budgetMs);
                    var result = await tree.SearchAsync([], env.RootKey, budget, budget, cancellation);
                    visits = result.Statistics.Sum(s => s.Visits);
                    foreach (var a in legal)
                        targets.Add(a.Key, (double)(result.Statistics.FirstOrDefault(s => s.Action.Key == a.Key)?.Visits ?? 0) / visits);
                    selected = result.Action;
                    // Early-turn self-play exploration samples the actual visit distribution.
                    if (mode == "collect" && native.Round <= 2)
                    {
                        double draw = rng.NextDouble(), cumulative = 0;
                        foreach (var a in legal)
                        {
                            cumulative += targets[a.Key];
                            if (draw < cumulative) { selected = a; break; }
                        }
                    }
                    simulations += result.CompletedSimulations;
                    searchMs += result.ElapsedMilliseconds;
                }
                var expected = env.PredictSuccessor(selected);
                await native.StepAsync(native.ToLiveSearchAction(selected), cancellation);
                if (!native.Terminal && expected.ContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                    throw new InvalidDataException("Evolution native successor differs from prediction");
                env.Promote(selected);
                tree.Advance(selected);
                actionsTaken.Add(new { observation = mode == "collect" ? observation : null,
                    action = selected.Key, policy = targets, visits });
            }
            if (!native.Terminal) throw new InvalidDataException("Incomplete episode is not a terminal training label");
            double outcome = native.Won ? 0.9 + 0.1 * native.Hp / 80d : -1;
            rows.Add(new { seed, initialHp, mode, native.Won, finalHp = native.Hp, outcome,
                simulations, searchMs, priorCalls = prior.Calls - calls, actionsTaken });
            string output = job.GetProperty("output").GetString()!;
            File.WriteAllText(output + ".tmp", JsonSerializer.Serialize(new { format = "native-evolution-v1",
                informationMode = "full-state-search", observationMode = "observable",
                reward = "native-final-v1-policy-only", modelSha256 = prior.ModelIdentity, rows }));
            File.Move(output + ".tmp", output, overwrite: true);
            Godot.GD.Print($"EVOLVE {mode} seed={seed} hp={initialHp} won={native.Won} finalHp={native.Hp} decisions={actionsTaken.Count}");
        }
        native.EnterRoomForVerification = null;
    }
}
