using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;
using CombatSolver.Api;

internal static class GamblingChipVerification
{
    internal static async Task RunAsync(NativeSession session, CancellationToken cancellation)
    {
        session.EnterRoomForVerification = async (run, encounter) =>
        {
            run.Players.Single().AddRelicInternal(ModelDb.Relic<GamblingChip>().ToMutable());
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
        };
        await session.ResetAsync("GAMBLING-CHIP", cancellation);
        session.EnterRoomForVerification = null;
        if (!session.HasPendingChoice) throw new InvalidDataException("Expected opening chip choice.");
        var checkpoint = NativeCombatCheckpoint.Latest ?? throw new InvalidDataException("Missing checkpoint.");
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_EXE", Godot.OS.GetExecutablePath());
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_PROJECT", Godot.ProjectSettings.GlobalizePath("res://"));
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_EXPORT_DIR", Path.Combine(Path.GetDirectoryName(Godot.OS.GetExecutablePath())!, "verification"));
        using var client = new NativeWorkerClient();
        var response = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint,
            [], session.StateKey(), session.Hp, BudgetMilliseconds: 500), cancellation);
        if (response.Action?.Selection == null) throw new InvalidDataException("Expected chip selection.");
        await session.StepAsync(response.Action, cancellation);
        if (session.StateKey() != response.NextStateKey) throw new InvalidDataException("Chip result differs.");
        Godot.GD.Print("SLAY_WORKER_GAMBLING_MATCH opening choice IPC and native result");
        var next = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint,
            [response.Action], session.StateKey(), session.Hp, BudgetMilliseconds: 500,
            PreviousAction: response.Action), cancellation);
        if (next.Action?.Combat == null) throw new InvalidDataException("Expected play after chip choice.");
        await session.StepAsync(next.Action, cancellation);
        if (session.StateKey() != next.NextStateKey) throw new InvalidDataException("Follow-up play differs.");
        Godot.GD.Print("SLAY_WORKER_GAMBLING_PLAY_MATCH warm worker continues after choice");

        session.Checkpoint = checkpoint;
        session.CaptureOpeningRoot = true;
        await session.RestoreAsync([], cancellation);
        session.CaptureOpeningRoot = false;
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.OpeningRoot!, session.Hp);
        if (simulation.ChoiceSignature != session.ChoiceSignature)
            throw new InvalidDataException("Opening options differ.");
        session.ValidateSimulationActions(simulation.LegalActions());
        var choices = simulation.LegalActions();
        int maximum = choices.Max(action => action.Native.SelectedCards!.Count);
        foreach (int count in new[] { 0, 2, maximum })
        {
            await session.RestoreAsync([], cancellation);
            await simulation.RestoreAsync([], cancellation);
            var choice = simulation.LegalActions().First(action => action.Native.SelectedCards!.Count == count);
            var live = session.ToLiveSearchAction(choice);
            await simulation.ApplyAsync(choice, cancellation);
            await session.StepAsync(live, cancellation);
            if (simulation.CurrentContinuationKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation))
                throw new InvalidDataException($"Chip discard {count} full continuation differs.");
            Godot.GD.Print($"SLAY_WORKER_GAMBLING_SUBSET_MATCH count={count} full continuation, piles and RNG");
        }
    }
}
