using System.Text.Json;
using CombatSolver.Api;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;

public static class CombatSolverMctsBenchmark
{
    private static readonly string[] Encounters =
    [
        "FUZZY_WURM_CRAWLER_WEAK",
        "CULTISTS_NORMAL",
        "LIVING_FOG_NORMAL",
        "PHROG_PARASITE_ELITE",
        "KAISER_CRAB_BOSS",
    ];

    public static async Task RunAsync(
        NativeSession native,
        string outputPath,
        CancellationToken cancellation)
    {
        var results = new List<object>();
        foreach (string encounter in Encounters)
        {
            native.Checkpoint = null;
            native.ChoiceFixture = false;
            native.EncounterId = encounter;
            native.Seed = "MCTS-SIM-" + encounter;
            await native.ResetAsync(native.Seed, cancellation);

            // One warm-up run is deliberately excluded from the five formal samples.
            await RunTrial(native, TimeSpan.FromSeconds(1), cancellation);
            var samples = new List<object>();
            var rates = new List<double>();
            string? error = null;
            for (int sample = 0; sample < 5; sample++)
            {
                try
                {
                    var result = await RunTrial(native, TimeSpan.FromSeconds(5), cancellation);
                    double rate = result.CompletedSimulations / (result.ElapsedMilliseconds / 1000d);
                    rates.Add(rate);
                    samples.Add(new
                    {
                        sample,
                        result.CompletedSimulations,
                        result.ElapsedMilliseconds,
                        simulationsPerSecond = rate,
                        result.RetainedVisits,
                    });
                }
                catch (Exception exception) when (exception is not OperationCanceledException)
                {
                    error = exception.ToString();
                    break;
                }
            }
            rates.Sort();
            results.Add(new
            {
                encounter,
                samples,
                median = rates.Count == 0 ? 0 : rates[rates.Count / 2],
                minimum = rates.Count == 0 ? 0 : rates[0],
                maximum = rates.Count == 0 ? 0 : rates[^1],
                stable = rates.Count == 5 && rates[0] >= 90,
                passed100 = rates.Count == 5 && rates[rates.Count / 2] >= 100,
                error,
            });
            Godot.GD.Print($"SLAY_WORKER_SOLVER_MCTS_BENCHMARK encounter={encounter} "
                + $"median={(rates.Count == 0 ? 0 : rates[rates.Count / 2]):F2} "
                + $"min={(rates.Count == 0 ? 0 : rates[0]):F2} error={(error == null ? "none" : "yes")}");
        }

        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        File.WriteAllText(outputPath, JsonSerializer.Serialize(new
        {
            generatedAtUtc = DateTimeOffset.UtcNow,
            backend = "ReplayMcts+CombatSolver",
            maxDepth = 200,
            sampleSeconds = 5,
            samplesPerEncounter = 5,
            results,
        }, new JsonSerializerOptions { WriteIndented = true }));
    }

    public static async Task ExportTrajectoryAsync(
        NativeSession native, string outputPath, int budgetMilliseconds,
        CancellationToken cancellation)
    {
        if (budgetMilliseconds < 50) throw new ArgumentOutOfRangeException(nameof(budgetMilliseconds));
        native.Checkpoint = null;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        await using var writer = new StreamWriter(outputPath, false);
        var pending = new List<ExportedDecision>();
        var maxDecisions = int.TryParse(Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_DECISIONS"), out var parsedMax)
            ? Math.Max(1, parsedMax) : 256;
        for (var decision = 0; decision < maxDecisions && !native.Terminal; decision++)
        {
            cancellation.ThrowIfCancellationRequested();
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(native.CombatStateForSimulation, native.EntryHp);
            var decisionPoint = CombatCaptureService.BuildDecisionPoint(native.CombatStateForSimulation, decision);
            var rootKey = environment.RootKey;
            var legal = environment.RootActions.ToArray();
            var legalIds = legal.Select(action => TrainingActionId(action.Native)).ToArray();
            if (legalIds.Length == 0 || legalIds.Distinct(StringComparer.Ordinal).Count() != legalIds.Length)
                throw new InvalidDataException($"Root {rootKey} has an empty or duplicate legal action set.");
            var tree = new ReplayMcts<CombatSolverMctsAction>(environment, seed: 20260922 + decision);
            var budget = TimeSpan.FromMilliseconds(budgetMilliseconds);
            var result = await tree.SearchAsync([], environment.RootKey, budget, budget, cancellation);
            var stats = result.Statistics.ToArray();
            var rootSet = legalIds.ToHashSet(StringComparer.Ordinal);
            var statIds = stats.Select(item => TrainingActionId(item.Action.Native)).ToArray();
            if (!rootSet.Contains(TrainingActionId(result.Action.Native))
                || statIds.Any(id => !rootSet.Contains(id))
                || stats.Any(item => item.Visits <= 0)
                || stats.Sum(item => item.Visits) <= 0)
            {
                var diagnosticPath = outputPath + ".diagnostic.json";
                File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
                {
                    seed = native.Seed, decision, rootKey,
                    legalIds, selected = TrainingActionId(result.Action.Native), statIds,
                    visits = stats.Select(item => item.Visits).ToArray(),
                    result.CompletedSimulations, result.ElapsedMilliseconds,
                    environment.CurrentContinuationKey,
                    environment.CurrentContinuationStateText,
                }, new JsonSerializerOptions { WriteIndented = true }));
                throw new InvalidDataException($"MCTS root statistics mismatch at decision {decision}; diagnostic={diagnosticPath}");
            }
            var visits = new Dictionary<string, int>(StringComparer.Ordinal);
            foreach (var item in stats)
            {
                string statId = TrainingActionId(item.Action.Native);
                if (!visits.TryAdd(statId, item.Visits))
                    throw new InvalidDataException($"Duplicate root action statistic {statId}.");
            }
            pending.Add(new ExportedDecision(
                native.Seed, decision, decisionPoint.Observation, rootKey,
                legal.Select(action => new ExportedAction(
                    action.Native.Kind switch
                    {
                        "PlayCard" => "PlayCard", "UsePotion" => "UsePotion", "EndTurn" => "EndTurn", _ => "NestedChoice",
                    }, TrainingActionId(action.Native), action.Native.Kind == "EndTurn", action.Native)).ToArray(),
                visits, result.CompletedSimulations));
            try
            {
                var liveAction = native.ToLiveSearchAction(result.Action);
                environment.Promote(result.Action);
                await native.StepAsync(liveAction, cancellation);
                while (native.HasPendingChoice)
                {
                    // Preserve the suspended parent context; never capture mid-action.
                    var choiceEnvironment = environment;
                    await choiceEnvironment.RestoreAsync([], cancellation);
                    var choiceActions = choiceEnvironment.LegalActions();
                    if (!choiceEnvironment.State.PendingChoice || choiceActions.Count == 0 || choiceActions.Any(action => action.Native.ChoiceKey == null))
                        throw new InvalidDataException("Live pending choice has no corresponding native choice actions.");
                    if (choiceEnvironment.ChoiceSignature != native.ChoiceSignature)
                        throw new InvalidDataException($"Choice boundaries differ: predicted={choiceEnvironment.ChoiceSignature} live={native.ChoiceSignature}");
                    native.ValidateSimulationActions(choiceActions);
                    var choiceObservation = CombatCaptureService.BuildDecisionPoint(native.CombatStateForSimulation, pending.Count).Observation;
                    var choiceTree = new ReplayMcts<CombatSolverMctsAction>(choiceEnvironment, seed: 20260922 + decision + 10000);
                    var choiceResult = await choiceTree.SearchAsync([], choiceEnvironment.RootKey, budget, budget, cancellation);
                    var selectedChoice = choiceActions.SingleOrDefault(action => action.Key == choiceResult.Action.Key)
                        ?? throw new InvalidDataException($"Choice result {choiceResult.Action.Key} is not in the pending root action set.");
                    var choiceLegal = choiceActions.ToArray();
                    var choiceIds = choiceLegal.Select(action => TrainingActionId(action.Native)).ToHashSet(StringComparer.Ordinal);
                    var choiceStats = choiceResult.Statistics.ToArray();
                    if (!choiceIds.Contains(TrainingActionId(choiceResult.Action.Native))
                        || choiceStats.Any(item => !choiceIds.Contains(TrainingActionId(item.Action.Native)))
                        || choiceStats.Any(item => item.Visits <= 0)
                        || choiceStats.Sum(item => item.Visits) <= 0)
                        throw new InvalidDataException("Pending choice statistics do not match its root legal action set.");
                    pending.Add(new ExportedDecision(
                        native.Seed, decision, choiceObservation,
                        choiceEnvironment.RootKey,
                        choiceLegal.Select(action => new ExportedAction("NestedChoice", TrainingActionId(action.Native), false, action.Native)).ToArray(),
                        choiceStats.ToDictionary(item => TrainingActionId(item.Action.Native), item => item.Visits, StringComparer.Ordinal),
                        choiceResult.CompletedSimulations));
                    var liveChoice = native.ToLiveSearchAction(selectedChoice);
                    choiceEnvironment.Promote(selectedChoice);
                    await native.StepAsync(liveChoice, cancellation);
                }
                // The native game resolves forced selections without opening a selector
                // (e.g. Headbutt with a single discarded card). They are not decisions.
                bool advancedForcedChoice = false;
                while (environment.State.PendingChoice)
                {
                    var forced = environment.RootActions;
                    if (forced.Count != 1 || forced[0].Native.ChoiceKey == null)
                        throw new InvalidDataException("Prediction requires a non-forced choice after live execution completed.");
                    environment.Promote(forced[0]);
                    advancedForcedChoice = true;
                }
                if (advancedForcedChoice && !native.Terminal
                    && environment.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(native.CombatStateForSimulation))
                    throw new InvalidDataException("Forced choice continuation differs from live state.");
            }
            catch (Exception exception)
            {
                string diagnosticPath = outputPath + ".live-action-diagnostic.json";
                File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
                {
                    seed = native.Seed,
                    decision,
                    decisionType = environment.State.PendingChoice ? "pending-choice" : "combat-action",
                    rawAction = result.Action.Native,
                    choiceDiagnostics = environment.ChoiceDiagnostics,
                    livePending = native.HasPendingChoice,
                    liveChoiceSignature = native.ChoiceSignature,
                    liveLegalActions = native.ActionsForDiagnostics(),
                    exception = exception.ToString(),
                    observation = decisionPoint.Observation,
                    legalActions = legal,
                }, new JsonSerializerOptions { WriteIndented = true }));
                throw new InvalidDataException($"Live action conversion failed at decision {decision}; diagnostic={diagnosticPath}", exception);
            }
        }
        bool resolved = native.Terminal;
        double value = resolved ? native.EvaluateTerminal() : native.EvaluateUnresolved();
        string outcome = resolved ? (native.Won ? "win" : "loss") : "unresolved";
        var provenance = new
        {
            seed = native.Seed,
            encounter = native.EncounterId,
            choiceFixture = native.ChoiceFixture,
            fixtureCards = native.ChoiceFixture ? native.ChoiceFixtureCards : null,
            budgetMilliseconds,
            maxDecisions,
            terminal = resolved,
            playerHp = native.Hp,
            initialEnemyEffectiveHp = native.InitialEnemyEffectiveHp,
            enemyDamageLost = native.EnemyDamageLost,
            assemblies = AssemblyProvenance(),
        };
        foreach (var item in pending)
        {
            var payload = new
            {
                schemaVersion = 1, seed = item.Seed, startType = "full_combat",
                observation = item.Observation,
                legalActions = item.LegalActions,
                visitPolicy = item.VisitPolicy,
                valueTarget = value, outcome,
                simulations = item.Simulations, stateKey = item.RootKey, provenance,
            };
            await writer.WriteLineAsync(JsonSerializer.Serialize(payload));
        }
        await writer.FlushAsync(cancellation);
    }

    private static object AssemblyProvenance()
        => new
        {
            nativeWorker = AssemblyIdentity(typeof(Worker).Assembly),
            search = AssemblyIdentity(typeof(SlayTheModel.Search.ReplayMcts<>).Assembly),
            combatSolver = AssemblyIdentity(typeof(NativeMctsSimulationApi).Assembly),
        };

    private static object AssemblyIdentity(System.Reflection.Assembly assembly)
    {
        string path = assembly.Location;
        return new
        {
            path,
            mvid = assembly.ManifestModule.ModuleVersionId,
            sha256 = File.Exists(path) ? Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path))) : "<missing>",
        };
    }

    private sealed record ExportedAction(string kind, string actionId, bool terminal, NativeMctsAction payload);
    private sealed record ExportedDecision(string Seed, int Decision, object Observation, string RootKey,
        IReadOnlyList<ExportedAction> LegalActions, IReadOnlyDictionary<string, int> VisitPolicy, int Simulations);
    private static string TrainingActionId(NativeMctsAction action)
        => action.Key;

    private static async Task<TimedSearchResult<CombatSolverMctsAction>> RunTrial(
        NativeSession native,
        TimeSpan budget,
        CancellationToken cancellation)
    {
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(native.CombatStateForSimulation, native.EntryHp);
        var tree = new ReplayMcts<CombatSolverMctsAction>(environment, seed: 20260922);
        return await tree.SearchAsync([], environment.RootKey, budget, budget, cancellation, maxDepth: 200);
    }
}
