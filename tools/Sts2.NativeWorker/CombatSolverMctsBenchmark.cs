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
        if (native.GeneratedScenario is not null
            && (startType != "full_combat" || native.ChoiceFixture || native.GeneratedDeckProvenance is null))
            throw new InvalidDataException("Generated deck export requires a verified, non-fixture full-combat native setup.");
        native.Checkpoint = null;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        using var model = AlphaZeroOnnxEvaluator.TryLoad(
            Environment.GetEnvironmentVariable("STS2_ALPHAZERO_ONNX_MODEL"), out var modelLoadStatus);
        var modelShadow = string.Equals(Environment.GetEnvironmentVariable("STS2_ALPHAZERO_SHADOW"), "1", StringComparison.Ordinal);
        var requestedSearchMode = Environment.GetEnvironmentVariable("STS2_ALPHAZERO_SEARCH_MODE");
        if (requestedSearchMode is not (null or "pure-mcts" or "policy-value-tree-v1"))
            throw new InvalidDataException($"Unsupported export search mode: {requestedSearchMode}");
        if (requestedSearchMode == "pure-mcts" && model != null)
            throw new InvalidDataException("A pure-MCTS export cannot load a model.");
        var treeRequested = requestedSearchMode == "policy-value-tree-v1";
        var treeMode = treeRequested && model != null;
        var parityPath = Environment.GetEnvironmentVariable("STS2_ALPHAZERO_ROOT_PARITY_OUT");
        if (parityPath != null)
        {
            if (!treeMode || string.IsNullOrWhiteSpace(parityPath))
                throw new InvalidDataException("Root parity capture requires a loaded policy-value-tree-v1 model and a nonempty output path.");
            parityPath = Path.GetFullPath(parityPath);
            if (string.Equals(parityPath, Path.GetFullPath(outputPath), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Root parity output must differ from the trajectory JSONL.");
            Directory.CreateDirectory(Path.GetDirectoryName(parityPath)!);
        }
        Godot.GD.Print("SLAY_WORKER_ALPHAZERO " + modelLoadStatus);
        var modelUsed = 0;
        var modelScored = 0;
        var modelFallbacks = 0;
        var forcedFixtureCard = Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_FORCE_CARD");
        var regressionOnlyText = Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_REGRESSION_ONLY");
        if (regressionOnlyText is not (null or "1"))
            throw new InvalidDataException("Export regression-only flag must be 1 when supplied.");
        bool regressionOnly = forcedFixtureCard != null || regressionOnlyText == "1";
        if (forcedFixtureCard != null && (string.IsNullOrWhiteSpace(forcedFixtureCard)
                || !native.ChoiceFixture || startType != "full_combat"))
            throw new InvalidDataException("Forced-card regression requires a full-combat choice fixture.");
        bool forcedFixtureChoiceObserved = false;
        using var parityWriter = parityPath is null ? null : new StreamWriter(
            new FileStream(parityPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read)) { AutoFlush = true };
        await using var writer = new StreamWriter(new FileStream(outputPath, FileMode.CreateNew, FileAccess.Write, FileShare.Read));
        var pending = new List<ExportedDecision>();
        var rewardAudits = new List<NativeMctsTerminalRewardInputs>();
        var maxDecisions = int.TryParse(Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_DECISIONS"), out var parsedMax)
            ? Math.Max(1, parsedMax) : 256;
        var maxSimulationsText = Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_SIMULATIONS");
        int? maxSimulations = null;
        if (maxSimulationsText != null)
        {
            if (!int.TryParse(maxSimulationsText, out var parsedSimulations) || parsedSimulations < 1)
                throw new InvalidDataException("Export max simulations must be a positive integer.");
            maxSimulations = parsedSimulations;
        }
        for (var decision = 0; decision < maxDecisions && !native.Terminal; decision++)
        {
            cancellation.ThrowIfCancellationRequested();
            using var environment = new CombatSolverReplayEnvironment();
            environment.Capture(native.CombatStateForSimulation, native.CaptureRewardSeed());
            native.BindTrajectoryRewardContext(environment.RewardContext);
            var decisionPoint = CombatCaptureService.BuildDecisionPoint(native.CombatStateForSimulation, decision);
            RequirePublicPolicyObservation(decisionPoint.Observation, outputPath, native.Seed, decision);
            var predictedObservation = environment.PolicyObservation();
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
            bool rootParityCaptured = false;
            var search = await SearchRootAsync(environment, tree, treeMode ? model : null,
                budget, 20260922 + decision, cancellation, maxSimulations, treeRequested, modelLoadStatus,
                (observation, actions, logits, value) =>
                {
                    if (environment.StateKey() != rootKey || rootParityCaptured) return;
                    WriteTreeParity(parityWriter, observation, decisionPoint.Observation,
                        rootKey, legal, actions,
                        logits, value, native.Seed, decision, 0);
                    rootParityCaptured = true;
                });
            if (parityWriter != null && !rootParityCaptured)
                throw new InvalidDataException("Ordinary root did not reach the actual tree evaluator.");
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
                search.NetworkValueCalls, search.NetworkFallbacks,
                treeRequested ? search.Mode : model == null ? "pure-mcts" : modelShadow ? "shadow-post-mcts" : "post-mcts-rerank",
                search.NetworkFallbackReason));
            try
            {
                string? predictedBefore = regressionOnly ? environment.CurrentContinuationStateText : null;
                string? liveBefore = regressionOnly
                    ? NativeMctsSimulationApi.CaptureLiveContinuationStateText(native.CombatStateForSimulation)
                    : null;
                int enemyDamageBefore = native.EnemyDamageLost;
                var liveAction = native.ToLiveSearchAction(selectedAction);
                environment.Promote(selectedAction);
                await native.StepAsync(liveAction, cancellation);
                int choiceLayer = 0;
                var completedLiveSelections = new List<CombatCompletedChoiceObservation>();
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
                        if (JsonSerializer.Serialize(frame.CompletedSelections)
                            != JsonSerializer.Serialize(completedLiveSelections))
                            throw new InvalidDataException("Choice frame completed prefix differs from executed native selections.");
                        if (frame.TriggerCardId != selectedAction.Native.CardId)
                            throw new InvalidDataException("Choice trigger differs from the executed parent card.");
                        if (!string.Equals(JsonSerializer.Serialize(choiceObservation),
                                JsonSerializer.Serialize(frame.Observation), StringComparison.Ordinal))
                            throw new InvalidDataException("Live/predicted pre-selection policy observations differ.");
                        choiceObservation = choiceEnvironment.PolicyObservation();
                        if (choiceObservation.Choice is null
                            || !string.Equals(JsonSerializer.Serialize(choiceObservation with { Choice = null }),
                                JsonSerializer.Serialize(frame.Observation), StringComparison.Ordinal))
                            throw new InvalidDataException("Current choice frame did not produce the tree policy observation.");
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
                    bool choiceParityCaptured = false;
                    var choiceRootKey = choiceEnvironment.RootKey;
                    var choiceSearch = await SearchRootAsync(choiceEnvironment, choiceTree, treeMode ? model : null,
                        budget, 20260922 + decision + 10000, cancellation, maxSimulations, treeRequested, modelLoadStatus,
                        (observation, actions, logits, value) =>
                        {
                            if (choiceEnvironment.StateKey() != choiceRootKey || choiceParityCaptured) return;
                            WriteTreeParity(parityWriter, observation, choiceObservation,
                                choiceRootKey, choiceActions,
                                actions, logits, value, native.Seed, decision, choiceLayer + 1);
                            choiceParityCaptured = true;
                        });
                    if (parityWriter != null && !choiceParityCaptured)
                        throw new InvalidDataException("Choice root did not reach the actual tree evaluator.");
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
                         choiceSearch.NetworkPriorCalls, choiceSearch.NetworkValueCalls, choiceSearch.NetworkFallbacks,
                         treeRequested ? choiceSearch.Mode : model == null ? "pure-mcts" : modelShadow ? "shadow-post-mcts" : "post-mcts-rerank",
                         choiceSearch.NetworkFallbackReason));
                    modelFallbacks += choiceSearch.NetworkFallbacks;
                    modelScored += choiceSearch.NetworkPriorCalls;
                    modelUsed += choiceSearch.NetworkValueCalls;
                    var liveChoice = native.ToLiveSearchAction(selectedChoice);
                    var liveCandidates = native.CaptureLiveChoiceEvidence().Candidates;
                    completedLiveSelections.Add(new CombatCompletedChoiceObservation(frame.Effect,
                        (liveChoice.Selection ?? throw new InvalidDataException("Live choice has no selected indices."))
                        .Select(index => liveCandidates[index].CombatCardIndex).ToArray()));
                    choiceEnvironment.Promote(selectedChoice);
                    await native.StepAsync(liveChoice, cancellation);
                }
                if (native.Terminal)
                {
                    await environment.RestoreAsync([], cancellation);
                    var predicted = environment.State;
                    string predictedContinuation = environment.CurrentContinuationStateText;
                    string liveContinuation = NativeMctsSimulationApi.CaptureLiveContinuationStateText(
                        native.CombatStateForSimulation);
                    bool terminalMatches = predicted.Terminal && predicted.Resolved
                        && !predicted.PendingChoice && predicted.Won == native.Won
                        && environment.CurrentBoundary is
                            { SimulatorHasPendingChoice: false, CombatHasPendingChoice: false }
                        && predicted.EnemyHpLost == native.EnemyDamageLost - enemyDamageBefore;
                    bool beforeMatches = predictedBefore == liveBefore;
                    bool rngMatches = ContinuationField(predictedContinuation, "R")
                        == ContinuationField(liveContinuation, "R");
                    if (regressionOnly || !terminalMatches)
                    {
                        File.WriteAllText(outputPath + ".terminal-boundary.json", JsonSerializer.Serialize(new
                        {
                            seed = native.Seed, decision, selectedActionId = TrainingActionId(selectedAction.Native),
                            liveTerminal = native.Terminal, liveWon = native.Won,
                            livePlayerHp = native.Hp, liveEnemyHpLost = native.EnemyDamageLost,
                            enemyDamageBefore, enemyDamageThisAction = native.EnemyDamageLost - enemyDamageBefore,
                            lastEnemyHpTransition = native.EnemyHpTransitions.LastOrDefault(),
                            predicted, currentBoundary = environment.CurrentBoundary,
                            probeBoundary = environment.LastProbeBoundary,
                            predictedPreTeardownReward = environment.EvaluateTerminal(),
                            actualSettledReward = native.EvaluateTerminal(), terminalMatches,
                            beforeMatches, rngMatches,
                            postTeardownContinuationMatches = predictedContinuation == liveContinuation,
                            predictedBefore, liveBefore, predictedContinuation, liveContinuation,
                        }, new JsonSerializerOptions { WriteIndented = true }));
                    }
                    if (!terminalMatches || regressionOnly && (!beforeMatches || !rngMatches))
                        throw new InvalidDataException(
                            $"Live terminal differs from predicted settled terminal; diagnostic={outputPath}.terminal-boundary.json");
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
                if (native.Terminal)
                {
                    await environment.RestoreAsync([], cancellation);
                    rewardAudits.Add(environment.TerminalRewardInputs());
                }
                else if (!environment.State.PendingChoice)
                {
                    rewardAudits.Add(environment.UnresolvedRewardInputs());
                }
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
                    probeBoundary = environment.LastProbeBoundary,
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
        var actualSearchModes = pending.Select(item => item.SearchMode).Distinct(StringComparer.Ordinal).ToArray();
        var provenance = new
        {
            searchSemanticsVersion = "azcombat.search.v3",
            rewardLedgerVersion = "azcombat.reward-ledger.v2",
            seed = native.Seed,
            encounter = native.EncounterId,
            choiceFixture = native.ChoiceFixture,
            fixtureCards = native.ChoiceFixture ? native.ChoiceFixtureCards : null,
            regressionOnly,
            forcedFixtureCard,
            forcedFixtureChoiceObserved,
            generatedDeck = native.GeneratedDeckProvenance,
            budgetMilliseconds,
            maxDecisions,
            maxSimulations,
            terminal = resolved,
            entryHp = native.EntryHp,
            playerHp = native.Hp,
            trajectoryInitialEnemyEffectiveHp = native.TrajectoryInitialEnemyEffectiveHp,
            enemyDamageLost = native.EnemyDamageLost,
            enemyHpTransitions = native.EnemyHpTransitions.Select(item => new {
                before = item.Before, after = item.After, damage = item.Damage,
                historyStartIndex = item.HistoryStartIndex,
                historyEndIndex = item.HistoryEndIndex,
                enemyRosterBefore = item.EnemyRosterBefore.Select(enemy => new {
                    combatId = enemy.CombatId, monsterId = enemy.MonsterId, hp = enemy.Hp,
                }).ToArray(),
                enemyRosterAfter = item.EnemyRosterAfter.Select(enemy => new {
                    combatId = enemy.CombatId, monsterId = enemy.MonsterId, hp = enemy.Hp,
                }).ToArray(),
                historyReset = item.HistoryReset,
                damageCaptureSource = item.DamageCaptureSource,
                enemyDamageEvents = item.EnemyDamageEvents.Select(damage => new {
                    combatId = damage.CombatId, monsterId = damage.MonsterId,
                    unblockedDamage = damage.UnblockedDamage,
                    overkillDamage = damage.OverkillDamage,
                    creditedDamage = damage.CreditedDamage,
                }).ToArray(),
            }).ToArray(),
            rewardAudits,
            startProvenance,
            modelLoadStatus,
            requestedSearchMode,
            searchMode = actualSearchModes.Length == 1 ? actualSearchModes[0] : "mixed-search-modes",
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
                networkFallbackReason = item.NetworkFallbackReason,
                searchMode = item.SearchMode,
                maxSimulations,
                budgetMilliseconds,
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

    internal static async Task VerifyObservationRestorationAsync(
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

    internal static object AssemblyProvenance()
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

    private static void WriteTreeParity(StreamWriter? writer, CombatObservation observation,
        CombatObservation expectedObservation,
        string rootKey, IReadOnlyList<CombatSolverMctsAction> expected,
        IReadOnlyList<CombatSolverMctsAction> legal, IReadOnlyList<float> logits, float value,
        string seed, int decision, int choiceLayer)
    {
        if (!legal.Select(action => action.Key).SequenceEqual(expected.Select(action => action.Key)))
            throw new InvalidDataException("Tree root legal action order differs from the export boundary.");
        var observationJson = JsonSerializer.Serialize(observation);
        if (observationJson != JsonSerializer.Serialize(expectedObservation))
            throw new InvalidDataException("Actual tree evaluator input differs from the export observation.");
        if (writer is null) return;
        var observationSha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(observationJson)));
        writer.WriteLine(JsonSerializer.Serialize(new
        {
            seed, decision, choiceLayer, stateKey = rootKey, observationJson,
            observation,
            observationSha256,
            orderedActionIds = legal.Select(action => TrainingActionId(action.Native)).ToArray(),
            legalActions = legal.Select(action => action.Native).ToArray(),
            logits, value, actualTreeEvaluator = true,
        }));
    }

    private sealed record ExportedAction(string kind, string actionId, bool terminal, NativeMctsAction payload);
    private sealed record ExportedDecision(string Seed, int Decision, object Observation, string RootKey,
        IReadOnlyList<ExportedAction> LegalActions, IReadOnlyDictionary<string, int> VisitPolicy,
        int Simulations, double ElapsedMilliseconds, int ChoiceLayer,
        string? ParentActionId, string SelectedActionId,
        int NetworkPriorCalls, int NetworkValueCalls, int NetworkFallbacks,
        string SearchMode, string? NetworkFallbackReason);

    private sealed record SearchEnvelope(CombatSolverMctsAction Action,
        IReadOnlyList<RootActionStatistics<CombatSolverMctsAction>> Statistics,
        int Simulations, double ElapsedMilliseconds, bool Rebuilt,
        int NetworkPriorCalls, int NetworkValueCalls, int NetworkFallbacks,
        string Mode, string? NetworkFallbackReason);

    private sealed class ModelInferenceException(string message) : Exception(message) { }

    private static async Task<SearchEnvelope> SearchRootAsync(
        CombatSolverReplayEnvironment environment,
        ReplayMcts<CombatSolverMctsAction> pureTree,
        AlphaZeroOnnxEvaluator? model,
        TimeSpan budget,
        int seed,
        CancellationToken cancellation,
        int? maxSimulations,
        bool treeRequested,
        string modelLoadStatus,
        Action<CombatObservation, IReadOnlyList<CombatSolverMctsAction>, IReadOnlyList<float>, float>? onTreeEvaluation = null)
    {
        if (model is null)
        {
            var pure = await pureTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(pure.Action, pure.Statistics, pure.CompletedSimulations,
                pure.ElapsedMilliseconds, pure.Rebuilt, 0, 0, treeRequested ? 1 : 0,
                treeRequested ? "pure-mcts-fallback" : "pure-mcts",
                treeRequested ? modelLoadStatus : null);
        }
        try
        {
            var policyTree = new PolicyValueMcts<CombatSolverMctsAction, CombatObservation>(
                environment,
                (observation, legal) =>
                {
                    if (!model.TryEvaluate(observation, legal, out var logits, out var value, out var status))
                        throw new ModelInferenceException(status);
                    onTreeEvaluation?.Invoke(observation, legal, logits, value);
                    return new PolicyValuePrediction(logits.Select(item => (double)item).ToArray(), value);
                }, seed);
            var policy = await policyTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(policy.Action, policy.Statistics, policy.CompletedSimulations,
                policy.ElapsedMilliseconds, policy.Rebuilt, policy.NetworkPriorCalls,
                policy.NetworkValueCalls, policy.NetworkFallbacks, "policy-value-tree-v1", null);
        }
        catch (ModelInferenceException error)
        {
            Godot.GD.PrintErr($"SLAY_WORKER_ALPHAZERO_EXPORT pure-mcts-fallback reason={error}");
            pureTree.Reset();
            var pure = await pureTree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
                maxSimulations: maxSimulations);
            return new SearchEnvelope(pure.Action, pure.Statistics, pure.CompletedSimulations,
                pure.ElapsedMilliseconds, pure.Rebuilt, 0, 0, 1, "pure-mcts-fallback", error.ToString());
        }
    }
    private static string TrainingActionId(NativeMctsAction action)
        => action.Key;

    private static string ContinuationField(string stateText, string name)
        => stateText.Split(';').Single(field => field.StartsWith(name + "=", StringComparison.Ordinal));

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
        environment.Capture(native.CombatStateForSimulation, native.CaptureRewardSeed());
        native.BindTrajectoryRewardContext(environment.RewardContext);
        return await SearchPureRootAsync(environment, budget, cancellation);
    }

    internal static Task<TimedSearchResult<CombatSolverMctsAction>> SearchPureRootAsync(
        CombatSolverReplayEnvironment environment, TimeSpan budget, CancellationToken cancellation,
        int seed = 20260922, int? maxSimulations = null, ReplayMctsDiagnostics? diagnostics = null)
    {
        var tree = new ReplayMcts<CombatSolverMctsAction>(environment, seed, diagnostics);
        return tree.SearchAsync([], environment.RootKey, budget, budget, cancellation,
            maxDepth: 200, maxSimulations: maxSimulations);
    }
}
