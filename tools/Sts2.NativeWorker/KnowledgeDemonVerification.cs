using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;

internal static class KnowledgeDemonVerification
{
    internal static async Task RunAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.EncounterId = "KNOWLEDGE_DEMON_BOSS";
        await session.ResetAsync("KNOWLEDGE-DEMON-CHOICE", cancellation);
        var checkpoint = NativeCombatCheckpoint.Latest ?? throw new InvalidDataException("Missing knowledge checkpoint.");
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        var end = simulation.LegalActions().Single(action => action.Native.Kind == "EndTurn");
        await simulation.ApplyAsync(end, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(end), cancellation);
        if (!session.HasPendingChoice || simulation.ChoiceSignature != session.ChoiceSignature)
            throw new InvalidDataException($"Knowledge choice mismatch: native={session.ChoiceSignature} simulated={simulation.ChoiceSignature}");
        session.ValidateSimulationActions(simulation.LegalActions());
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_EXE", Godot.OS.GetExecutablePath());
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_PROJECT", Godot.ProjectSettings.GlobalizePath("res://"));
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_EXPORT_DIR", Path.Combine(Path.GetDirectoryName(Godot.OS.GetExecutablePath())!, "verification"));
        using (var client = new NativeWorkerClient())
        {
            var response = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint,
                [session.ToLiveSearchAction(end)], session.StateKey(), 80, BudgetMilliseconds: 500), cancellation);
            if (response.Action?.Selection?.Length != 1)
                throw new InvalidDataException("Restarted worker must recover the mandatory curse choice.");
            Godot.GD.Print("SLAY_WORKER_KNOWLEDGE_RESTART_MATCH cold worker recovered at enemy choice");
        }
        var choice = simulation.LegalActions().First();
        var liveChoice = session.ToLiveSearchAction(choice);
        await simulation.ApplyAsync(choice, cancellation);
        await session.StepAsync(liveChoice, cancellation);
        if (simulation.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation))
            throw new InvalidDataException("Knowledge curse result differs from native execution.");
        Godot.GD.Print("SLAY_WORKER_KNOWLEDGE_CHOICE_MATCH end turn, curse choice and full continuation");
        await AllCurseRoundsAsync(session, cancellation);
        session.EncounterId = "CULTISTS_NORMAL";
        await NativeVerification.ChoicesAsync(session, cancellation);
    }

    private static async Task AllCurseRoundsAsync(NativeSession session, CancellationToken cancellation)
    {
        foreach (bool disintegration in new[] { true, false })
        {
            session.Checkpoint = null;
            session.EnterRoomForVerification = async (run, encounter) =>
            {
                await CreatureCmd.SetMaxHp(run.Players.Single().Creature, 1000);
                await CreatureCmd.SetCurrentHp(run.Players.Single().Creature, 1000);
                await RunManager.Instance.EnterRoomDebug(RoomType.Boss, model: encounter);
            };
            await session.ResetAsync("KNOWLEDGE-DEMON-ALL-CURSES", cancellation);
            session.EnterRoomForVerification = null;
            int choices = 0;
            for (int turn = 0; turn < 9; turn++)
            {
                using var prediction = new CombatSolverReplayEnvironment();
                prediction.Capture(session.CombatStateForSimulation, 1000);
                var endTurn = prediction.LegalActions().Single(action => action.Native.Kind == "EndTurn");
                await prediction.ApplyAsync(endTurn, cancellation);
                await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
                if (session.HasPendingChoice)
                {
                    if (prediction.ChoiceSignature != session.ChoiceSignature)
                        throw new InvalidDataException("Later curse options differ from native.");
                    session.ValidateSimulationActions(prediction.LegalActions());
                    var selected = prediction.LegalActions().Single(action =>
                        (action.Native.SelectedCards!.Single().CardId == "DISINTEGRATION") == disintegration);
                    if (selected.Native.KnowledgeCurseCounter != choices)
                        throw new InvalidDataException("Curse phase was not preserved.");
                    var live = session.ToLiveSearchAction(selected);
                    await prediction.ApplyAsync(selected, cancellation);
                    await session.StepAsync(live, cancellation);
                    choices++;
                }
                if (prediction.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation))
                    throw new InvalidDataException($"Curse route diverged at turn {turn + 1}, disintegration={disintegration}.");
            }
            if (choices != 3) throw new InvalidDataException("Expected all three curse phases.");
            Godot.GD.Print($"SLAY_WORKER_KNOWLEDGE_PHASES_MATCH disintegration={disintegration}, three phases, nine turns, full continuation matched");
        }
    }
}
