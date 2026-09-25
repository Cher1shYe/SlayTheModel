using System.Diagnostics;
using System.Text.Json;
using Godot;
using CombatSolver.Api;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static class WorkerServer
{
    public static async Task RunAsync(Node host, NativeSession session, string directory, int parentId)
    {
        using var model = AlphaZeroOnnxEvaluator.TryLoad(
            System.Environment.GetEnvironmentVariable("STS2_ALPHAZERO_ONNX_MODEL"), out var modelStatus);
        GD.Print("SLAY_WORKER_ALPHAZERO_SERVER " + modelStatus);
        using var simulation = new CombatSolverReplayEnvironment();
        var tree = new ReplayMcts<CombatSolverMctsAction>(simulation);
        var returnedActions = new Dictionary<string, CombatSolverMctsAction>(StringComparer.Ordinal);
        string? checkpointKey = null;
        while (true)
        {
            try { if (Process.GetProcessById(parentId).HasExited) return; }
            catch (ArgumentException) { return; }
            var path = Directory.EnumerateFiles(directory, "*.request.json")
                .Order(StringComparer.Ordinal)
                .FirstOrDefault();
            if (path == null)
            {
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                continue;
            }
            NativeMctsRequest request;
            try
            {
                request = JsonSerializer.Deserialize<NativeMctsRequest>(File.ReadAllText(path))
                    ?? throw new InvalidDataException("Empty worker request.");
                File.Delete(path);
            }
            catch (IOException)
            {
                // Atomic rename normally makes a request immediately readable, but
                // antivirus/indexing can briefly retain a Windows file handle.
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                continue;
            }
            NativeMctsResponse response;
            try
            {
                if (checkpointKey != request.Checkpoint.RunPacket)
                {
                    tree.Reset();
                    returnedActions.Clear();
                    checkpointKey = request.Checkpoint.RunPacket;
                }
                session.Checkpoint = request.Checkpoint;
                session.EntryHp = request.EntryHp;
                if (request.BudgetMilliseconds is < 50 or > 10_000)
                    throw new InvalidDataException("Search budget must be between 50 and 10000 ms.");
                await session.RestoreAsync(request.Prefix, CancellationToken.None);
                if (session.StateKey() != request.StateKey)
                    throw new InvalidDataException("Native reconstruction differs from the requested root state.");

                bool reused = false;
                if (returnedActions.Count > 0)
                    reused = simulation.MatchesLiveRoot(
                        session.CombatStateForSimulation, session.HasPendingChoice,
                        session.ChoiceSignature);
                if (reused && (!simulation.HasRewardContext
                    || simulation.RewardContext.TrajectoryId != session.TrajectoryId
                    || simulation.RewardContext.CapturedEnemyDamagePrefix != session.EnemyDamageLost
                    || simulation.RewardContext.CaptureBoundaryKey
                        != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                            session.CombatStateForSimulation)))
                    reused = false;
                SearchAction? previousRequest = request.PreviousAction ?? request.Prefix.LastOrDefault();
                if (!reused && previousRequest != null
                    && returnedActions.TryGetValue(previousRequest.Key, out var previous))
                {
                    simulation.Promote(previous);
                    tree.Advance(previous);
                    reused = simulation.MatchesLiveRoot(
                        session.CombatStateForSimulation, session.HasPendingChoice,
                        session.ChoiceSignature);
                }
                if (reused && (!simulation.HasRewardContext
                    || simulation.RewardContext.TrajectoryId != session.TrajectoryId
                    || simulation.RewardContext.CapturedEnemyDamagePrefix != session.EnemyDamageLost
                    || simulation.RewardContext.CaptureBoundaryKey
                        != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                            session.CombatStateForSimulation)))
                    reused = false;
                if (!reused)
                {
                    if (session.HasPendingChoice)
                        throw new InvalidDataException(
                            "Cannot align the Combat Solver tree with the restored native choice boundary. "
                            + $"native={session.ChoiceSignature} simulated={simulation.ChoiceSignature} "
                            + $"choiceDiagnostics={simulation.ChoiceDiagnostics}");
                    // A request without PreviousAction may be a native choice boundary whose
                    // ponder key did not match. The restored session is authoritative; never
                    // search the previous play-state root at a new choice boundary.
                    simulation.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
                    session.BindTrajectoryRewardContext(simulation.RewardContext);
                    tree.Reset();
                }
                session.ValidateSimulationActions(simulation.LegalActions());

                var budget = TimeSpan.FromMilliseconds(request.BudgetMilliseconds);
                long transitionsBefore = simulation.Transitions;
                var decisionWatch = Stopwatch.StartNew();
                CombatSolverMctsAction rootAction;
                int completedSimulations, retainedVisits, networkPriorCalls = 0,
                    networkValueCalls = 0, networkFallbacks = 0;
                string? networkFallbackReason = null;
                IReadOnlyList<RootActionStatistics<CombatSolverMctsAction>> statistics;
                bool rebuilt;
                string searchMode;
                if (model != null)
                {
                    try
                    {
                        var policyTree = new PolicyValueMcts<CombatSolverMctsAction, CombatObservation>(
                            simulation,
                            (observation, legal) =>
                            {
                                if (!model.TryEvaluate(observation, legal, out var logits, out var value, out var status))
                                    throw new InvalidDataException(status);
                                GD.Print($"SLAY_WORKER_ALPHAZERO_SERVER {status}");
                                return new PolicyValuePrediction(logits.Select(item => (double)item).ToArray(), value);
                            });
                        var policyResult = await policyTree.SearchAsync([], simulation.RootKey, budget, budget);
                        rootAction = policyResult.Action;
                        completedSimulations = policyResult.CompletedSimulations;
                        retainedVisits = policyResult.RetainedVisits;
                        statistics = policyResult.Statistics;
                        rebuilt = policyResult.Rebuilt;
                        networkPriorCalls = policyResult.NetworkPriorCalls;
                        networkValueCalls = policyResult.NetworkValueCalls;
                        networkFallbacks = policyResult.NetworkFallbacks;
                        searchMode = "policy-value-tree-v1";
                        GD.Print($"SLAY_WORKER_ALPHAZERO_SERVER policy-value-tree-v1 prior={networkPriorCalls} value={networkValueCalls} fallback={networkFallbacks}");
                    }
                    catch (Exception policyError)
                    {
                        networkFallbacks = 1;
                        networkFallbackReason = policyError.ToString();
                        searchMode = "pure-mcts-fallback";
                        GD.PrintErr($"SLAY_WORKER_ALPHAZERO_SERVER pure-mcts-fallback reason={policyError}");
                        tree.Reset();
                        var pureResult = await tree.SearchAsync([], simulation.RootKey, budget, budget);
                        rootAction = pureResult.Action;
                        completedSimulations = pureResult.CompletedSimulations;
                        retainedVisits = pureResult.RetainedVisits;
                        statistics = pureResult.Statistics;
                        rebuilt = pureResult.Rebuilt;
                    }
                }
                else
                {
                    var pureResult = await tree.SearchAsync([], simulation.RootKey, budget, budget);
                    rootAction = pureResult.Action;
                    completedSimulations = pureResult.CompletedSimulations;
                    retainedVisits = pureResult.RetainedVisits;
                    statistics = pureResult.Statistics;
                    rebuilt = pureResult.Rebuilt;
                    searchMode = "pure-mcts";
                }
                var predictedSimulation = simulation.PredictSuccessor(rootAction);
                var selectedAction = session.ToLiveSearchAction(rootAction);
                await CombatSolverMctsBenchmark.WaitForDecisionBudgetAsync(decisionWatch, budget, CancellationToken.None);
                // Keep both transport identities. The live controller records
                // a compact descriptor key, while pondered results carry the
                // immutable full card identity key.
                returnedActions[selectedAction.Key] = rootAction;
                returnedActions[rootAction.Key] = rootAction;
                await session.ApplyAsync(selectedAction, CancellationToken.None);
                var nextStateKey = session.Terminal ? null : session.StateKey();
                bool predictionMatched = true;
                if (!session.Terminal && !session.HasPendingChoice)
                {
                    string actualContinuation = CombatSolver.Api.NativeMctsSimulationApi
                        .CaptureLiveContinuationKey(session.CombatStateForSimulation);
                    if (actualContinuation != predictedSimulation.ContinuationKey)
                    {
                        predictionMatched = false;
                        Console.Error.WriteLine(
                            $"[SlayTheModel] Combat Solver continuation mismatch; rebuilding from native state. "
                            + $"predicted={predictedSimulation.ContinuationKey} actual={actualContinuation}");
                        simulation.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
                        session.BindTrajectoryRewardContext(simulation.RewardContext);
                        tree.Reset();
                        returnedActions.Clear();
                    }
                }
                response = new NativeMctsResponse(request.Id, selectedAction, null,
                    completedSimulations, retainedVisits, decisionWatch.Elapsed.TotalMilliseconds,
                    rebuilt || !predictionMatched, nextStateKey,
                    simulation.Transitions - transitionsBefore,
                    simulation.Transitions - transitionsBefore,
                    "combat_solver", searchMode,
                    networkPriorCalls, networkValueCalls, networkFallbacks, networkFallbackReason);
            }
            catch (Exception exception)
            {
                tree.Reset();
                returnedActions.Clear();
                response = new NativeMctsResponse(request.Id, null, exception.ToString());
            }
            var output = Path.Combine(directory, $"{request.Id}.json");
            File.WriteAllText(output + ".tmp", JsonSerializer.Serialize(response));
            File.Move(output + ".tmp", output, true);
        }
    }

}
