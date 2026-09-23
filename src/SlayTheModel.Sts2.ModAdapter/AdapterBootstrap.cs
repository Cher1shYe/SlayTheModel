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
        AdapterConfiguration configuration;
        try
        {
            configuration = AdapterConfiguration.LoadFromEnvironment();
        }
        catch (ArgumentException exception)
        {
            configuration = AdapterConfiguration.Default;
            Console.Error.WriteLine($"[SlayTheModel] invalid launch configuration; automation disabled: {exception.Message}");
        }

        Console.WriteLine($"[SlayTheModel] configuration {configuration.Describe()}");
        if (configuration.UsedLegacyCombatPolicy)
        {
            Console.WriteLine(
                $"[SlayTheModel] {AdapterConfiguration.LegacyCombatPolicyVariable} is deprecated; "
                + $"use {AdapterConfiguration.CombatPolicyVariable} instead");
        }

        MctsCombatController.Initialize(configuration);
        LiveCombatController.Initialize(configuration);
        OutsideCombatController.Initialize(configuration);
        AiStatusOverlay.Initialize();
        var manager = CombatManager.Instance;
        manager.CombatBegan += OnCombatBegan;
        manager.CombatEnded += _ => ResetCombatServices();
        manager.StateTracker.CombatStateChanged += OnCombatStateChanged;
        Console.WriteLine("[SlayTheModel] omniscient combat capture adapter initialized");

        var autoSlaySeed = RuntimeConfiguration.Get("SLAY_THE_MODEL_AUTOSLAY_SEED");
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
