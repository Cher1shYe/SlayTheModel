using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Combat.History.Entries;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Search;

// Bounded collection adapter, independent of NativeEvolution and its training protocol.
internal static class CollectionPilot
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("STS2_COLLECTION_PILOT_JOB")!));
        var job = document.RootElement;
        if (job.TryGetProperty("format", out var generic) && generic.GetString() == "native-generic-collection-v1")
        {
            await GenericCollection.RunAsync(native, cancellation);
            return;
        }
        bool v2 = job.TryGetProperty("format", out var format) && format.GetString() == "native-collection-v2";
        string source = job.GetProperty("source").GetString()!;
        string identity = job.GetProperty("identity").GetString()!;
        int budgetMs = job.GetProperty("budgetMs").GetInt32();
        var cases = job.GetProperty("cases").EnumerateArray().ToArray();
        if (cases.Length > 24 || budgetMs < 50 || budgetMs > 1000)
            throw new InvalidDataException("Pilot limited to 24 fights and 50..1000 ms per decision");
        using var prior = new StarterPriorClient(Path.Combine(source, ".venv-az/Scripts/python.exe"),
            Path.Combine(source, "scripts/native_pilot_service.py"), source, job.GetProperty("checkpoint").GetString()!);
        if (prior.ModelIdentity != job.GetProperty("modelSha256").GetString())
            throw new InvalidDataException("Frozen collection model changed");
        native.EncounterId = "BYRDONIS_ELITE";
        native.Checkpoint = null;
        foreach (var entry in cases)
        {
            native.EncounterId = v2 ? entry.GetProperty("encounter").GetString()! : "BYRDONIS_ELITE";
            if (native.EncounterId is not ("BYRDONIS_ELITE" or "NIBBITS_WEAK"))
                throw new InvalidDataException("Unaudited collection encounter");
            native.ChoiceFixture = v2;
            native.ChoiceFixtureCards = v2 ? entry.GetProperty("deck").EnumerateArray().Select(x => x.GetString()!).ToArray() : [];
            if (v2 && (native.ChoiceFixtureCards.Length < 6 || native.ChoiceFixtureCards.Length > 20
                || native.ChoiceFixtureCards.Any(c => c is not ("STRIKE_IRONCLAD" or "DEFEND_IRONCLAD" or "BASH" or "IRON_WAVE" or "POMMEL_STRIKE" or "TWIN_STRIKE"))))
                throw new InvalidDataException("Unaudited collection deck");
            int seed = entry.GetProperty("seed").GetInt32(), hp = entry.GetProperty("hp").GetInt32();
            string arm = entry.GetProperty("arm").GetString()!;
            string output = entry.GetProperty("output").GetString()!;
            if (arm is not ("policy" or "uct" or "puct") || hp < 1 || hp > 80 || File.Exists(output))
                throw new InvalidDataException("Unsupported pilot case or existing output");
            native.EnterRoomForVerification = async (run, encounter) =>
            {
                var player = run.Players.Single();
                foreach (var relic in player.Relics.ToArray()) player.RemoveRelicInternal(relic, silent: true);
                await CreatureCmd.SetCurrentHp(player.Creature, hp);
                await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
            };
            await native.ResetAsync($"COLLECTION-PILOT-{seed}", cancellation);
            using var env = new CombatSolverReplayEnvironment();
            env.Capture(native.CombatStateForSimulation, hp);
            Func<IReadOnlyList<CombatSolverMctsAction>, CancellationToken, Task<IReadOnlyList<double>>>? provider = arm == "puct"
                ? (actions, ct) => prior.PredictAsync(env.ExportStarterPriorObservation(hp, v2), ct) : null;
            // Warm inference in every arm; keep startup and audit outside search timing.
            await prior.PredictAsync(env.ExportStarterPriorObservation(hp, v2), cancellation);
            if (arm != "policy")
                await new ReplayMcts<CombatSolverMctsAction>(env, seed: seed, policyPrior: provider)
                    .SearchAsync([], env.RootKey, TimeSpan.FromMilliseconds(300), TimeSpan.FromMilliseconds(300), cancellation);
            var steps = new List<object>();
            var wall = Stopwatch.StartNew();
            while (!native.Terminal && steps.Count < 100 && native.Round <= 40)
            {
                await env.RestoreAsync([], cancellation);
                env.SetRootPlayerHp(native.Hp);
                var observation = env.ExportStarterPriorObservation(hp, v2);
                // Independent capture from the authoritative native world, not a second read of the same shadow.
                using (var live = new CombatSolverReplayEnvironment())
                {
                    live.Capture(native.CombatStateForSimulation, hp);
                    var liveObservation = JsonSerializer.SerializeToNode(live.ExportStarterPriorObservation(hp, v2))!;
                    // A fresh prediction capture has an empty local simulation history.
                    // Fill its two cumulative counters from independent executed inputs/native events.
                    liveObservation["decisions"] = steps.Count;
                    liveObservation["unblockedHits"] = CombatManager.Instance.History.Entries
                        .OfType<DamageReceivedEntry>().Count(e => e.Receiver.IsPlayer && e.Result.UnblockedDamage > 0);
                    if (!JsonNode.DeepEquals(JsonSerializer.SerializeToNode(observation), liveObservation))
                    {
                        File.WriteAllText(output + ".mismatch.json", JsonSerializer.Serialize(new { step = steps.Count, observation, liveObservation }));
                        throw new InvalidDataException("Native/prediction feature or legal-action mismatch");
                    }
                }
                var legal = env.LegalActions();
                CombatSolverMctsAction selected;
                var visits = legal.ToDictionary(a => a.Key, _ => 0);
                int simulations = 0;
                var timer = Stopwatch.StartNew();
                if (legal.Count == 1) selected = legal[0];
                else if (arm == "policy")
                {
                    var probabilities = await prior.PredictAsync(observation, cancellation);
                    selected = legal[Enumerable.Range(0, legal.Count).MaxBy(i => probabilities[i])];
                }
                else
                {
                    // Fresh root: visit targets describe this decision only, with no retained-label ambiguity.
                    var result = await new ReplayMcts<CombatSolverMctsAction>(env, seed: seed + steps.Count, policyPrior: provider)
                        .SearchAsync([], env.RootKey, TimeSpan.FromMilliseconds(budgetMs), TimeSpan.FromMilliseconds(budgetMs), cancellation);
                    foreach (var stat in result.Statistics) visits[stat.Action.Key] = stat.Visits;
                    simulations = result.CompletedSimulations;
                    if (simulations <= 0 || visits.Values.Sum() != simulations)
                        throw new InvalidDataException("Incomplete root visit distribution");
                    selected = result.Action;
                }
                double seconds = timer.Elapsed.TotalSeconds;
                var expected = env.PredictSuccessor(selected);
                await native.StepAsync(native.ToLiveSearchAction(selected), cancellation);
                if (!native.Terminal && expected.ContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                    throw new InvalidDataException("Full native successor continuation mismatch");
                env.Promote(selected);
                if (env.CurrentState.Terminal != native.Terminal || env.CurrentState.PlayerHp != native.Hp
                    || (native.Terminal && env.CurrentState.Won != native.Won))
                    throw new InvalidDataException("Native/simulation endpoint mismatch");
                steps.Add(new { observation, action = selected.Key, visits, simulations, seconds,
                    forced = legal.Count == 1, featureParity = true, successorParity = true,
                    terminalAfter = native.Terminal, hpAfter = native.Hp });
            }
            if (!native.Terminal) throw new InvalidDataException("Unfinished fights cannot enter pilot replay");
            var end = env.CurrentState;
            double searchReward = env.EvaluateTerminal();
            // Canonical Python V7 operation order; native rollout divides before multiplying.
            // Permit only floating-point roundoff, preserving both values as audit evidence.
            double reward = native.Won ? .9 + .1 * native.Hp / end.PlayerMaxHp : -1;
            if (!double.IsFinite(searchReward) || Math.Abs(searchReward - reward) > 1e-15)
                throw new InvalidDataException($"Native terminal reward mismatch: {searchReward:R} vs {reward:R}");
            var payload = new { format = v2 ? "native-collection-v2" : "native-collection-pilot-v1", identity, modelSha256 = prior.ModelIdentity,
                recipe = v2 ? (object)entry.GetProperty("recipe").Clone() : null,
                teacherInformation = "native_checkpoint_privileged", encounter = native.EncounterId,
                seed, initialHp = hp, arm, budgetMs, complete = true, split = entry.GetProperty("split").GetString(),
                outcome = new { won = native.Won, finalHp = native.Hp, maxHp = end.PlayerMaxHp,
                    reward, searchReward, decisions = steps.Count, turns = native.Round },
                wallSeconds = wall.Elapsed.TotalSeconds, steps };
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllText(output + ".tmp", JsonSerializer.Serialize(payload));
            File.Move(output + ".tmp", output, overwrite: false);
            Godot.GD.Print($"PILOT {arm} seed={seed} hp={hp} won={native.Won} finalHp={native.Hp} decisions={steps.Count}");
        }
        native.EnterRoomForVerification = null;
    }
}
