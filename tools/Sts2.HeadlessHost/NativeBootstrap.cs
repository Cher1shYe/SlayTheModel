using System.Reflection;
using System.Text;
using Godot;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Timeline;

namespace SlayTheModel.Headless;

/// <summary>Loads the complete native scene tree inside an isolated, displayless Godot process.</summary>
public static class NativeBootstrap
{
    public static async Task InitializeAsync(Node host)
    {
        await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        string expected = Path.GetFullPath(System.Environment.GetEnvironmentVariable("STS2_HEADLESS_USER_DIR")
            ?? throw new InvalidOperationException("Use the headless launcher to configure an isolated user directory."));
        string actual = Path.GetFullPath(OS.GetUserDataDir());
        if (!string.Equals(expected, actual, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
            throw new InvalidOperationException($"Refusing to start with user data outside the isolated directory: {actual}");
        Console.WriteLine("SLAY_HEADLESS_USER " + actual);
        string pack = System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")
            ?? throw new InvalidOperationException("STS2_GAME_PACK is required.");
        if (!ProjectSettings.LoadResourcePack(pack, false)) throw new IOException("Could not mount the native game resource pack.");
        ApplyNativeProjectSettings();

        // Native scene scripts reside in sts2.dll. Their paths must be registered
        // before loading packed scenes into this separate Godot project.
        var bridge = typeof(Node).Assembly.GetType("Godot.Bridge.ScriptManagerBridge", true)!;
        var lookup = bridge.GetMethod("LookupScriptsInAssembly", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new MissingMethodException(bridge.FullName, "LookupScriptsInAssembly");
        lookup.Invoke(null, [typeof(NGame).Assembly]);

        if (!ClassDB.ClassExists("FmodBankLoader") || !ClassDB.ClassExists("SpineSprite"))
            throw new InvalidOperationException("The staged native FMOD/Spine extensions did not load.");
        InputMap.LoadFromProjectSettings();
        AudioServer.SetBusLayout(GD.Load<AudioBusLayout>("res://default_bus_layout.tres"));
        var fmodScript = GD.Load<Script>("res://addons/fmod/FmodManager.gd");
        if (fmodScript != null)
        {
            var fmod = new Node { Name = "FmodManager" };
            fmod.SetScript(fmodScript);
            host.GetTree().Root.AddChild(fmod);
        }
        var game = GD.Load<PackedScene>("res://scenes/game.tscn").Instantiate<NGame>();
        game.StartOnMainMenu = false;
        host.AddChild(game);
        await game.GameStartupComplete.WaitAsync(TimeSpan.FromSeconds(90));
        if (LocManager.Instance is null || !ModelDb.All.Any()
            || !SaveManager.Instance.IsProfileInitialized
            || SaveManager.Instance.PrefsSave is null || SaveManager.Instance.Progress is null)
            throw new InvalidOperationException("Native game startup did not initialize the model database.");
        if (MegaCrit.Sts2.Core.Nodes.CommonUi.NModalContainer.Instance?.OpenModal is { } startupModal)
            throw new InvalidOperationException($"Native startup opened an unexpected dialog: {startupModal.GetType().Name}. Inspect stderr.log.");
        OneTimeInitialization.ExecuteDeferred();
        // Unlocks live exclusively in the isolated test profile. Rules within a
        // run remain the game's ordinary rules, including every event model.
        foreach (string epoch in EpochModel.AllEpochIds)
            SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
        SaveManager.Instance.SetFtuesEnabled(false);
        SaveManager.Instance.PrefsSave.IsLongPressEnabled = false;
        SaveManager.Instance.PrefsSave.FastMode = MegaCrit.Sts2.Core.Settings.FastModeType.Fast;
        GD.Print("SLAY_HEADLESS_NATIVE_INITIALIZED");
    }

    public static async Task<RunState> StartNewRunAsync(string character, int ascension, string? seed, string language)
    {
        if (ascension is < 0 or > 10) throw new ArgumentOutOfRangeException(nameof(ascension));
        if (RunManager.Instance.IsInProgress)
            throw new InvalidOperationException("A run is already in progress. Restart the isolated host to begin another run.");
        var model = ModelDb.All.OfType<CharacterModel>().SingleOrDefault(candidate =>
            candidate.Id.Entry.Equals(character, StringComparison.OrdinalIgnoreCase)
            || candidate.GetType().Name.Equals(character, StringComparison.OrdinalIgnoreCase))
            ?? throw new ArgumentException($"Unknown character {character}.");
        LocManager.Instance.SetLanguage(language is "zhs" or "eng" ? language : "zhs");
        string canonicalSeed = string.IsNullOrWhiteSpace(seed) ? SeedHelper.GetRandomSeed() : SeedHelper.CanonicalizeSeed(seed);
        // Mirror StartRunLobby.BeginRunLocally, including the game's alternate
        // act selection and discovery rules, without requiring the menu lobby.
        var actRng = new MegaCrit.Sts2.Core.Random.Rng(StringHelper.GetDeterministicHashCode(canonicalSeed), "act_selection");
        var acts = ActModel.GetRandomList(actRng, SaveManager.Instance.GenerateUnlockStateFromProgress(), false).ToList();
        return await NGame.Instance!.StartNewSingleplayerRun(model, false, acts, [], canonicalSeed, GameMode.Standard, ascension);
    }

    private static void ApplyNativeProjectSettings()
    {
        using var file = Godot.FileAccess.Open("res://project.binary", Godot.FileAccess.ModeFlags.Read);
        if (Encoding.ASCII.GetString(file.GetBuffer(4)) != "ECFG")
            throw new InvalidDataException("Unexpected native project settings format.");
        uint count = file.Get32();
        for (uint i = 0; i < count; i++)
        {
            string name = Encoding.UTF8.GetString(file.GetBuffer(file.Get32()));
            byte[] value = file.GetBuffer(file.Get32());
            if (name.StartsWith("application/", StringComparison.Ordinal)
                || name.StartsWith("dotnet/", StringComparison.Ordinal)
                || name.StartsWith("autoload/", StringComparison.Ordinal)
                || name.StartsWith("sentry/", StringComparison.Ordinal)
                || name.StartsWith("debug/settings/stdout/", StringComparison.Ordinal)
                || name == "_custom_features") continue;
            ProjectSettings.SetSetting(name, GD.BytesToVarWithObjects(value));
        }
    }
}
