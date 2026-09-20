using MegaCrit.Sts2.Core.AutoSlay;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Modding;

namespace SlayTheModel.Sts2.ModAdapter;

[ModInitializer(nameof(Initialize))]
public static class AdapterBootstrap
{
    private static bool _initialized;

    public static void Initialize()
    {
        if (_initialized)
        {
            return;
        }

        _initialized = true;
        MctsCombatController.Initialize();
        LiveCombatController.Initialize();
        AiStatusOverlay.Initialize();
        var manager = CombatManager.Instance;
        manager.CombatBegan += OnCombatBegan;
        manager.CombatEnded += _ => ResetCombatServices();
        manager.StateTracker.CombatStateChanged += OnCombatStateChanged;
        Console.WriteLine("[SlayTheModel] omniscient combat capture adapter initialized");

        var autoSlaySeed = Environment.GetEnvironmentVariable("SLAY_THE_MODEL_AUTOSLAY_SEED");
        if (!string.IsNullOrWhiteSpace(autoSlaySeed))
        {
            var outputDirectory = CombatCaptureService.GetOutputDirectory();
            Directory.CreateDirectory(outputDirectory);
            var logPath = Path.Combine(outputDirectory, $"autoslay-{autoSlaySeed}.log");
            Console.WriteLine($"[SlayTheModel] starting AutoSlay seed={autoSlaySeed}");
            new AutoSlayer().Start(autoSlaySeed, logPath);
        }
    }

    private static void OnCombatBegan(CombatState state)
    {
        ResetCombatServices();
        OnCombatStateChanged(state);
    }

    private static void OnCombatStateChanged(CombatState state)
    {
        CombatCaptureService.TryCapture(state);
        LiveCombatController.TrySchedule(state);
    }

    private static void ResetCombatServices()
    {
        CombatCaptureService.Reset();
        LiveCombatController.Reset();
    }
}
