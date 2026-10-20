using System.Text.Json;
using SlayTheModel.Search;

public static class CombatSolverMctsBenchmark
{
    private static readonly string[] Encounters =
    [
        "FUZZY_WURM_CRAWLER_WEAK",
        "CULTISTS_NORMAL",
        "LIVING_FOG_NORMAL",
        "PHROG_PARASITE_ELITE",
        "KAISER_CRAB_BOSS",
    ];

    public static async Task RunAsync(
        NativeSession native,
        string outputPath,
        CancellationToken cancellation)
    {
        var results = new List<object>();
        foreach (string encounter in Encounters)
        {
            native.Checkpoint = null;
            native.ChoiceFixture = false;
            native.EncounterId = encounter;
            native.Seed = "MCTS-SIM-" + encounter;
            await native.ResetAsync(native.Seed, cancellation);

            // One warm-up run is deliberately excluded from the five formal samples.
            await RunTrial(native, TimeSpan.FromSeconds(1), cancellation);
            var samples = new List<object>();
            var rates = new List<double>();
            string? error = null;
            for (int sample = 0; sample < 5; sample++)
            {
                try
                {
                    var result = await RunTrial(native, TimeSpan.FromSeconds(5), cancellation);
                    double rate = result.CompletedSimulations / (result.ElapsedMilliseconds / 1000d);
                    rates.Add(rate);
                    samples.Add(new
                    {
                        sample,
                        result.CompletedSimulations,
                        result.ElapsedMilliseconds,
                        simulationsPerSecond = rate,
                        result.RetainedVisits,
                    });
                }
                catch (Exception exception) when (exception is not OperationCanceledException)
                {
                    error = exception.ToString();
                    break;
                }
            }
            rates.Sort();
            results.Add(new
            {
                encounter,
                samples,
                median = rates.Count == 0 ? 0 : rates[rates.Count / 2],
                minimum = rates.Count == 0 ? 0 : rates[0],
                maximum = rates.Count == 0 ? 0 : rates[^1],
                stable = rates.Count == 5 && rates[0] >= 90,
                passed100 = rates.Count == 5 && rates[rates.Count / 2] >= 100,
                error,
            });
            Godot.GD.Print($"SLAY_WORKER_SOLVER_MCTS_BENCHMARK encounter={encounter} "
                + $"median={(rates.Count == 0 ? 0 : rates[rates.Count / 2]):F2} "
                + $"min={(rates.Count == 0 ? 0 : rates[0]):F2} error={(error == null ? "none" : "yes")}");
        }

        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        File.WriteAllText(outputPath, JsonSerializer.Serialize(new
        {
            generatedAtUtc = DateTimeOffset.UtcNow,
            backend = "ReplayMcts+CombatSolver",
            maxDepth = 200,
            sampleSeconds = 5,
            samplesPerEncounter = 5,
            results,
        }, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static async Task<TimedSearchResult<CombatSolverMctsAction>> RunTrial(
        NativeSession native,
        TimeSpan budget,
        CancellationToken cancellation)
    {
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(native.CombatStateForSimulation, native.EntryHp);
        var tree = new ReplayMcts<CombatSolverMctsAction>(environment, seed: 20260922);
        return await tree.SearchAsync([], environment.RootKey, budget, budget, cancellation, maxDepth: 200);
    }
}
