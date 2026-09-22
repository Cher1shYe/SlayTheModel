using System.Diagnostics;
using System.Text.Json;
using Godot;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static class WorkerServer
{
    public static async Task RunAsync(Node host, NativeSession session, string directory, int parentId)
    {
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
                if (!reused)
                {
                    if (session.HasPendingChoice)
                        throw new InvalidDataException(
                            "Cannot align the Combat Solver tree with the restored native choice boundary.");
                    // A request without PreviousAction may be a native choice boundary whose
                    // ponder key did not match. The restored session is authoritative; never
                    // search the previous play-state root at a new choice boundary.
                    simulation.Capture(session.CombatStateForSimulation, request.EntryHp);
                    tree.Reset();
                }
                session.ValidateSimulationActions(simulation.LegalActions());

                var budget = TimeSpan.FromMilliseconds(request.BudgetMilliseconds);
                long transitionsBefore = simulation.Transitions;
                var result = await tree.SearchAsync([], simulation.RootKey, budget, budget);
                var predictedSimulation = simulation.PredictSuccessor(result.Action);
                var selectedAction = session.ToLiveSearchAction(result.Action);
                // Keep both transport identities. The live controller records
                // a compact descriptor key, while pondered results carry the
                // immutable full card identity key.
                returnedActions[selectedAction.Key] = result.Action;
                returnedActions[result.Action.Key] = result.Action;
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
                        simulation.Capture(session.CombatStateForSimulation, request.EntryHp);
                        tree.Reset();
                        returnedActions.Clear();
                    }
                }
                response = new NativeMctsResponse(request.Id, selectedAction, null,
                    result.CompletedSimulations, result.RetainedVisits, result.ElapsedMilliseconds,
                    result.Rebuilt || !predictionMatched, nextStateKey,
                    simulation.Transitions - transitionsBefore,
                    simulation.Transitions - transitionsBefore,
                    "combat_solver");
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
