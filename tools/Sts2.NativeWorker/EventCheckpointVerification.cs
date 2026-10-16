using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Events;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Search;
using SlayTheModel.Sts2.ModAdapter;

internal static class EventCheckpointVerification
{
    internal static async Task RunAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.EncounterId = "DENSE_VEGETATION_EVENT_ENCOUNTER";
        session.EnterRoomForVerification = async (run, encounter) =>
        {
            var manager = RunManager.Instance;
            await manager.EnterRoomDebug(RoomType.Event, model: ModelDb.Event<DenseVegetation>());
            await CreatureCmd.SetCurrentHp(run.Players.Single().Creature, 30);
            await PlayerCmd.MimicRestSiteHeal(run.Players.Single(), playSfx: false);
            var room = new CombatRoom(encounter, run)
            {
                ParentEventId = ModelDb.Event<DenseVegetation>().Id,
                ShouldResumeParentEventAfterCombat = false
            };
            await manager.EnterRoomWithoutExitingCurrentRoom(room, fadeToBlack: false);
            if (room.IsPreFinished || room.ParentEventId != ModelDb.Event<DenseVegetation>().Id)
                throw new InvalidDataException("Checkpoint capture mutated the live event room.");
        };
        await session.ResetAsync("DENSE-VEGETATION-CHECKPOINT", cancellation);
        session.EnterRoomForVerification = null;
        if (session.CombatStateForSimulation.Enemies.Count() != 4 || session.Hp <= 30)
            throw new InvalidDataException("Expected healed player facing four Wrigglers.");
        var checkpoint = NativeCombatCheckpoint.Latest
            ?? throw new InvalidDataException("Event combat did not produce a checkpoint.");
        var roomPacket = NativeCombatCheckpoint.Decode<MegaCrit.Sts2.Core.Saves.Runs.SerializableRoom>(checkpoint.RoomPacket);
        if (roomPacket.ParentEventId != ModelDb.Event<DenseVegetation>().Id || roomPacket.IsPreFinished || roomPacket.ShouldResumeParentEvent)
            throw new InvalidDataException("Event checkpoint lost its parent or active-room metadata.");
        var key = session.StateKey();
        var continuation = NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation);
        session.Checkpoint = checkpoint;
        await session.ResetAsync("ignored", cancellation);
        if (session.StateKey() != key || NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation) != continuation)
            throw new InvalidDataException("Event checkpoint reconstruction differs from native combat.");
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        var budget = TimeSpan.FromMilliseconds(500);
        var result = await new ReplayMcts<CombatSolverMctsAction>(simulation).SearchAsync([], simulation.RootKey, budget, budget, cancellation, maxDepth: 12);
        await simulation.RestoreAsync([], cancellation);
        await simulation.ApplyAsync(result.Action, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(result.Action), cancellation);
        if (simulation.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation))
            throw new InvalidDataException("Event combat selected action diverged from native execution.");
        var endTurn = simulation.LegalActions().Single(action => action.Native.Kind == "EndTurn");
        await simulation.ApplyAsync(endTurn, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
        if (simulation.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation))
            throw new InvalidDataException("Event enemy turn differs from native execution.");
        Godot.GD.Print($"SLAY_WORKER_EVENT_CHECKPOINT_MATCH healed event entry, four enemies, exact restored state, MCTS action and enemy turn; simulations={result.CompletedSimulations}");

        session.Checkpoint = null;
        session.EncounterId = "CULTISTS_NORMAL";
        await session.ResetAsync("NORMAL-CHECKPOINT-SENTINEL", cancellation);
        key = session.StateKey();
        session.Checkpoint = NativeCombatCheckpoint.Latest ?? throw new InvalidDataException("Missing ordinary checkpoint.");
        await session.ResetAsync("ignored", cancellation);
        if (session.StateKey() != key)
            throw new InvalidDataException("Ordinary combat checkpoint regressed.");
        Godot.GD.Print("SLAY_WORKER_NORMAL_CHECKPOINT_MATCH ordinary combat round trip unchanged");
    }
}
