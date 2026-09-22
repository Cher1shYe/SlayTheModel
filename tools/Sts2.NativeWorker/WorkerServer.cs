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

                if (request.PreviousAction != null
                    && returnedActions.TryGetValue(request.PreviousAction.Key, out var previous))
                {
                    simulation.Promote(previous);
                    tree.Advance(previous);
                }
                else if (request.PreviousAction != null || returnedActions.Count == 0)
                {
                    simulation.Capture(session.CombatStateForSimulation, request.EntryHp);
                    tree.Reset();
                }

                var budget = TimeSpan.FromMilliseconds(request.BudgetMilliseconds);
                long transitionsBefore = simulation.Transitions;
                var result = await tree.SearchAsync([], simulation.RootKey, budget, budget);
                var predictedSimulation = simulation.PredictSuccessor(result.Action);
                var selectedAction = session.ToLiveSearchAction(result.Action);
                returnedActions[selectedAction.Key] = result.Action;
                await session.ApplyAsync(selectedAction, CancellationToken.None);
                var nextStateKey = session.Terminal ? null : session.StateKey();
                if (!session.Terminal && !session.HasPendingChoice)
                {
                    string actualContinuation = CombatSolver.Api.NativeMctsSimulationApi
                        .CaptureLiveContinuationKey(session.CombatStateForSimulation);
                    if (actualContinuation != predictedSimulation.ContinuationKey)
                        throw new InvalidDataException(
                            $"Combat Solver prediction differs from native execution. predicted={predictedSimulation.ContinuationKey} actual={actualContinuation}");
                }
                response = new NativeMctsResponse(request.Id, selectedAction, null,
                    result.CompletedSimulations, result.RetainedVisits, result.ElapsedMilliseconds,
                    result.Rebuilt, nextStateKey,
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
