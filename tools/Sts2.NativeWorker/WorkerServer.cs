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
            var path = Path.Combine(directory, "request.json");
            if (!File.Exists(path))
            {
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                continue;
            }
            var request = JsonSerializer.Deserialize<NativeMctsRequest>(File.ReadAllText(path))
                ?? throw new InvalidDataException("Empty worker request.");
            File.Delete(path);
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
                var result = await tree.SearchAsync(request.Prefix, request.StateKey,
                    TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(1));
                response = new NativeMctsResponse(request.Id, result.Action, null, result.CompletedSimulations,
                    result.RetainedVisits, result.ElapsedMilliseconds, result.Rebuilt);
                tree.Advance(result.Action);
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
