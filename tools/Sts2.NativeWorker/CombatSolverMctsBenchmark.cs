using System.Text.Json;
using System.Diagnostics;
using CombatSolver.Api;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

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
        CancellationToken cancellation, string startType = "full_combat", object? startProvenance = null)
    {
        if (budgetMilliseconds < 50) throw new ArgumentOutOfRangeException(nameof(budgetMilliseconds));
        if (startType is not ("full_combat" or "mid_combat_verified"))
            throw new ArgumentOutOfRangeException(nameof(startType));
        native.Checkpoint = null;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        using var model = AlphaZeroOnnxEvaluator.TryLoad(
            Environment.GetEnvironmentVariable("STS2_ALPHAZERO_ONNX_MODEL"), out var modelLoadStatus);
        var modelShadow = string.Equals(Environment.GetEnvironmentVariable("STS2_ALPHAZERO_SHADOW"), "1", StringComparison.Ordinal);
        var treeMode = model != null && string.Equals(
            Environment.GetEnvironmentVariable("STS2_ALPHAZERO_SEARCH_MODE"),
            "policy-value-tree-v1", StringComparison.Ordinal);
        Godot.GD.Print("SLAY_WORKER_ALPHAZERO " + modelLoadStatus);
        var modelUsed = 0;
        var modelScored = 0;
        var modelFallbacks = 0;
        var forcedFixtureCard = Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_FORCE_CARD");
        if (forcedFixtureCard != null && (string.IsNullOrWhiteSpace(forcedFixtureCard)
                || !native.ChoiceFixture || startType != "full_combat" || model != null))
            throw new InvalidDataException("Forced-card regression requires a full-combat choice fixture without a model.");
        bool forcedFixtureChoiceObserved = false;
        await using var writer = new StreamWriter(outputPath, false);
        var pending = new List<ExportedDecision>();
        var maxDecisions = int.TryParse(Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_DECISIONS"), out var parsedMax)
            ? Math.Max(1, parsedMax) : 256;
        int? maxSimulations = int.TryParse(Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_SIMULATIONS"), out var parsedSimulations)
            ? Math.Max(1, parsedSimulations) : null;
        for (var decision = 0; decision < maxDecisions && !native.Terminal; decision++)
        {
            cancellation.ThrowIfCancellationRequested();
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(native.CombatStateForSimulation, native.EntryHp);
            var decisionPoint = CombatCaptureService.BuildDecisionPoint(native.CombatStateForSimulation, decision);
            RequirePublicPolicyObservation(decisionPoint.Observation, outputPath, native.Seed, decision);
            var predictedObservation = environment.ObserveCurrent();
            RequirePublicPolicyObservation(predictedObservation, outputPath, native.Seed, decision);
            if (!string.Equals(JsonSerializer.Serialize(decisionPoint.Observation),
                    JsonSerializer.Serialize(predictedObservation), StringComparison.Ordinal))
            {
                string diagnosticPath = outputPath + ".prediction-observation-diagnostic.json";
                File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
                {
                    seed = native.Seed, decision, rootKey = environment.RootKey,
                    live = decisionPoint.Observation, predicted = predictedObservation,
                }, new JsonSerializerOptions { WriteIndented = true }));
                throw new InvalidDataException(
                    $"Live/predicted root policy observations differ; diagnostic={diagnosticPath}");
            }
            var rootKey = environment.RootKey;
            var legal = environment.RootActions.ToArray();
            var legalIds = legal.Select(action => TrainingActionId(action.Native)).ToArray();
            if (legalIds.Length == 0 || legalIds.Distinct(StringComparer.Ordinal).Count() != legalIds.Length)
                throw new InvalidDataException($"Root {rootKey} has an empty or duplicate legal action set.");
            var tree = new ReplayMcts<CombatSolverMctsAction>(environment, seed: 20260922 + decision);
            var budget = TimeSpan.FromMilliseconds(budgetMilliseconds);
            var decisionWatch = Stopwatch.StartNew();
            var search = await SearchRootAsync(environment, tree, treeMode ? model : null,
                budget, 20260922 + decision, cancellation, maxSimulations);
            await VerifyObservationRestorationAsync(environment, predictedObservation, legal, cancellation);
            var stats = search.Statistics.ToArray();
            var rootSet = legalIds.ToHashSet(StringComparer.Ordinal);
            var statIds = stats.Select(item => TrainingActionId(item.Action.Native)).ToArray();
            if (!rootSet.Contains(TrainingActionId(search.Action.Native))
                || statIds.Any(id => !rootSet.Contains(id))
                || stats.Any(item => item.Visits <= 0)
                || stats.Sum(item => item.Visits) <= 0)
            {
                var diagnosticPath = outputPath + ".diagnostic.json";
                File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
                {
                    seed = native.Seed, decision, rootKey,
                    legalIds, selected = TrainingActionId(search.Action.Native), statIds,
                    visits = stats.Select(item => item.Visits).ToArray(),
                    search.Simulations, search.ElapsedMilliseconds,
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
            var selectedAction = search.Action;
            modelFallbacks += search.NetworkFallbacks;
            modelScored += search.NetworkPriorCalls;
            modelUsed += search.NetworkValueCalls;
            if (!treeMode && model != null)
            {
                var visitedKeys = stats.Select(item => item.Action.Key).ToHashSet(StringComparer.Ordinal);
                var candidates = legal.Where(action => visitedKeys.Contains(action.Key)).ToArray();
                if (model.TryChoose(decisionPoint.Observation, candidates, out var modelAction, out var predictedValue, out var modelStatus))
                {
                    modelScored++;
                    if (!modelShadow) { selectedAction = modelAction!; modelUsed++; }
                    Godot.GD.Print($"SLAY_WORKER_ALPHAZERO decision={decision} shadow={modelShadow} {modelStatus} value={predictedValue:F6}");
                }
                else
                {
                    modelFallbacks++;
                    Godot.GD.PrintErr($"SLAY_WORKER_ALPHAZERO decision={decision} {modelStatus}");
                }
            }
            // Regression setup only, never a production decision or a search fallback.
            // Keep the unmodified MCTS statistics; mark the whole trajectory non-training.
            if (decision == 0 && forcedFixtureCard != null)
            {
                var forced = legal.Where(action => action.Native.Kind == "PlayCard"
                    && action.Native.CardId == forcedFixtureCard).ToArray();
                if (forced.Length != 1)
                    throw new InvalidDataException($"Fixture card {forcedFixtureCard} must identify exactly one legal action; found {forced.Length}.");
                selectedAction = forced[0];
                Godot.GD.Print($"SLAY_WORKER_EXPORT_FORCE_CARD card={forcedFixtureCard} action={selectedAction.Key}");
            }
            await WaitForDecisionBudgetAsync(decisionWatch, budget, cancellation);
            pending.Add(new ExportedDecision(
                native.Seed, decision, decisionPoint.Observation, rootKey,
                legal.Select(action => new ExportedAction(
                    action.Native.Kind switch
                    {
                        "PlayCard" => "PlayCard", "UsePotion" => "UsePotion", "EndTurn" => "EndTurn", _ => "NestedChoice",
                    }, TrainingActionId(action.Native), action.Native.Kind == "EndTurn", action.Native)).ToArray(),
                visits, search.Simulations, decisionWatch.Elapsed.TotalMilliseconds,
                0, null, TrainingActionId(selectedAction.Native), search.NetworkPriorCalls,
                search.NetworkValueCalls, search.NetworkFallbacks));
            try
            {
                var liveAction = native.ToLiveSearchAction(selectedAction);
                environment.Promote(selectedAction);
                await native.StepAsync(liveAction, cancellation);
                int choiceLayer = 0;
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
                    RequirePublicPolicyObservation(choiceObservation, outputPath, native.Seed, decision);
                    NativeMctsChoiceFrame frame;
                    try
                    {
                        frame = choiceEnvironment.CurrentChoiceFrame;
                        native.ValidateChoiceFrame(frame);
                        if (frame.TriggerCardId != selectedAction.Native.CardId)
                            throw new InvalidDataException("Choice trigger differs from the executed parent card.");
                        if (!string.Equals(JsonSerializer.Serialize(choiceObservation),
                                JsonSerializer.Serialize(frame.Observation), StringComparison.Ordinal))
                            throw new InvalidDataException("Live/predicted pre-selection policy observations differ.");
                        var choiceContext = new CombatChoiceObservation(
                            frame.TriggerCardId, frame.Effect, frame.SourcePile,
                            frame.MinCount, frame.MaxCount, frame.Ordered,
                            frame.Candidates.Select(candidate => new CombatChoiceCandidateObservation(
                                candidate.CombatCardIndex, candidate.ModelId, candidate.UpgradeLevel)).ToArray(),
                            frame.CompletedSelections);
                        choiceObservation = choiceObservation with { Choice = choiceContext };
                        choiceObservation.Validate();
                        if (decision == 0 && forcedFixtureCard != null)
                            forcedFixtureChoiceObserved = true;
                    }
                    catch (Exception error)
                    {
                        string diagnosticPath = outputPath + ".choice-observation-diagnostic.json";
                        File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
                        {
                            seed = native.Seed, decision, choiceLayer,
                            rootKey = choiceEnvironment.RootKey,
                            liveObservation = choiceObservation,
                            predictionDiagnostics = choiceEnvironment.ChoiceDiagnostics,
                            liveChoiceSignature = native.ChoiceSignature,
                            error = error.ToString(),
                        }, new JsonSerializerOptions { WriteIndented = true }));
                        throw new InvalidDataException(
                            $"Choice observation context differs; diagnostic={diagnosticPath}", error);
                    }
                    var choiceTree = new ReplayMcts<CombatSolverMctsAction>(choiceEnvironment, seed: 20260922 + decision + 10000);
                    var choiceWatch = Stopwatch.StartNew();
                    var choiceSearch = await SearchRootAsync(choiceEnvironment, choiceTree, treeMode ? model : null,
                        budget, 20260922 + decision + 10000, cancellation, maxSimulations);
                    var selectedChoice = choiceActions.SingleOrDefault(action => action.Key == choiceSearch.Action.Key)
                        ?? throw new InvalidDataException($"Choice result {choiceSearch.Action.Key} is not in the pending root action set.");
                    var choiceLegal = choiceActions.ToArray();
                    var choiceIds = choiceLegal.Select(action => TrainingActionId(action.Native)).ToHashSet(StringComparer.Ordinal);
                    var choiceStats = choiceSearch.Statistics.ToArray();
                    if (!choiceIds.Contains(TrainingActionId(choiceSearch.Action.Native))
                        || choiceStats.Any(item => !choiceIds.Contains(TrainingActionId(item.Action.Native)))
                        || choiceStats.Any(item => item.Visits <= 0)
                        || choiceStats.Sum(item => item.Visits) <= 0)
                        throw new InvalidDataException("Pending choice statistics do not match its root legal action set.");
                    if (!treeMode && model != null)
                    {
                        var visitedChoiceKeys = choiceStats.Select(item => item.Action.Key).ToHashSet(StringComparer.Ordinal);
                        var candidates = choiceLegal.Where(action => visitedChoiceKeys.Contains(action.Key)).ToArray();
                        if (model.TryChoose(choiceObservation, candidates, out var modelChoice, out var predictedValue, out var modelStatus))
                        {
                            modelScored++;
                            if (!modelShadow) { selectedChoice = modelChoice!; modelUsed++; }
                            Godot.GD.Print($"SLAY_WORKER_ALPHAZERO decision={decision} choice shadow={modelShadow} {modelStatus} value={predictedValue:F6}");
                        }
                        else
                        {
                            modelFallbacks++;
                            Godot.GD.PrintErr($"SLAY_WORKER_ALPHAZERO decision={decision} choice {modelStatus}");
                        }
                    }
                    await WaitForDecisionBudgetAsync(choiceWatch, budget, cancellation);
                    choiceLayer++;
                    pending.Add(new ExportedDecision(
                        native.Seed, decision, choiceObservation,
                        choiceEnvironment.RootKey,
                        choiceLegal.Select(action => new ExportedAction("NestedChoice", TrainingActionId(action.Native), false, action.Native)).ToArray(),
                        choiceStats.ToDictionary(item => TrainingActionId(item.Action.Native), item => item.Visits, StringComparer.Ordinal),
                        choiceSearch.Simulations, choiceWatch.Elapsed.TotalMilliseconds,
                        choiceLayer, TrainingActionId(selectedAction.Native), TrainingActionId(selectedChoice.Native),
                        choiceSearch.NetworkPriorCalls, choiceSearch.NetworkValueCalls, choiceSearch.NetworkFallbacks));
                    modelFallbacks += choiceSearch.NetworkFallbacks;
                    modelScored += choiceSearch.NetworkPriorCalls;
                    modelUsed += choiceSearch.NetworkValueCalls;
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
                if ((advancedForcedChoice || (decision == 0 && forcedFixtureCard != null)) && !native.Terminal
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
                    rawAction = selectedAction.Native,
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
        if (forcedFixtureCard != null && !forcedFixtureChoiceObserved)
            throw new InvalidDataException("Forced-card regression did not observe and validate a live selection boundary.");
        bool resolved = native.Terminal;
        double value = resolved ? native.EvaluateTerminal() : native.EvaluateUnresolved();
        string outcome = resolved ? (native.Won ? "win" : "loss") : "unresolved";
        var provenance = new
        {
            seed = native.Seed,
            encounter = native.EncounterId,
            choiceFixture = native.ChoiceFixture,
            fixtureCards = native.ChoiceFixture ? native.ChoiceFixtureCards : null,
            regressionOnly = forcedFixtureCard != null,
            forcedFixtureCard,
            forcedFixtureChoiceObserved,
            budgetMilliseconds,
            maxDecisions,
            maxSimulations,
            terminal = resolved,
            entryHp = native.EntryHp,
            playerHp = native.Hp,
            initialEnemyEffectiveHp = native.InitialEnemyEffectiveHp,
            enemyDamageLost = native.EnemyDamageLost,
            startProvenance,
            modelLoadStatus,
            searchMode = treeMode ? "policy-value-tree-v1" : model == null ? "pure-mcts" : modelShadow ? "shadow-post-mcts" : "post-mcts-rerank",
            modelShadow,
            modelScored,
            modelUsed,
            modelFallbacks,
            decisionMetrics = pending.Select(item => new {
                parentDecision = item.Decision,
                choiceLayer = item.ChoiceLayer,
                parentActionId = item.ParentActionId,
                selectedActionId = item.SelectedActionId,
                networkPriorCalls = item.NetworkPriorCalls,
                networkValueCalls = item.NetworkValueCalls,
                networkFallbacks = item.NetworkFallbacks,
                stateKey = item.RootKey,
                simulations = item.Simulations,
                elapsedMilliseconds = item.ElapsedMilliseconds,
            }).ToArray(),
            assemblies = AssemblyProvenance(),
        };
        foreach (var item in pending)
        {
            var payload = new
            {
                schemaVersion = 1, seed = item.Seed, startType,
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

    private static async Task VerifyObservationRestorationAsync(
        CombatSolverReplayEnvironment environment,
        SlayTheModel.Sts2.Protocol.CombatObservation frozenRoot,
        IReadOnlyList<CombatSolverMctsAction> legal,
        CancellationToken cancellation)
    {
        string expected = JsonSerializer.Serialize(frozenRoot);
        async Task AssertRestoredAsync()
        {
            await environment.RestoreAsync([], cancellation);
            if (environment.State.Key != environment.RootKey
                || !string.Equals(expected, JsonSerializer.Serialize(environment.ObserveCurrent()),
                    StringComparison.Ordinal))
                throw new InvalidDataException("Root policy observation changed after rollout/branch replay.");
        }
        await AssertRestoredAsync();
        // Sample two distinct sibling continuations; their state must never be
        // reused as the observation of their common parent.
        foreach (var sibling in legal.Where(action => action.Native.Kind == "PlayCard").Take(2))
        {
            await environment.ApplyAsync(sibling, cancellation);
            if (!environment.State.PendingChoice && !environment.State.Terminal)
                _ = environment.ObserveCurrent();
            await AssertRestoredAsync();
        }
    }

    private static void RequirePublicPolicyObservation(
        SlayTheModel.Sts2.Protocol.CombatObservation observation, string outputPath, string seed, int decision)
    {
        // The current v1 capture serializes the draw pile in simulator order.
        // Until a versioned public-information projection exists, fail before
        // persisting a sample, including at pending choice boundaries.
        var hiddenDrawPiles = observation.Players.SelectMany(player => player.Piles)
            .Where(pile => string.Equals(pile.PileType, "Draw", StringComparison.OrdinalIgnoreCase)
                && pile.Cards.Count > 0).ToArray();
        if (hiddenDrawPiles.Length == 0) return;
        string diagnosticPath = outputPath + ".policy-observation-diagnostic.json";
        File.WriteAllText(diagnosticPath, JsonSerializer.Serialize(new
        {
            seed, decision, reason = "hidden-draw-pile-v1",
            hiddenDrawPileSizes = hiddenDrawPiles.Select(pile => pile.Cards.Count).ToArray(),
        }, new JsonSerializerOptions { WriteIndented = true }));
        throw new InvalidDataException(
            $"Policy observation contains hidden draw pile contents; diagnostic={diagnosticPath}");
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
        IReadOnlyList<ExportedAction> LegalActions, IReadOnlyDictionary<string, int> VisitPolicy,
        int Simulations, double ElapsedMilliseconds, int ChoiceLayer,
        string? ParentActionId, string SelectedActionId,
        int NetworkPriorCalls, int NetworkValueCalls, int NetworkFallbacks);

    private sealed record SearchEnvelope(CombatSolverMctsAction Action,
        IReadOnlyList<RootActionStatistics<CombatSolverMctsAction>> Statistics,
        int Simulations, double ElapsedMilliseconds, bool Rebuilt,
        int NetworkPriorCalls, int NetworkValueCalls, int NetworkFallbacks,
        string Mode);

    private static async Task<SearchEnvelope> SearchRootAsync(
        CombatSolverReplayEnvironment environment,
        ReplayMcts<CombatSolverMctsAction> pureTree,
        AlphaZeroOnnxEvaluator? model,
        TimeSpan budget,
        int seed,
        CancellationToken cancellation,
        int? maxSimulations)
    {
        if (model is null)
        {
            var pure = await pureTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(pure.Action, pure.Statistics, pure.CompletedSimulations,
                pure.ElapsedMilliseconds, pure.Rebuilt, 0, 0, 0, "pure-mcts");
        }
        try
        {
            var policyTree = new PolicyValueMcts<CombatSolverMctsAction, CombatObservation>(
                environment,
                (observation, legal) =>
                {
                    if (!model.TryEvaluate(observation, legal, out var logits, out var value, out var status))
                        throw new InvalidDataException(status);
                    return new PolicyValuePrediction(logits.Select(item => (double)item).ToArray(), value);
                }, seed);
            var policy = await policyTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(policy.Action, policy.Statistics, policy.CompletedSimulations,
                policy.ElapsedMilliseconds, policy.Rebuilt, policy.NetworkPriorCalls,
                policy.NetworkValueCalls, policy.NetworkFallbacks, "policy-value-tree-v1");
        }
        catch (Exception error)
        {
            Godot.GD.PrintErr($"SLAY_WORKER_ALPHAZERO_EXPORT pure-mcts-fallback reason={error}");
            pureTree.Reset();
            var pure = await pureTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(pure.Action, pure.Statistics, pure.CompletedSimulations,
                pure.ElapsedMilliseconds, pure.Rebuilt, 0, 0, 1, "pure-mcts-fallback");
        }
    }
    private static string TrainingActionId(NativeMctsAction action)
        => action.Key;

    internal static async Task WaitForDecisionBudgetAsync(Stopwatch watch, TimeSpan budget, CancellationToken cancellation)
    {
        while (watch.Elapsed < budget)
            await Task.Delay(Math.Max(1, (int)Math.Ceiling((budget - watch.Elapsed).TotalMilliseconds)), cancellation);
    }

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
