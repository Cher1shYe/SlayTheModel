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
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(10));
            var session = new NativeSession(this);
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
}
