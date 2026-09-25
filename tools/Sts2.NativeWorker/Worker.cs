using Godot;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Unlocks;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Rooms;
using CombatSolver.Api;
using CombatSolver;
using System.Reflection;
using System.Security.Cryptography;

public partial class Worker : Node
{
    public override async void _Ready()
    {
        try
        {
            GD.Print("SLAY_WORKER_READY user=" + OS.GetUserDataDir());
            TestMode.IsOn = true;
            NonInteractiveMode.AutoSlayerCheck = () => true;
            MegaCrit.Sts2.Core.Context.LocalContext.NetId = 1;
            var pack = System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")
                ?? throw new InvalidOperationException("STS2_GAME_PACK is required.");
            if (!ProjectSettings.LoadResourcePack(pack, false)) throw new IOException("Cannot load game pack.");
            await OneTimeInitialization.ExecuteVeryEarly();
            MegaCrit.Sts2.Core.Saves.SaveManager.Instance.InitPrefsDataForTest();
            MegaCrit.Sts2.Core.Saves.SaveManager.Instance.InitProfileId();
            OneTimeInitialization.ExecuteEssential();
            MegaCrit.Sts2.Core.Saves.SaveManager.Instance.InitProgressData();
            NativeReplayCompatibilityPatches.Install();
            NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.EnableCapture();
            PrintAssemblyIdentity("NativeWorker", typeof(Worker).Assembly);
            PrintAssemblyIdentity("Search", typeof(SlayTheModel.Search.ReplayMcts<>).Assembly);
            PrintAssemblyIdentity("CombatSolver", typeof(NativeMctsSimulationApi).Assembly);
            var configuredExportPath = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_OUT");
            GD.Print("SLAY_WORKER_EXPORT_OUT="
                + (configuredExportPath is null ? "<unset>" : Path.GetFullPath(configuredExportPath)));
            GD.Print("SLAY_WORKER_SEARCH_CONFIG"
                + " mode=" + (System.Environment.GetEnvironmentVariable("STS2_ALPHAZERO_SEARCH_MODE") ?? "<unset>")
                + " maxSimulations=" + (System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MAX_SIMULATIONS") ?? "<unset>")
                + " budgetMilliseconds=" + (System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_BUDGET_MS") ?? "<unset>"));
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(10));
            var session = new NativeSession(this);
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "solver-mcts-diagnosis")
            {
                string rootKind = System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_ROOT")
                    ?? throw new InvalidDataException("STS2_MCTS_DIAG_ROOT is required.");
                string output = System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_OUT")
                    ?? throw new InvalidDataException("STS2_MCTS_DIAG_OUT is required.");
                session.Seed = System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_SEED")
                    ?? throw new InvalidDataException("STS2_MCTS_DIAG_SEED is required.");
                session.EncounterId = "CULTISTS_NORMAL";
                session.ChoiceFixture = rootKind != "ordinary";
                session.ChoiceFixtureCards = rootKind switch
                {
                    "ordinary" => session.ChoiceFixtureCards,
                    "purity" => ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"],
                    "cascade-second" => ["CASCADE", "CASCADE", "CASCADE", "PREPARED", "PREPARED",
                        "PREPARED", "PREPARED", "PREPARED", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"],
                    _ => throw new InvalidDataException("Unsupported MCTS diagnosis root: " + rootKind),
                };
                string? checkpointIn = System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_CHECKPOINT_IN");
                string? checkpointOut = System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_CHECKPOINT_OUT");
                if (checkpointIn != null)
                    session.Checkpoint = System.Text.Json.JsonSerializer.Deserialize<
                        SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint>(File.ReadAllText(checkpointIn))
                        ?? throw new InvalidDataException("Diagnosis checkpoint is empty.");
                double startupMilliseconds = (DateTime.Now
                    - System.Diagnostics.Process.GetCurrentProcess().StartTime).TotalMilliseconds;
                var resetWatch = System.Diagnostics.Stopwatch.StartNew();
                await session.ResetAsync(session.Seed, timeout.Token);
                resetWatch.Stop();
                var diagnosticCheckpoint = session.Checkpoint
                    ?? SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.Latest
                    ?? throw new InvalidDataException("Diagnosis entry checkpoint was not captured.");
                if (checkpointOut != null)
                {
                    using var stream = new System.IO.FileStream(checkpointOut,
                        System.IO.FileMode.CreateNew, System.IO.FileAccess.Write);
                    System.Text.Json.JsonSerializer.Serialize(stream, diagnosticCheckpoint);
                }
                if (System.Environment.GetEnvironmentVariable("STS2_MCTS_DIAG_POLICY_VALUE") == "1")
                    await FrozenRootPolicyValueDiagnosis.RunAsync(session, rootKind, output, timeout.Token,
                        diagnosticCheckpoint);
                else
                    await MctsThroughputDiagnosis.RunAsync(session, rootKind, output, timeout.Token,
                        resetWatch.Elapsed.TotalMilliseconds, startupMilliseconds, diagnosticCheckpoint);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "verify-choices")
            {
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                await NativeVerification.ChoicesAsync(session, timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "verify-headbutt")
            {
                var output = System.Environment.GetEnvironmentVariable("STS2_HEADBUTT_DIAG_OUT")
                    ?? throw new InvalidDataException("STS2_HEADBUTT_DIAG_OUT is required.");
                await NativeVerification.HeadbuttAsync(session, Path.GetFullPath(output), timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "verify-cross-root")
            {
                var output = System.Environment.GetEnvironmentVariable("STS2_CROSS_ROOT_DIAG_OUT")
                    ?? throw new InvalidDataException("STS2_CROSS_ROOT_DIAG_OUT is required.");
                await NativeVerification.CrossRootAsync(session, Path.GetFullPath(output), timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "verify-enemy-damage")
            {
                var output = System.Environment.GetEnvironmentVariable("STS2_ENEMY_DAMAGE_DIAG_OUT")
                    ?? throw new InvalidDataException("STS2_ENEMY_DAMAGE_DIAG_OUT is required.");
                await NativeVerification.EnemyDamageAsync(session, Path.GetFullPath(output), timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "solver-mcts-export")
            {
                var midTurns = int.TryParse(System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_MID_START_TURNS"), out var parsedTurns)
                    ? parsedTurns : 0;
                if (midTurns is < 0 or > 20)
                    throw new ArgumentOutOfRangeException(nameof(midTurns), "Mid-combat start turns must be 0..20.");
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = midTurns > 0;
                var exportPath = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_OUT")
                    ?? throw new InvalidOperationException("STS2_MCTS_EXPORT_OUT is required.");
                exportPath = Path.GetFullPath(exportPath);
                var exportSeed = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_SEED") ?? "AZ-TRAIN-000";
                session.Seed = exportSeed;
                session.EncounterId = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_ENCOUNTER") ?? "CULTISTS_NORMAL";
                session.ChoiceFixture = string.Equals(
                    System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_CHOICE_FIXTURE"), "1",
                    StringComparison.Ordinal);
                if (session.ChoiceFixture && System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_FIXTURE_CARDS") is { Length: > 0 } fixtureCards)
                    session.ChoiceFixtureCards = fixtureCards.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
                if (System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_GENERATED_SCENARIO") is { } generatedPath)
                {
                    if (midTurns != 0 || session.ChoiceFixture || string.IsNullOrWhiteSpace(generatedPath))
                        throw new InvalidDataException("A generated deck requires a full-combat, non-fixture export and a scenario path.");
                    generatedPath = Path.GetFullPath(generatedPath);
                    byte[] bytes = File.ReadAllBytes(generatedPath);
                    var requested = System.Text.Json.JsonSerializer.Deserialize<GeneratedCombatScenarioOptions>(
                        bytes, GeneratedCombatScenario.JsonOptions)
                        ?? throw new InvalidDataException("Generated deck scenario is empty.");
                    if (requested.CharacterCards?.Ids == null || requested.ColorlessCards?.Ids == null
                        || requested.Relics?.Ids == null || requested.Potions?.Ids == null
                        || requested.Seed != exportSeed || requested.CharacterId != "IRONCLAD"
                        || requested.EncounterId != session.EncounterId || requested.Ascension != 0
                        || requested.Mode != "Setup" || requested.IncludeStartingDeck
                        || !requested.IncludeStartingRelics || requested.IncludeAscendersBane
                        || requested.ApplyRelicObtainEffects || requested.SetupChoices != null
                        || requested.PlayerCurrentHp != null || requested.PotionSlotCount != null
                        || requested.CharacterCards.Count != requested.CharacterCards.Ids.Length
                        || requested.CharacterCards.Ids.Length == 0
                        || requested.CharacterCards.Ids.Any(string.IsNullOrWhiteSpace)
                        || requested.CharacterCards.UpgradeLevels != 0
                        || requested.ColorlessCards.Count != 0 || requested.ColorlessCards.Ids.Length != 0
                        || requested.Relics.Count != 0 || requested.Relics.Ids.Length != 0
                        || requested.Potions.Count != 0 || requested.Potions.Ids.Length != 0)
                        throw new InvalidDataException("Generated deck scenario must be an explicit A0 Ironclad deck-only Setup for this seed and encounter.");
                    // The generated-scenario catalog selects from default-act encounters;
                    // the Native worker's fixed research encounter is validated separately.
                    var resolved = GeneratedCombatScenario.Resolve(requested with
                    {
                        EncounterId = null,
                        EncounterKind = "Monster",
                    });
                    if (resolved.Encounter.RoomType != RoomType.Monster
                        || resolved.Options.CharacterCards.Ids.Where(id => id != null)
                            .Select(id => id!).SequenceEqual(requested.CharacterCards.Ids.Select(id => id!)) is false)
                        throw new InvalidDataException("Generated deck encounter or canonical card IDs differ from the request.");
                    session.GeneratedScenario = resolved;
                    session.GeneratedScenarioSpecPath = generatedPath;
                    session.GeneratedScenarioSpecSha256 = Convert.ToHexString(SHA256.HashData(bytes));
                    session.GeneratedScenarioRequestedCards = requested.CharacterCards.Ids.Select(id => id!).ToArray();
                    GD.Print($"SLAY_WORKER_GENERATED_DECK path={generatedPath} sha256={session.GeneratedScenarioSpecSha256}");
                }
                await session.ResetAsync(exportSeed, timeout.Token);
                int? initialHpFixture = null;
                if (System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_INITIAL_HP") is { Length: > 0 } hpText)
                {
                    if (midTurns > 0 || !int.TryParse(hpText, out int fixtureHp))
                        throw new InvalidDataException("Low-HP fixture must be numeric and start from a full combat.");
                    await session.SetInitialHpFixtureAsync(fixtureHp, timeout.Token);
                    initialHpFixture = fixtureHp;
                }
                object? startProvenance = null;
                if (initialHpFixture.HasValue)
                    startProvenance = new { nativeInitialHpFixture = initialHpFixture.Value,
                        entryHp = session.EntryHp, initialEnemyRawHp = session.InitialEnemyRawHp };
                if (midTurns > 0)
                {
                    var entryCheckpoint = SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.Latest
                        ?? throw new InvalidDataException("Mid-combat start requires a real entry checkpoint.");
                    SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                    var prefix = new List<SlayTheModel.Sts2.Protocol.SearchAction>();
                    for (int turn = 0; turn < midTurns; turn++)
                    {
                        if (session.Terminal || session.HasPendingChoice)
                            throw new InvalidDataException("Mid-combat start ended before requested settled turns.");
                        var endTurn = session.Actions().SingleOrDefault(action =>
                            action.Combat?.Kind == SlayTheModel.Sts2.Protocol.CombatActionKind.EndTurn)
                            ?? throw new InvalidDataException("Mid-combat start has no legal EndTurn action.");
                        prefix.Add(endTurn);
                        await session.StepAsync(endTurn, timeout.Token);
                    }
                    if (session.Terminal || session.HasPendingChoice)
                        throw new InvalidDataException("Mid-combat start did not reach a legal decision.");
                    string expectedKey = session.StateKey();
                    string expectedContinuation = NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation);
                    session.Checkpoint = entryCheckpoint;
                    await session.RestoreAsync(prefix, timeout.Token);
                    string actualContinuation = NativeMctsSimulationApi.CaptureLiveContinuationKey(session.CombatStateForSimulation);
                    if (session.StateKey() != expectedKey || actualContinuation != expectedContinuation)
                        throw new InvalidDataException("Checkpoint/prefix reconstruction differs at mid-combat start.");
                    session.BeginTrajectoryAtCurrentState();
                    startProvenance = new { replayVerified = true, midTurns, rootKey = expectedKey,
                        entryHp = session.EntryHp, initialEnemyRawHp = session.InitialEnemyRawHp,
                        prefix = prefix.Select(action => action.Key).ToArray() };
                }
                var exportBudget = int.TryParse(System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_BUDGET_MS"), out var parsedBudget) ? parsedBudget : 1000;
                await CombatSolverMctsBenchmark.ExportTrajectoryAsync(session, exportPath, exportBudget, timeout.Token,
                    midTurns > 0 ? "mid_combat_verified" : "full_combat", startProvenance);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "solver-mcts-benchmark")
            {
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                foreach (var type in Enum.GetValues<MegaCrit.Sts2.Core.Logging.LogType>())
                    MegaCrit.Sts2.Core.Logging.Logger.SetLogLevelForType(type, MegaCrit.Sts2.Core.Logging.LogLevel.Warn);
                await CombatSolverMctsBenchmark.RunAsync(session,
                    System.Environment.GetEnvironmentVariable("STS2_BENCHMARK_OUT") ?? "solver-mcts-benchmark.json",
                    timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "serve")
            {
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                foreach (var type in Enum.GetValues<MegaCrit.Sts2.Core.Logging.LogType>())
                    MegaCrit.Sts2.Core.Logging.Logger.SetLogLevelForType(type, MegaCrit.Sts2.Core.Logging.LogLevel.Warn);
                await WorkerServer.RunAsync(this, session,
                    System.Environment.GetEnvironmentVariable("STS2_WORKER_INBOX")!,
                    int.Parse(System.Environment.GetEnvironmentVariable("STS2_WORKER_PARENT")!));
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "az-server-smoke")
            {
                var smokePath = System.Environment.GetEnvironmentVariable("STS2_AZ_SERVER_VERIFY_OUT")
                    ?? throw new InvalidOperationException("STS2_AZ_SERVER_VERIFY_OUT is required.");
                session.Seed = "AZ-SERVER-SMOKE";
                session.EncounterId = "CULTISTS_NORMAL";
                await session.ResetAsync(session.Seed, timeout.Token);
                var smokeCheckpoint = SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.Latest
                    ?? throw new InvalidOperationException("Combat checkpoint was not captured.");
                var directory = smokePath + ".ipc";
                Directory.CreateDirectory(directory);
                var id = Guid.NewGuid();
                var request = new SlayTheModel.Sts2.ModAdapter.NativeMctsRequest(
                    id, smokeCheckpoint, [], session.StateKey(), session.EntryHp,
                    BudgetMilliseconds: 1000);
                var requestPath = Path.Combine(directory, id + ".request.json");
                File.WriteAllText(requestPath + ".tmp", System.Text.Json.JsonSerializer.Serialize(request));
                File.Move(requestPath + ".tmp", requestPath);
                var serverTask = WorkerServer.RunAsync(this, new NativeSession(this), directory,
                    System.Environment.ProcessId);
                var responsePath = Path.Combine(directory, id + ".json");
                while (!File.Exists(responsePath) && !serverTask.IsFaulted)
                    await Task.Delay(20, timeout.Token);
                if (serverTask.IsFaulted) await serverTask;
                var response = System.Text.Json.JsonSerializer.Deserialize<SlayTheModel.Sts2.ModAdapter.NativeMctsResponse>(
                    File.ReadAllText(responsePath)) ?? throw new InvalidDataException("Empty IPC response.");
                if (response.Error != null || response.Action == null || response.Simulations <= 0
                    || response.SearchMilliseconds < 900 || response.SimulatorBackend != "combat_solver")
                    throw new InvalidDataException("AlphaZero IPC smoke failed: " + System.Text.Json.JsonSerializer.Serialize(response));
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(smokePath))!);
                File.WriteAllText(smokePath, System.Text.Json.JsonSerializer.Serialize(response,
                    new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
                GD.Print($"SLAY_WORKER_ALPHAZERO_SERVER_SMOKE_MATCH simulations={response.Simulations} ms={response.SearchMilliseconds:F0} action={response.Action.Key}");
                GetTree().Quit();
                return;
            }
            await session.ResetAsync("SLAYMODEL1", timeout.Token);
            var initial = session.Fingerprint();
            var checkpoint = SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.Latest
                ?? throw new InvalidOperationException("Checkpoint hook did not fire.");
            var action = session.Actions()[0];
            await session.StepAsync(action, timeout.Token);
            var after = session.Fingerprint();
            await session.ResetAsync("SLAYMODEL1", timeout.Token);
            if (initial != session.Fingerprint()) throw new InvalidDataException("Initial reconstruction diverged.");
            await session.StepAsync(action, timeout.Token);
            if (after != session.Fingerprint()) throw new InvalidDataException("Action replay diverged.");
            GD.Print("SLAY_WORKER_REPLAY_MATCH");
            session.Checkpoint = checkpoint;
            await session.ResetAsync("SLAYMODEL1", timeout.Token);
            if (initial != session.Fingerprint()) throw new InvalidDataException("Serialized checkpoint reconstruction diverged.");
            await session.StepAsync(action, timeout.Token);
            if (after != session.Fingerprint()) throw new InvalidDataException("Serialized checkpoint action diverged.");
            GD.Print("SLAY_WORKER_CHECKPOINT_MATCH");
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
            session.Checkpoint = null;
            for (var i = 0; i < 250 && !session.Terminal; i++)
                await session.StepAsync(session.Heuristic(session.Actions()), timeout.Token);
            GD.Print($"SLAY_WORKER_RESULT terminal={session.Terminal} won={session.Won} hp={session.Hp} round={session.Round}");
            MegaCrit.Sts2.Core.Logging.Logger.GlobalLogLevel = MegaCrit.Sts2.Core.Logging.LogLevel.Warn;
            foreach (var logType in Enum.GetValues<MegaCrit.Sts2.Core.Logging.LogType>())
                MegaCrit.Sts2.Core.Logging.Logger.SetLogLevelForType(logType, MegaCrit.Sts2.Core.Logging.LogLevel.Warn);
            await NativeVerification.CombatSolverEndTurnAsync(session, timeout.Token);
            await NativeVerification.ChoicesAsync(session, timeout.Token);
            await NativeVerification.IpcAsync(session, checkpoint, timeout.Token);
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "benchmark")
                await Benchmark.RunAsync(session, System.Environment.GetEnvironmentVariable("STS2_BENCHMARK_OUT") ?? "benchmark.json", timeout.Token);
            GetTree().Quit();
        }
        catch (Exception exception)
        {
            GD.PrintErr("SLAY_WORKER_FAILED " + exception);
            GetTree().Quit(1);
        }
    }

    private static void PrintAssemblyIdentity(string label, Assembly assembly)
    {
        string path = assembly.Location;
        string hash = File.Exists(path)
            ? Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)))
            : "<missing>";
        GD.Print($"SLAY_WORKER_ASSEMBLY label={label} path={path} mvid={assembly.ManifestModule.ModuleVersionId:D} sha256={hash}");
    }
}
