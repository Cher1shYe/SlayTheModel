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
internal static class GenericCollection
{
    internal static async Task RunAsync(NativeSession native, CancellationToken cancellation)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("STS2_COLLECTION_PILOT_JOB")!));
        var job = document.RootElement;
        if (job.TryGetProperty("catalogOutput", out var catalogOutput))
        {
            var catalog = new {
                cards = MegaCrit.Sts2.Core.Models.ModelDb.AllCards
                    .Where(c => c.Pool is MegaCrit.Sts2.Core.Models.CardPools.IroncladCardPool or MegaCrit.Sts2.Core.Models.CardPools.ColorlessCardPool)
                    .Select(c => new { id=c.Id.Entry, pool=c.Pool.GetType().Name,
                        multiplayerOnly=c.MultiplayerConstraint==MegaCrit.Sts2.Core.Entities.Cards.CardMultiplayerConstraint.MultiplayerOnly,
                        maxUpgradeLevel=c.MaxUpgradeLevel }).OrderBy(c=>c.id).ToArray(),
                encounters = MegaCrit.Sts2.Core.Models.ModelDb.All.OfType<MegaCrit.Sts2.Core.Models.EncounterModel>()
                    .Select(e=>new { id=e.Id.Entry, type=e.GetType().Name }).OrderBy(e=>e.id).ToArray()
            };
            File.WriteAllText(catalogOutput.GetString()!, JsonSerializer.Serialize(catalog));
            return;
        }
        if (job.GetProperty("format").GetString() != "native-generic-collection-v1") throw new InvalidDataException("Generic format required");
        string source = job.GetProperty("source").GetString()!;
        string identity = job.GetProperty("identity").GetString()!;
        int budgetMs = job.GetProperty("budgetMs").GetInt32();
        var leaf = new LeafValuePolicy(job.TryGetProperty("leafMode",out var lm) ? lm.GetString()! : "heuristic",
            job.TryGetProperty("valueMix",out var vm) ? vm.GetDouble() : .5);
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
            foreach (var token in entry.GetProperty("deck").EnumerateArray())
            {
                string id=token.GetString()!.TrimEnd('+');
                var canonical=MegaCrit.Sts2.Core.Models.ModelDb.AllCards.Single(c=>c.Id.Entry==id);
                if(canonical.MultiplayerConstraint==MegaCrit.Sts2.Core.Entities.Cards.CardMultiplayerConstraint.MultiplayerOnly)
                    throw new InvalidDataException($"Single-player collection excludes multiplayer-only card {id}");
                if(token.GetString()!.EndsWith('+') && canonical.MaxUpgradeLevel<1)
                    throw new InvalidDataException($"Card {id} cannot be upgraded");
            }
            native.EncounterId = entry.GetProperty("encounter").GetString()!;
            native.ChoiceFixture = true;
            native.ChoiceFixtureUpgradeLevels = entry.GetProperty("deck").EnumerateArray().Select(x => x.GetString()!.EndsWith('+') ? 1 : 0).ToArray();
            native.ChoiceFixtureCards = entry.GetProperty("deck").EnumerateArray().Select(x => x.GetString()!.TrimEnd('+')).ToArray();
            native.ChoiceFixtureUpgradedCards = entry.GetProperty("deck").EnumerateArray().Select(x => x.GetString()!)
                .Where(x => x.EndsWith('+')).Select(x => x.TrimEnd('+')).ToHashSet();
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
            if (job.TryGetProperty("preflightOnly", out var preflightOnly) && preflightOnly.GetBoolean())
            {
                if (!env.MatchesLiveRoot(native.CombatStateForSimulation, native.HasPendingChoice, native.ChoiceSignature))
                    throw new InvalidDataException("Preflight native/simulation root mismatch");
                var rootLegal = env.LegalActions();
                var frame = native.ExportGenericObservation(rootLegal, hp, 0);
                await prior.PredictAsync(frame, cancellation);
                if (!native.HasPendingChoice)
                    await prior.ValueAsync(env.ExportGenericValueObservation(hp, 0), cancellation, frame);
                File.WriteAllText(output, JsonSerializer.Serialize(new { preflight=true, recipe=entry.GetProperty("recipe").Clone(), legalActions=rootLegal.Count, pendingChoice=native.HasPendingChoice, observation=frame }));
                continue;
            }
            var steps = new List<object>();
            var wall = Stopwatch.StartNew();
            while (!native.Terminal && steps.Count < 100 && native.Round <= 40)
            {
                await env.RestoreAsync([], cancellation);
                env.SetRootPlayerHp(native.Hp);
                if (!env.MatchesLiveRoot(native.CombatStateForSimulation, native.HasPendingChoice, native.ChoiceSignature))
                    throw new InvalidDataException("Native/simulation root mismatch");
                var legal = env.LegalActions();
                var observation = native.ExportGenericObservation(legal, hp, steps.Count);
                if (leaf.Mode != "heuristic" && !native.HasPendingChoice)
                    await prior.ValueAsync(env.ExportGenericValueObservation(hp, steps.Count), cancellation, observation);
                var probabilities = await prior.PredictAsync(observation, cancellation);
                string decisionRoot = env.StateKey();
                var rootPriors = legal.Select((a, i) => (a.Key, Probability: probabilities[i])).ToDictionary(a => a.Key, a => a.Probability);
                Func<IReadOnlyList<CombatSolverMctsAction>, CancellationToken, Task<IReadOnlyList<double>>>? provider = arm == "puct"
                    ? (actions, ct) => Task.FromResult<IReadOnlyList<double>>(env.StateKey() == decisionRoot
                        ? actions.Select(a => rootPriors[a.Key]).ToArray()
                        : actions.Select(_ => 1d / actions.Count).ToArray()) : null;
                CombatSolverMctsAction selected;
                var visits = legal.ToDictionary(a => a.Key, _ => 0);
                int simulations = 0;
                int valueCalls=0,leafBackups=0,terminalBackups=0; double valueSum=0, heuristicSum=0, evaluatedValueSum=0, meanBackupDepth=0;
                Func<int,CancellationToken,Task<double>>? evaluator = leaf.Mode == "heuristic" ? null : async (depth,ct) => {
                    string branchBefore=env.CurrentContinuationKey;
                    double heuristic=env.EvaluateCutoff();
                    double learned=await prior.ValueAsync(env.ExportGenericValueObservation(hp,steps.Count+depth),ct);
                    if(branchBefore!=env.CurrentContinuationKey) throw new InvalidDataException("Value projection mutated its branch");
                    double combined=leaf.Combine(heuristic,learned);
                    valueCalls++; valueSum+=learned; heuristicSum+=heuristic; evaluatedValueSum+=combined;
                    return combined;
                };
                var timer = Stopwatch.StartNew();
                string? liveBefore = native.HasPendingChoice ? null : NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation);
                if (legal.Count == 1) selected = legal[0];
                else if (arm == "policy")
                {
                    selected = legal[Enumerable.Range(0, legal.Count).MaxBy(i => probabilities[i])];
                }
                else
                {
                    // Fresh root: visit targets describe this decision only, with no retained-label ambiguity.
                    var result = await new ReplayMcts<CombatSolverMctsAction>(env, seed: seed + steps.Count, policyPrior: provider, leafValue:evaluator)
                        .SearchAsync([], env.RootKey, TimeSpan.FromMilliseconds(budgetMs), TimeSpan.FromMilliseconds(budgetMs), cancellation);
                    foreach (var stat in result.Statistics) visits[stat.Action.Key] = stat.Visits;
                    simulations = result.CompletedSimulations;
                    leafBackups=result.LeafBackups; terminalBackups=result.TerminalBackups; meanBackupDepth=result.MeanBackupDepth;
                    if (simulations <= 0 || visits.Values.Sum() != simulations)
                        throw new InvalidDataException("Incomplete root visit distribution");
                    selected = result.Action;
                }
                double seconds = timer.Elapsed.TotalSeconds;
                if(liveBefore!=null && liveBefore!=NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                    throw new InvalidDataException("Search mutated live root");
                var liveAction = native.ToLiveSearchAction(selected);
                env.Promote(selected);
                await native.StepAsync(liveAction, cancellation);
                // Native card commands can automatically resolve a forced selection.
                // The simulation API still represents it as a sole choice edge.
                // Consume only unique choices when live has already continued, then
                // require the entire resulting continuation to match independently.
                int automaticForcedChoices = 0;
                while (!native.HasPendingChoice && env.CurrentState.PendingChoice
                    && env.LegalActions() is { Count: 1 } automatic
                    && automatic[0].Native.SelectedCards is not null)
                {
                    if (++automaticForcedChoices > 16) throw new InvalidDataException("Automatic forced-choice loop");
                    env.Promote(automatic[0]);
                }
                if (!native.Terminal && !native.HasPendingChoice && env.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                {
                    File.WriteAllText(output + ".predicted.txt", env.CurrentContinuationStateText);
                    File.WriteAllText(output + ".live.txt", NativeMctsSimulationApi.CaptureLiveContinuationStateText(native.CombatStateForSimulation));
                    File.WriteAllText(output + ".failure.json", JsonSerializer.Serialize(new {
                        recipe=entry.GetProperty("recipe").Clone(),steps,observation,action=selected.Key,
                        liveExhausts=CombatManager.Instance.History.Entries.OfType<CardExhaustedEntry>()
                            .Select(e=>new {card=e.Card.Id.Entry,thisTurn=e.HappenedThisTurn(native.CombatStateForSimulation)}).ToArray() }));
                    throw new InvalidDataException($"Full native successor continuation mismatch: seed={seed} decision={steps.Count} action={selected.Key}");
                }
                if (native.HasPendingChoice && !env.MatchesLiveRoot(native.CombatStateForSimulation, true, native.ChoiceSignature))
                    throw new InvalidDataException("Native selector mismatch");
                string successorParityScope;
                try
                {
                    successorParityScope=CollectionEndpointContract.Validate(env.CurrentState.PendingChoice,native.HasPendingChoice,
                        env.CurrentState.Terminal,native.Terminal,env.CurrentState.PlayerHp,native.Hp,env.CurrentState.Won,native.Won);
                }
                catch (InvalidDataException error)
                {
                    File.WriteAllText(output+".failure.json",JsonSerializer.Serialize(new {
                        recipe=entry.GetProperty("recipe").Clone(),steps,observation,action=selected.Key,
                        predicted=env.CurrentState,
                        actual=new {terminal=native.Terminal,hp=native.Hp,won=native.Won,round=native.Round} }));
                    throw new InvalidDataException($"Endpoint contract at decision={steps.Count} action={selected.Key}",error);
                }
                steps.Add(new { observation, action = selected.Key, visits, simulations, seconds,
                    leafDiagnostics=new { valueCalls,valueSum,heuristicSum,evaluatedValueSum,leafBackups,terminalBackups,meanBackupDepth },
                    forced = legal.Count == 1, automaticForcedChoices, featureParity = true, successorParity = true, successorParityScope,
                    terminalAfter = native.Terminal, hpAfter = native.Hp });
            }
            bool truncated = !native.Terminal;
            var end = env.CurrentState;
            double cutoffRisk = end.PendingChoice ? 1d : Math.Clamp((double)end.IncomingDamage / Math.Max(1,native.Hp),0,1);
            double cutoffDamage = env.EnemyDamageFraction;
            double searchReward = truncated
                ? CombatRolloutReward.Evaluate(false,false,native.Hp,end.PlayerMaxHp,hp,cutoffDamage,cutoffRisk*native.Hp)
                : env.EvaluateTerminal();
            // Canonical Python V7 operation order; native rollout divides before multiplying.
            // Permit only floating-point roundoff, preserving both values as audit evidence.
            double reward = truncated ? searchReward : native.Won ? .9 + .1 * native.Hp / end.PlayerMaxHp : -1;
            if (!double.IsFinite(searchReward) || Math.Abs(searchReward - reward) > 1e-15)
                throw new InvalidDataException($"Native terminal reward mismatch: {searchReward:R} vs {reward:R}");
            var payload = new { format = "native-generic-collection-v1", identity, modelSha256 = prior.ModelIdentity,
                recipe = entry.GetProperty("recipe").Clone(), searchMode = leaf.Mode == "heuristic" ? "root-prior-uniform-tree-rollout-v1" : "root-prior-uniform-tree-leaf-v1",
                leafMode=leaf.Mode,valueMix=leaf.Mix,
                teacherInformation = "native_checkpoint_privileged", encounter = native.EncounterId,
                seed, initialHp = hp, arm, budgetMs, complete = !truncated, split = entry.GetProperty("split").GetString(),
                outcome = new { won = native.Won, finalHp = native.Hp, maxHp = end.PlayerMaxHp,
                    reward, searchReward, decisions = steps.Count, turns = native.Round,
                    terminationReason = truncated ? "time_limit" : native.Won ? "win" : "death",
                    cutoff = truncated ? (object)new { damage=cutoffDamage, risk=cutoffRisk, pendingChoice=native.HasPendingChoice } : null },
                wallSeconds = wall.Elapsed.TotalSeconds, steps };
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllText(output + ".tmp", JsonSerializer.Serialize(payload));
            File.Move(output + ".tmp", output, overwrite: false);
            Godot.GD.Print($"PILOT {arm} seed={seed} hp={hp} won={native.Won} finalHp={native.Hp} decisions={steps.Count}");
        }
        native.EnterRoomForVerification = null;
        native.ChoiceFixtureUpgradedCards.Clear();
    }
}
