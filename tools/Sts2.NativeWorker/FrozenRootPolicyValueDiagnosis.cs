using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CombatSolver.Api;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

// Search-only ablation. This artifact is not a trajectory or a training sample.
internal static class FrozenRootPolicyValueDiagnosis
{
    private const int SimulationsPerArm = 32;
    private static readonly TimeSpan ArmBudget = TimeSpan.FromSeconds(60);
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static async Task RunAsync(NativeSession native, string rootKind, string output,
        CancellationToken cancellation, NativeCombatCheckpoint checkpoint)
    {
        output = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var modelPath = Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_MODEL")
            ?? throw new InvalidDataException("STS2_MCTS_DIAG_MODEL is required.");
        using var model = AlphaZeroOnnxEvaluator.TryLoad(modelPath, out var modelStatus)
            ?? throw new InvalidDataException("Frozen-root model load failed: " + modelStatus);
        modelPath = Path.GetFullPath(modelPath);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(native.CombatStateForSimulation, native.CaptureRewardSeed());
        native.BindTrajectoryRewardContext(environment.RewardContext);
        var liveCompletedSelections = new List<CombatCompletedChoiceObservation>();
        var actualTreeEvaluatorInputs = new List<object>();
        if (rootKind == "purity")
        {
            // A separate, bounded tree from the real ordinary root must expand
            // a choice as a child. Choice-root-only checks cannot exercise this.
            var ordinaryKey = environment.RootKey;
            int legalCount = environment.RootActions.Count;
            int invocation = 0;
            bool sawExpandedChoice = false;
            var probe = new PolicyValueMcts<CombatSolverMctsAction, CombatObservation>(environment,
                (nodeObservation, actions) =>
                {
                    invocation++;
                    if (environment.State.PendingChoice)
                    {
                        sawExpandedChoice = true;
                        if (nodeObservation.Choice is null)
                            throw new InvalidDataException("Newly expanded choice reached tree evaluator without Choice context.");
                    }
                    if (!model.TryEvaluate(nodeObservation, actions, out var logits, out var value, out var status))
                        throw new InvalidDataException("Expanded-choice model inference failed: " + status);
                    var policyLogits = logits.Select(item => (double)item).ToArray();
                    RecordTreeInput("expanded-choice-probe", invocation, nodeObservation, actions,
                        policyLogits, value);
                    return new PolicyValuePrediction(policyLogits, value);
                }, 20270922);
            await probe.SearchAsync([], ordinaryKey, ArmBudget, ArmBudget, cancellation,
                maxDepth: 200, maxSimulations: legalCount + 1);
            if (!sawExpandedChoice)
                throw new InvalidDataException("Bounded ordinary-root tree did not evaluate a newly expanded choice node.");
            await environment.RestoreAsync([], cancellation);
        }
        if (rootKind != "ordinary")
        {
            var parent = environment.RootActions.Single(action => action.Native.CardId ==
                (rootKind == "purity" ? "PURITY" : "CASCADE"));
            var liveParent = native.ToLiveSearchAction(parent);
            environment.Promote(parent);
            await native.StepAsync(liveParent, cancellation);
            AssertChoiceAlignment();
            if (rootKind == "cascade-second")
            {
                var first = environment.RootActions.First(action =>
                    action.Native.SelectedCards is [{ CardId: "PREPARED", OptionOccurrence: 0 }]);
                var liveChoice = native.ToLiveSearchAction(first);
                var liveOptions = native.CaptureLiveChoiceEvidence().Candidates;
                liveCompletedSelections.Add(new CombatCompletedChoiceObservation("Discard",
                    (liveChoice.Selection ?? throw new InvalidDataException("First CASCADE selection has no live indices."))
                    .Select(index => liveOptions[index].CombatCardIndex).ToArray()));
                environment.Promote(first);
                await native.StepAsync(liveChoice, cancellation);
                AssertChoiceAlignment();
                if (environment.CurrentChoiceFrame.CompletedSelections.Count != 1)
                    throw new InvalidDataException("Second CASCADE choice lost completed selection.");
            }
        }
        else if (native.HasPendingChoice)
            throw new InvalidDataException("Ordinary frozen root unexpectedly has a pending choice.");

        await environment.RestoreAsync([], cancellation);
        var rootKey = environment.RootKey;
        var legal = environment.RootActions.ToArray();
        var legalIds = legal.Select(action => action.Key).ToArray();
        if (legalIds.Length == 0 || legalIds.Distinct(StringComparer.Ordinal).Count() != legalIds.Length)
            throw new InvalidDataException("Frozen root has no actions or duplicate action IDs.");
        var observation = environment.ObserveCurrent();
        var observationJson = JsonSerializer.Serialize(observation);
        var choiceFrame = environment.State.PendingChoice ? environment.CurrentChoiceFrame : null;
        CombatObservation? choiceContextObservation = choiceFrame?.ToPolicyObservation();
        var liveBaseObservation = CombatCaptureService.BuildDecisionPoint(
            native.CombatStateForSimulation, 0).Observation;
        var liveChoiceEvidence = choiceFrame == null ? null : native.CaptureLiveChoiceEvidence();
        bool choiceContextAligned = choiceFrame == null ||
            JsonSerializer.Serialize(observation) == JsonSerializer.Serialize(choiceContextObservation);
        if (!model.TryEvaluate(observation, legal, out var rootLogits, out var rootValue,
                out var rootStatus))
            throw new InvalidDataException("Frozen-root model evaluation failed: " + rootStatus);
        var rootPriors = Softmax(rootLogits.Select(value => (double)value).ToArray());
        var rootObservationHash = Hash(observationJson);
        var report = new Dictionary<string, object?>
        {
            ["format"] = "azcombat.frozen-root-policy-value-diagnosis.v1",
            ["status"] = "incomplete",
            ["regressionOnly"] = true,
            ["searchOnly"] = true,
            ["seed"] = native.Seed,
            ["encounter"] = native.EncounterId,
            ["rootKind"] = rootKind,
            ["fixtureCards"] = native.ChoiceFixture ? native.ChoiceFixtureCards : null,
            ["checkpointSha256"] = Hash(JsonSerializer.Serialize(checkpoint)),
            ["promotedActionKeys"] = environment.PromotedActionKeys,
            ["stateKey"] = rootKey,
            ["observation"] = observation,
            ["observationSha256"] = rootObservationHash,
            ["choiceContextObservation"] = choiceContextObservation,
            ["choiceContextAligned"] = choiceContextAligned,
            ["legalActionIds"] = legalIds,
            ["choiceFrame"] = choiceFrame,
            ["liveBaseObservation"] = liveBaseObservation,
            ["liveChoiceEvidence"] = liveChoiceEvidence,
            ["liveCompletedSelections"] = liveCompletedSelections.ToArray(),
            ["exportObservation"] = observation,
            ["actualTreeEvaluatorInputs"] = actualTreeEvaluatorInputs,
            ["model"] = new { path = modelPath, sha256 = Hash(File.ReadAllBytes(modelPath)),
                loadStatus = modelStatus },
            ["rootModel"] = new
            {
                logits = rootLogits,
                prior = rootPriors,
                actionScores = legalIds.Select((id, index) => new
                {
                    actionId = id, logit = rootLogits[index], prior = rootPriors[index],
                }).ToArray(),
                value = rootValue,
                outsideSearch = true,
            },
            ["rootTerminal"] = environment.Terminal,
            ["searchSeed"] = 20270922,
            ["maxDepth"] = 200,
            ["maxSimulations"] = SimulationsPerArm,
            ["budgetMilliseconds"] = ArmBudget.TotalMilliseconds,
            ["trajectoryOutcome"] = null,
            ["trajectoryValueTarget"] = null,
            ["assemblies"] = new
            {
                nativeWorker = Identity(typeof(Worker).Assembly),
                search = Identity(typeof(ReplayMcts<>).Assembly),
                combatSolver = Identity(typeof(NativeMctsSimulationApi).Assembly),
            },
        };
        var arms = new List<object>();
        report["arms"] = arms;
        using (var created = new FileStream(output, FileMode.CreateNew, FileAccess.Write))
            JsonSerializer.Serialize(created, report, JsonOptions);
        try
        {
            await AssertFrozenRoot();
            var pure = await CombatSolverMctsBenchmark.SearchPureRootAsync(environment,
                ArmBudget, cancellation, 20270922, SimulationsPerArm);
            arms.Add(Arm("pure-mcts", pure.Action, pure.CompletedSimulations,
                pure.ElapsedMilliseconds, pure.Statistics, 0, 0, 0, 0, 0));
            Save();
            if (pure.CompletedSimulations != SimulationsPerArm)
                throw new TimeoutException("Pure frozen-root arm did not complete its fixed simulations.");
            await RunTree("model-prior_model-value", true, true);
            await RunTree("model-prior_constant-zero-value", true, false);
            await RunTree("uniform-prior_model-value", false, true);
            await RunTree("uniform-prior_constant-zero-value", false, false);
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
            Save();
        }

        async Task RunTree(string label, bool modelPrior, bool modelValue)
        {
            await AssertFrozenRoot();
            int inferenceCalls = 0, appliedPrior = 0, appliedValue = 0;
            int evaluatorInvocations = 0;
            var tree = new PolicyValueMcts<CombatSolverMctsAction, CombatObservation>(environment,
                (nodeObservation, actions) =>
                {
                    if (evaluatorInvocations == 0 &&
                        (Hash(JsonSerializer.Serialize(nodeObservation)) != rootObservationHash
                         || !actions.Select(action => action.Key).SequenceEqual(legalIds)))
                        throw new InvalidDataException("Tree evaluator first node differs from frozen root.");
                    evaluatorInvocations++;
                    double[] logits;
                    double value;
                    if (modelPrior || modelValue)
                    {
                        if (!model.TryEvaluate(nodeObservation, actions, out var inferredLogits,
                                out var inferredValue, out var status))
                            throw new InvalidDataException("Frozen-root model inference failed: " + status);
                        inferenceCalls++;
                        if (evaluatorInvocations == 1 &&
                            (inferredLogits.Length != rootLogits.Length
                             || inferredLogits.Zip(rootLogits).Any(pair => Math.Abs(pair.First - pair.Second) > 1e-5)
                             || Math.Abs(inferredValue - rootValue) > 1e-5))
                            throw new InvalidDataException("Tree root model output differs from frozen diagnostic inference.");
                        logits = modelPrior ? inferredLogits.Select(x => (double)x).ToArray()
                            : new double[actions.Count];
                        value = modelValue ? inferredValue : 0;
                    }
                    else
                    {
                        logits = new double[actions.Count];
                        value = 0;
                    }
                    if (modelPrior) appliedPrior++;
                    if (modelValue) appliedValue++;
                    RecordTreeInput(label, evaluatorInvocations, nodeObservation, actions,
                        logits, value);
                    return new PolicyValuePrediction(logits, value);
                }, 20270922);
            var result = await tree.SearchAsync([], rootKey, ArmBudget, ArmBudget, cancellation,
                maxDepth: 200, maxSimulations: SimulationsPerArm);
            if (evaluatorInvocations != result.NetworkPriorCalls
                || evaluatorInvocations != result.NetworkValueCalls)
                throw new InvalidDataException("Tree evaluator invocation accounting differs from search result.");
            arms.Add(Arm(label, result.Action, result.CompletedSimulations,
                result.ElapsedMilliseconds, result.Statistics, inferenceCalls,
                appliedPrior, appliedValue, result.NetworkPriorCalls, result.NetworkFallbacks));
            Save();
            if (result.CompletedSimulations != SimulationsPerArm)
                throw new TimeoutException($"Frozen-root arm {label} did not complete its fixed simulations.");
        }

        object Arm(string label, CombatSolverMctsAction selected, int completed,
            double elapsedMilliseconds, IReadOnlyList<RootActionStatistics<CombatSolverMctsAction>> statistics,
            int inferenceCalls, int appliedPrior, int appliedValue, int evaluatorCalls, int fallback)
        {
            var byId = statistics.ToDictionary(item => item.Action.Key, StringComparer.Ordinal);
            if (completed < 1 || byId.Count != statistics.Count
                || byId.Keys.Except(legalIds, StringComparer.Ordinal).Any()
                || !byId.ContainsKey(selected.Key)
                || statistics.Any(item => item.Visits <= 0))
                throw new InvalidDataException("Frozen-root search returned invalid action visits.");
            bool pureArm = label == "pure-mcts";
            if (statistics.Sum(item => item.Visits) != completed - (pureArm ? 0 : 1))
                throw new InvalidDataException("Frozen-root root visits do not match completed simulations.");
            return new
            {
                mode = label,
                completedSimulations = completed,
                requestedSimulations = SimulationsPerArm,
                elapsedMilliseconds,
                selectedActionId = selected.Key,
                rootVisits = statistics.Sum(item => item.Visits),
                actions = legalIds.Select(id => new
                {
                    actionId = id,
                    visits = byId.TryGetValue(id, out var stat) ? stat.Visits : 0,
                    meanQ = byId.TryGetValue(id, out stat) ? stat.MeanValue : (double?)null,
                    bestQ = byId.TryGetValue(id, out stat) ? stat.BestValue : (double?)null,
                }).ToArray(),
                networkInferenceCalls = inferenceCalls,
                modelPriorAppliedNodes = appliedPrior,
                modelValueBackprops = appliedValue,
                evaluatorCalls,
                fallbackCount = fallback,
                terminal = (bool?)null,
                unresolved = (bool?)null,
                outcome = (string?)null,
                valueTarget = (double?)null,
            };
        }

        async Task AssertFrozenRoot()
        {
            await environment.RestoreAsync([], cancellation);
            if (environment.Terminal || environment.RootKey != rootKey
                || environment.StateKey() != rootKey
                || !environment.RootActions.Select(action => action.Key).SequenceEqual(legalIds)
                || Hash(JsonSerializer.Serialize(environment.ObserveCurrent())) != rootObservationHash)
                throw new InvalidDataException("Frozen-root identity changed between ablation arms.");
        }

        void AssertChoiceAlignment()
        {
            if (!native.HasPendingChoice || !environment.State.PendingChoice
                || native.ChoiceSignature != environment.ChoiceSignature)
                throw new InvalidDataException("Live/predicted frozen choice boundaries differ.");
            var frame = environment.CurrentChoiceFrame;
            native.ValidateChoiceFrame(frame);
            native.ValidateSimulationActions(environment.RootActions);
            string expectedTrigger = rootKind == "purity" ? "PURITY" : "CASCADE";
            string expectedEffect = rootKind == "purity" ? "Exhaust" : "Discard";
            if (frame.TriggerCardId != expectedTrigger || frame.Effect != expectedEffect
                || frame.SourcePile != "Hand" || frame.Ordered
                || JsonSerializer.Serialize(frame.CompletedSelections)
                    != JsonSerializer.Serialize(liveCompletedSelections))
                throw new InvalidDataException("Choice fixture context or completed live prefix differs.");
            var liveObservation = CombatCaptureService.BuildDecisionPoint(
                native.CombatStateForSimulation, 0).Observation;
            if (JsonSerializer.Serialize(liveObservation) != JsonSerializer.Serialize(frame.Observation))
                throw new InvalidDataException("Live/predicted frozen choice observations differ.");
        }

        void Save() => File.WriteAllText(output, JsonSerializer.Serialize(report, JsonOptions));

        void RecordTreeInput(string arm, int invocation, CombatObservation nodeObservation,
            IReadOnlyList<CombatSolverMctsAction> actions, IReadOnlyList<double> logits, double value)
        {
            if (actualTreeEvaluatorInputs.Count >= 160)
                throw new InvalidDataException("Bounded tree evaluator trace exceeded 160 nodes.");
            string json = JsonSerializer.Serialize(nodeObservation);
            actualTreeEvaluatorInputs.Add(new
            {
                arm, invocation, stateKey = environment.StateKey(), observation = nodeObservation,
                observationJson = json, observationSha256 = Hash(json),
                orderedActionIds = actions.Select(action => action.Key).ToArray(),
                legalActions = actions.Select(action => action.Native).ToArray(),
                logits = logits.ToArray(), value, actualTreeEvaluator = true,
            });
        }
    }

    private static double[] Softmax(IReadOnlyList<double> logits)
    {
        double max = logits.Max();
        var exp = logits.Select(x => Math.Exp(Math.Clamp(x - max, -80, 80))).ToArray();
        double total = exp.Sum();
        if (!(total > 0) || !double.IsFinite(total))
            throw new InvalidDataException("Frozen-root prior normalization failed.");
        return exp.Select(x => x / total).ToArray();
    }

    private static object Identity(System.Reflection.Assembly assembly)
    {
        var path = assembly.Location;
        return new { path, mvid = assembly.ManifestModule.ModuleVersionId,
            sha256 = Hash(File.ReadAllBytes(path)) };
    }

    private static string Hash(string value) => Hash(Encoding.UTF8.GetBytes(value));
    private static string Hash(byte[] value) => Convert.ToHexString(SHA256.HashData(value));
}
