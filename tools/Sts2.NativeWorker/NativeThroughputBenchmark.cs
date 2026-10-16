using System.Diagnostics;
using System.Text.Json;

/// <summary>Measures sequential native decisions without the game scene or terminal transport.</summary>
public static class NativeThroughputBenchmark
{
    private static readonly string[] Seeds =
    [
        "STM-THROUGHPUT-WARMUP",
        "STM-THROUGHPUT-1",
        "STM-THROUGHPUT-2",
        "STM-THROUGHPUT-3",
    ];

    public static async Task RunAsync(NativeSession session, string output, CancellationToken cancellation)
    {
        var runs = new List<object>();
        for (int index = 0; index < Seeds.Length; index++)
        {
            string seed = Seeds[index];
            session.Checkpoint = null;
            session.ChoiceFixture = false;
            session.EncounterId = "CULTISTS_NORMAL";

            var reset = Stopwatch.StartNew();
            await session.ResetAsync(seed, cancellation);
            reset.Stop();

            var actionMs = new List<double>();
            var steps = Stopwatch.StartNew();
            while (!session.Terminal && actionMs.Count < 200)
            {
                var actions = session.Actions();
                if (actions.Count == 0)
                    throw new InvalidOperationException("Native combat has no legal action at a decision boundary.");
                var action = session.AttackFirst(actions);
                var step = Stopwatch.StartNew();
                await session.StepAsync(action, cancellation);
                actionMs.Add(step.Elapsed.TotalMilliseconds);
            }
            steps.Stop();

            if (index == 0) continue; // Exclude JIT and resource warm-up from measured runs.
            actionMs.Sort();
            var run = new
            {
                seed,
                terminal = session.Terminal,
                won = session.Won,
                decisions = actionMs.Count,
                resetMs = reset.Elapsed.TotalMilliseconds,
                actionsMs = steps.Elapsed.TotalMilliseconds,
                decisionsPerSecond = actionMs.Count / steps.Elapsed.TotalSeconds,
                p50ActionMs = Percentile(actionMs, 0.50),
                p95ActionMs = Percentile(actionMs, 0.95),
                maxActionMs = actionMs.Count == 0 ? 0 : actionMs[^1],
            };
            runs.Add(run);
            Godot.GD.Print("NATIVE_THROUGHPUT " + JsonSerializer.Serialize(run));
        }

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(new
        {
            generatedAtUtc = DateTimeOffset.UtcNow,
            backend = "native sts2 TestMode / NonInteractiveMode",
            encounter = "CULTISTS_NORMAL",
            policy = "attack-first",
            warmupSeed = Seeds[0],
            runs,
        }, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static double Percentile(IReadOnlyList<double> sorted, double fraction)
        => sorted.Count == 0 ? 0 : sorted[(int)Math.Ceiling((sorted.Count - 1) * fraction)];
}
