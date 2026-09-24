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
            GD.Print("SLAY_WORKER_EXPORT_OUT="
                + (System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_OUT") ?? "<unset>"));
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(10));
            var session = new NativeSession(this);
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "verify-choices")
            {
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                await NativeVerification.ChoicesAsync(session, timeout.Token);
                GetTree().Quit();
                return;
            }
            if (System.Environment.GetEnvironmentVariable("STS2_WORKER_MODE") == "solver-mcts-export")
            {
                SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
                var exportPath = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_OUT")
                    ?? throw new InvalidOperationException("STS2_MCTS_EXPORT_OUT is required.");
                var exportSeed = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_SEED") ?? "AZ-TRAIN-000";
                session.Seed = exportSeed;
                session.EncounterId = System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_ENCOUNTER") ?? "CULTISTS_NORMAL";
                session.ChoiceFixture = string.Equals(
                    System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_CHOICE_FIXTURE"), "1",
                    StringComparison.Ordinal);
                if (session.ChoiceFixture && System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_FIXTURE_CARDS") is { Length: > 0 } fixtureCards)
                    session.ChoiceFixtureCards = fixtureCards.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
                await session.ResetAsync(exportSeed, timeout.Token);
                var exportBudget = int.TryParse(System.Environment.GetEnvironmentVariable("STS2_MCTS_EXPORT_BUDGET_MS"), out var parsedBudget) ? parsedBudget : 1000;
                await CombatSolverMctsBenchmark.ExportTrajectoryAsync(session, exportPath, exportBudget, timeout.Token);
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
