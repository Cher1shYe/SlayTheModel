using System.Diagnostics;
using System.Text.Json;
using SlayTheModel.Search;
using SlayTheModel.Sts2.Protocol;

public static class Benchmark
{
    public static async Task RunAsync(NativeSession session, string output, CancellationToken cancellation)
    {
        var results = new List<object>();
        foreach (var seed in new[] { "STM-HOLDOUT-v1-1", "STM-HOLDOUT-v1-2", "STM-HOLDOUT-v1-3" })
        {
            session.Seed = seed;
            foreach (var policy in new[] { "first-legal", "heuristic", "attack-first", "mcts" })
            {
                var elapsed = Stopwatch.StartNew();
                var prefix = new List<SearchAction>();
                var tree = new ReplayMcts<SearchAction>(session);
                var decisions = new List<object>();
                await session.RestoreAsync(prefix, cancellation);
                while (!session.Terminal && prefix.Count < 200)
                {
                    var expected = session.Fingerprint();
                    SearchAction action;
                    if (policy == "mcts")
                    {
                        var result = await tree.SearchAsync(prefix, expected, TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(1), cancellation);
                        action = result.Action;
                        decisions.Add(new { action.Key, result.CompletedSimulations, result.RetainedVisits, result.ElapsedMilliseconds, result.Rebuilt });
                        // Searching changed only the worker's scratch state. Reconstruct
                        // the real prefix before committing the selected action.
                        await session.RestoreAsync(prefix, cancellation);
                        if (session.Fingerprint() != expected) throw new InvalidDataException("Commit reconstruction diverged.");
                        tree.Advance(action);
                    }
                    else action = policy == "first-legal" ? session.Actions()[0] : policy == "attack-first" ? session.AttackFirst(session.Actions()) : session.Heuristic(session.Actions());
                    await session.StepAsync(action, cancellation);
                    prefix.Add(action);
                }
                var row = new { seed, policy, terminal = session.Terminal, won = session.Won, hp = session.Hp,
                    netHpLoss = 80 - session.Hp, rounds = session.Round, actions = prefix.Count,
                    elapsedSeconds = elapsed.Elapsed.TotalSeconds, decisions };
                results.Add(row);
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
                File.WriteAllText(output, JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }));
                Godot.GD.Print("BENCHMARK " + JsonSerializer.Serialize(row with { decisions = [] }));
            }
        }
    }
}
