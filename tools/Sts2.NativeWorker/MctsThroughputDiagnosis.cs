using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CombatSolver.Api;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;

internal static class MctsThroughputDiagnosis
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static async Task RunAsync(NativeSession native, string rootKind, string output,
        CancellationToken cancellation, double nativeResetMilliseconds,
        double workerStartupMilliseconds, NativeCombatCheckpoint checkpoint)
    {
        output = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var setupWatch = Stopwatch.StartNew();
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(native.CombatStateForSimulation, native.CaptureRewardSeed());
        native.BindTrajectoryRewardContext(environment.RewardContext);
        if (rootKind != "ordinary")
        {
            string parentCard = rootKind == "purity" ? "PURITY" : "CASCADE";
            var parent = environment.RootActions.Single(action => action.Native.CardId == parentCard);
            var liveParent = native.ToLiveSearchAction(parent);
            environment.Promote(parent);
            await native.StepAsync(liveParent, cancellation);
            AssertChoiceAlignment(native, environment);
            if (rootKind == "cascade-second")
            {
                var first = environment.RootActions.First(action =>
                    action.Native.SelectedCards is [{ CardId: "PREPARED", OptionOccurrence: 0 }]);
                var liveChoice = native.ToLiveSearchAction(first);
                environment.Promote(first);
                await native.StepAsync(liveChoice, cancellation);
                AssertChoiceAlignment(native, environment);
                if (environment.CurrentChoiceFrame.CompletedSelections.Count != 1)
                    throw new InvalidDataException("Second CASCADE root lost its completed first selection.");
            }
        }
        else if (native.HasPendingChoice)
            throw new InvalidDataException("Ordinary diagnosis unexpectedly begins at a choice.");

        await environment.RestoreAsync([], cancellation);
        string rootKey = environment.RootKey;
        string[] legalKeys = environment.RootActions.Select(action => action.Key).ToArray();
        if (legalKeys.Length == 0 || legalKeys.Distinct(StringComparer.Ordinal).Count() != legalKeys.Length)
            throw new InvalidDataException("Diagnosis root has empty or duplicate legal actions.");
        var frozenObservation = environment.ObserveCurrent();
        string observationHash = Hash(JsonSerializer.Serialize(frozenObservation));
        string checkpointHash = Hash(JsonSerializer.Serialize(checkpoint));
        var setupDiagnostics = environment.NativeDiagnosticSnapshot;
        setupWatch.Stop();
        bool phaseProfile = Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_PROFILE") == "1";
        var arms = new List<object>();
        var report = new Dictionary<string, object?>
        {
            ["format"] = "azcombat.same-root-mcts-diagnosis.v1",
            ["status"] = "incomplete",
            ["rootKind"] = rootKind,
            ["seed"] = native.Seed,
            ["encounter"] = native.EncounterId,
            ["fixtureCards"] = native.ChoiceFixture ? native.ChoiceFixtureCards : null,
            ["checkpointSha256"] = checkpointHash,
            ["rootKey"] = rootKey,
            ["rootActionKeysSha256"] = Hash(JsonSerializer.Serialize(legalKeys)),
            ["rootObservationSha256"] = observationHash,
            ["promotedActionKeys"] = environment.PromotedActionKeys,
            ["choiceFrame"] = environment.State.PendingChoice ? environment.CurrentChoiceFrame : null,
            ["maxDepth"] = 200,
            ["searchSeed"] = rootKind == "ordinary" ? 20260922 : 20270922,
            ["rolloutPolicy"] = "CombatSolverReplayEnvironment.RolloutAction",
            ["profileEnabled"] = phaseProfile,
            ["nativeResetMilliseconds"] = nativeResetMilliseconds,
            ["workerStartupMilliseconds"] = workerStartupMilliseconds,
            ["rootSetupMilliseconds"] = setupWatch.Elapsed.TotalMilliseconds,
            ["setupDriverDiagnostics"] = setupDiagnostics,
            ["arms"] = arms,
        };
        using (var created = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
            JsonSerializer.Serialize(created, report, JsonOptions);
        int searchSeed = rootKind == "ordinary" ? 20260922 : 20270922;
        try
        {
            await RunArmAsync("A-cold-1s", TimeSpan.FromSeconds(1), null, false, true);
            await RunArmAsync("warmup-discard-tree-1s", TimeSpan.FromSeconds(1), null, false, true);
            await RunArmAsync("B-hot-new-tree-1s", TimeSpan.FromSeconds(1), null, false, true);
            await RunArmAsync("C-hot-new-tree-5s", TimeSpan.FromSeconds(5), null, false, true);
            await RunArmAsync("E-hot-fixed-16", TimeSpan.FromSeconds(5), 16, false, true);
            if (phaseProfile)
                await RunArmAsync("D-hot-export-validation-1s", TimeSpan.FromSeconds(1), null, true, true);
            report["status"] = "complete";
        }
        catch (Exception error)
        {
            report["status"] = "failed";
            report["error"] = error.ToString();
            throw;
        }
        finally
        {
            File.WriteAllText(output, JsonSerializer.Serialize(report, JsonOptions));
        }

        async Task RunArmAsync(string label, TimeSpan budget, int? maxSimulations,
            bool exportValidation, bool record)
        {
            await environment.RestoreAsync([], cancellation);
            if (environment.StateKey() != rootKey ||
                Hash(JsonSerializer.Serialize(environment.ObserveCurrent())) != observationHash)
                throw new InvalidDataException($"Diagnosis root changed before arm {label}.");
            var environmentMetrics = new MctsReplayEnvironmentDiagnostics();
            environment.Diagnostics = environmentMetrics;
            var before = environment.NativeDiagnosticSnapshot;
            long allocatedBefore = GC.GetTotalAllocatedBytes(false);
            long[] collectionsBefore = [GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2)];
            double pauseBefore = GC.GetGCMemoryInfo().PauseTimePercentage;
            TimeSpan totalPauseBefore = GC.GetTotalPauseDuration();
            TimeSpan cpuBefore = Process.GetCurrentProcess().TotalProcessorTime;
            var decisionWatch = Stopwatch.StartNew();
            var searchMetrics = new ReplayMctsDiagnostics();
            TimedSearchResult<CombatSolverMctsAction> search;
            try
            {
                search = await CombatSolverMctsBenchmark.SearchPureRootAsync(
                    environment, budget, cancellation, searchSeed, maxSimulations, searchMetrics);
            }
            catch
            {
                arms.Add(new { label, failed = true, attempted = searchMetrics?.AttemptedSimulations,
                    incomplete = searchMetrics?.IncompleteSimulations });
                throw;
            }
            var afterSearch = environment.NativeDiagnosticSnapshot;
            double validationMs = 0, waitMs = 0;
            if (exportValidation)
            {
                var validationWatch = Stopwatch.StartNew();
                await CombatSolverMctsBenchmark.VerifyObservationRestorationAsync(
                    environment, frozenObservation, environment.RootActions, cancellation);
                validationMs = validationWatch.Elapsed.TotalMilliseconds;
                var waitWatch = Stopwatch.StartNew();
                await CombatSolverMctsBenchmark.WaitForDecisionBudgetAsync(decisionWatch, budget, cancellation);
                waitMs = waitWatch.Elapsed.TotalMilliseconds;
            }
            decisionWatch.Stop();
            var afterAll = environment.NativeDiagnosticSnapshot;
            long allocated = GC.GetTotalAllocatedBytes(false) - allocatedBefore;
            long[] collections = [GC.CollectionCount(0) - collectionsBefore[0],
                GC.CollectionCount(1) - collectionsBefore[1], GC.CollectionCount(2) - collectionsBefore[2]];
            var rootStatistics = search.Statistics.Select(item => new
            {
                actionKey = item.Action.Key, item.Visits, item.MeanValue,
            }).ToArray();
            if (rootStatistics.Length == 0 || rootStatistics.Any(item => item.Visits <= 0
                    || !legalKeys.Contains(item.actionKey, StringComparer.Ordinal))
                || !legalKeys.Contains(search.Action.Key, StringComparer.Ordinal))
                throw new InvalidDataException($"Arm {label} returned invalid root action statistics.");
            arms.Add(new
            {
                label,
                style = exportValidation ? "exporter" : "legacy-benchmark-search",
                budgetMilliseconds = budget.TotalMilliseconds,
                maxSimulations,
                completedSimulations = search.CompletedSimulations,
                searchActiveMs = search.ElapsedMilliseconds,
                decisionWallMs = decisionWatch.Elapsed.TotalMilliseconds,
                validationMs, waitMs,
                simulationsPerSecond = search.CompletedSimulations / (decisionWatch.Elapsed.TotalSeconds),
                selectedActionKey = search.Action.Key,
                retainedVisits = search.RetainedVisits,
                rootVisits = rootStatistics.Sum(item => item.Visits),
                rootStatistics,
                searchMetrics,
                environmentMetrics,
                driverSearch = Diff(before, afterSearch),
                driverExportValidation = Diff(afterSearch, afterAll),
                processAllocatedBytes = allocated,
                processCpuMilliseconds = (Process.GetCurrentProcess().TotalProcessorTime - cpuBefore).TotalMilliseconds,
                gcCollections = collections,
                gcPauseMilliseconds = (GC.GetTotalPauseDuration() - totalPauseBefore).TotalMilliseconds,
                gcPausePercentageBefore = pauseBefore,
                gcPausePercentageAfter = GC.GetGCMemoryInfo().PauseTimePercentage,
                rootRestored = await RootRestoredAsync(),
            });
            if (record) File.WriteAllText(output, JsonSerializer.Serialize(report, JsonOptions));
        }

        async Task<bool> RootRestoredAsync()
        {
            environment.Diagnostics = null;
            await environment.RestoreAsync([], cancellation);
            return environment.StateKey() == rootKey
                && Hash(JsonSerializer.Serialize(environment.ObserveCurrent())) == observationHash;
        }
    }

    private static void AssertChoiceAlignment(NativeSession native, CombatSolverReplayEnvironment environment)
    {
        if (!native.HasPendingChoice || !environment.State.PendingChoice
            || native.ChoiceSignature != environment.ChoiceSignature)
            throw new InvalidDataException("Native and predicted diagnosis choice boundaries differ.");
        var frame = environment.CurrentChoiceFrame;
        native.ValidateChoiceFrame(frame);
        native.ValidateSimulationActions(environment.RootActions);
        var liveObservation = CombatCaptureService.BuildDecisionPoint(
            native.CombatStateForSimulation, 0).Observation;
        if (JsonSerializer.Serialize(liveObservation) != JsonSerializer.Serialize(frame.Observation))
            throw new InvalidDataException("Native and predicted pre-selection observations differ.");
    }

    private static object Diff(NativeMctsDriverDiagnostics before, NativeMctsDriverDiagnostics after)
        => new
        {
            after.Enabled,
            forkCopies = after.ForkCount - before.ForkCount,
            rootForkCopies = after.RootForkCount - before.RootForkCount,
            replayCalls = after.ReplayCount - before.ReplayCount,
            choiceBranchesEvaluated = after.ChoiceBranchesEvaluated - before.ChoiceBranchesEvaluated,
            choiceReplayAttempts = after.ChoiceReplayAttempts - before.ChoiceReplayAttempts,
            choiceReplayBudgetExhaustions = after.ChoiceReplayBudgetExhaustions - before.ChoiceReplayBudgetExhaustions,
            choiceBranchesDroppedByBudget = after.ChoiceBranchesDroppedByBudget - before.ChoiceBranchesDroppedByBudget,
            semanticTransitions = after.TransitionCount - before.TransitionCount,
            generatedChoiceBranches = after.GeneratedChoiceBranches - before.GeneratedChoiceBranches,
            resolvedChoiceBranches = after.ResolvedChoiceBranches - before.ResolvedChoiceBranches,
            exclusivePhases = after.Phases.ToDictionary(pair => pair.Key, pair => new
            {
                milliseconds = pair.Value.ExclusiveMilliseconds
                    - before.Phases[pair.Key].ExclusiveMilliseconds,
                allocatedBytes = pair.Value.ExclusiveAllocatedBytes
                    - before.Phases[pair.Key].ExclusiveAllocatedBytes,
                inclusiveMilliseconds = pair.Value.InclusiveMilliseconds
                    - before.Phases[pair.Key].InclusiveMilliseconds,
                inclusiveAllocatedBytes = pair.Value.InclusiveAllocatedBytes
                    - before.Phases[pair.Key].InclusiveAllocatedBytes,
            }, StringComparer.Ordinal),
        };

    private static string Hash(string value)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
}
