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
        var tree = new ReplayMcts<SearchAction>(session);
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
                    checkpointKey = request.Checkpoint.RunPacket;
                }
                session.Checkpoint = request.Checkpoint;
                session.EntryHp = request.EntryHp;
                if (request.PreviousAction != null) tree.Advance(request.PreviousAction);
                if (request.BudgetMilliseconds is < 50 or > 10_000)
                    throw new InvalidDataException("Search budget must be between 50 and 10000 ms.");
                var budget = TimeSpan.FromMilliseconds(request.BudgetMilliseconds);
                var result = await tree.SearchAsync(request.Prefix, request.StateKey,
                    budget, budget);
                await session.RestoreAsync(request.Prefix, CancellationToken.None);
                if (session.StateKey() != request.StateKey)
                    throw new InvalidDataException("Native reconstruction changed after search.");
                await session.ApplyAsync(result.Action, CancellationToken.None);
                var nextStateKey = session.Terminal ? null : session.StateKey();
                response = new NativeMctsResponse(request.Id, result.Action, null, result.CompletedSimulations,
                    result.RetainedVisits, result.ElapsedMilliseconds, result.Rebuilt, nextStateKey);
            }
            catch (Exception exception)
            {
                tree.Reset();
                response = new NativeMctsResponse(request.Id, null, exception.ToString());
            }
            var output = Path.Combine(directory, $"{request.Id}.json");
            File.WriteAllText(output + ".tmp", JsonSerializer.Serialize(response));
            File.Move(output + ".tmp", output, true);
        }
    }
}
