using System.Text.Json;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static class NativeVerification
{
    public static async Task ChoicesAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        await session.ResetAsync("CHOICE-FIXTURE", cancellation);
        var purity = session.ActionForCard("PURITY");
        await session.StepAsync(purity, cancellation);
        var choiceKey = session.Fingerprint();
        var choices = session.Actions();
        if (choices.Count != 15 || choices.Select(action => action.Key).Distinct().Count() != 15)
            throw new InvalidDataException("Purity should expose all 15 subsets of up to 3 of 4 cards.");
        var exhaust = choices.First(action => action.Selection?.Length == 3);
        await session.StepAsync(exhaust, cancellation);
        var exhaustedKey = session.Fingerprint();
        await session.RestoreAsync("CHOICE-FIXTURE", [purity], cancellation);
        if (session.Fingerprint() != choiceKey) throw new InvalidDataException("Pending choice replay diverged.");
        await session.StepAsync(exhaust, cancellation);
        if (session.Fingerprint() != exhaustedKey) throw new InvalidDataException("Choice effect replay diverged.");
        await session.RestoreAsync("CHOICE-FIXTURE", [purity], cancellation);
        await session.StepAsync(session.Actions().First(action => action.Selection?.Length == 0), cancellation);
        if (session.Fingerprint() == exhaustedKey) throw new InvalidDataException("Different selections collapsed to one state.");
        await session.StepAsync(session.ActionForCard("ARMAMENTS"), cancellation);
        if (!session.Actions().All(action => action.Selection?.Length == 1)) throw new InvalidDataException("Required upgrade choice missing.");
        await session.StepAsync(session.Actions()[0], cancellation);
        session.ChoiceFixture = false;
        Godot.GD.Print("SLAY_WORKER_CHOICES_MATCH purity=15 branches; alternate branch isolated; armaments resolved");
    }

    public static async Task IpcAsync(NativeSession session, NativeCombatCheckpoint checkpoint, CancellationToken cancellation)
    {
        session.Checkpoint = checkpoint;
        await session.RestoreAsync([], cancellation);
        var before = session.Fingerprint();
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_EXE", Godot.OS.GetExecutablePath());
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_PROJECT", Godot.ProjectSettings.GlobalizePath("res://"));
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_EXPORT_DIR", Path.Combine(Path.GetDirectoryName(Godot.OS.GetExecutablePath())!, "verification"));
        using var client = new NativeWorkerClient();
        var response = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, [], before, 80), cancellation);
        if (before != session.Fingerprint()) throw new InvalidDataException("Child search changed parent state.");
        var action = response.Action ?? throw new InvalidDataException("IPC returned no action.");
        await session.StepAsync(action, cancellation);
        var second = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, [action], session.Fingerprint(), 80), cancellation);
        if (second.Rebuilt || second.RetainedVisits == 0) throw new InvalidDataException("IPC did not retain the matching subtree.");
        Godot.GD.Print("SLAY_WORKER_IPC_MATCH " + JsonSerializer.Serialize(new { response.SearchMilliseconds, nextMilliseconds = second.SearchMilliseconds, second.RetainedVisits }));
        session.Checkpoint = null;
    }
}
