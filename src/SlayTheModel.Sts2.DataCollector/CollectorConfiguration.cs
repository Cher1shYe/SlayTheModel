using System.Text.Json;

namespace SlayTheModel.Sts2.DataCollector;

internal enum CollectorInformationMode
{
    Auto,
    NoSl,
    Sl,
}

/// <summary>
/// Immutable process configuration for the standalone collector. The fallback
/// JSON file supports launches made directly by Steam, where a temporary shell
/// environment is not always inherited by the game process.
/// </summary>
internal sealed record CollectorConfiguration(
    bool Enabled,
    string DatasetRoot,
    CollectorInformationMode InformationMode,
    string Actor,
    string CombatPolicy = "manual",
    string OutsideCombatPolicy = "manual")
{
    internal const string EnabledVariable = "SLAY_THE_MODEL_COLLECTOR_ENABLED";
    internal const string DatasetRootVariable = "SLAY_THE_MODEL_DATASET_DIR";
    internal const string InformationModeVariable = "SLAY_THE_MODEL_INFORMATION_MODE";
    internal const string ActorVariable = "SLAY_THE_MODEL_COLLECTOR_ACTOR";
    private const string ConfigurationFileName = "SlayTheModelDataCollector.runtime.json";

    private static readonly Lazy<IReadOnlyDictionary<string, string?>> FileValues =
        new(LoadFileValues);
    private static readonly Lazy<IReadOnlyDictionary<string, string?>> AdapterFileValues =
        new(LoadAdapterFileValues);

    internal static CollectorConfiguration Load()
    {
        var enabledText = Read(EnabledVariable)?.Trim();
        var enabled = enabledText is null or "" or "1"
            || bool.TryParse(enabledText, out var parsedEnabled) && parsedEnabled;
        if (enabledText == "0")
        {
            enabled = false;
        }

        var configuredRoot = Read(DatasetRootVariable);
        var root = string.IsNullOrWhiteSpace(configuredRoot)
            ? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "SlayTheModel",
                "datasets")
            : Path.GetFullPath(configuredRoot);

        var informationMode = Normalize(Read(InformationModeVariable)) switch
        {
            "" or "auto" => CollectorInformationMode.Auto,
            "no-sl" or "nosl" => CollectorInformationMode.NoSl,
            "sl" => CollectorInformationMode.Sl,
            var value => throw new ArgumentException(
                $"Unknown {InformationModeVariable} value '{value}'; expected auto, no-sl, or sl."),
        };

        var actor = Normalize(Read(ActorVariable));
        var combatPolicyText = ReadAutomationSetting(
            "SLAY_THE_MODEL_COMBAT_POLICY");
        if (string.IsNullOrWhiteSpace(combatPolicyText))
        {
            // Older Adapter builds exposed only LIVE_POLICY. Keep checking it
            // so a legacy first-legal/MCTS launch can never be mislabeled as a
            // human demonstration merely because the interface was renamed.
            combatPolicyText = ReadAutomationSetting(
                "SLAY_THE_MODEL_LIVE_POLICY");
        }
        var combatPolicy = Normalize(combatPolicyText);
        var outsidePolicy = Normalize(ReadAutomationSetting(
            "SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY"));
        if (combatPolicy is not ("" or "manual")
            || outsidePolicy is not ("" or "manual"))
        {
            // Never let an explicit label silently turn first-legal/MCTS data
            // into a human demonstration. The sibling Adapter JSON is checked
            // because Steam launches may not carry its settings in env vars.
            actor = "automation_or_unknown";
        }
        else if (actor == "")
        {
            actor = "human";
        }
        else if (actor != "human")
        {
            throw new ArgumentException(
                $"Unknown {ActorVariable} value '{actor}'; expected human. "
                + "Automation is detected from the Adapter policy configuration.");
        }

        return new CollectorConfiguration(enabled, root, informationMode, actor,
            combatPolicy == "" ? "manual" : combatPolicy,
            outsidePolicy == "" ? "manual" : outsidePolicy);
    }

    private static string? Read(string name)
    {
        var processValue = Environment.GetEnvironmentVariable(name);
        return !string.IsNullOrWhiteSpace(processValue)
            ? processValue
            : FileValues.Value.GetValueOrDefault(name);
    }

    private static string? ReadAutomationSetting(string name)
    {
        var configured = Read(name);
        return !string.IsNullOrWhiteSpace(configured)
            ? configured
            : AdapterFileValues.Value.GetValueOrDefault(name);
    }

    private static string Normalize(string? value) =>
        value?.Trim().Replace('_', '-').ToLowerInvariant() ?? "";

    private static IReadOnlyDictionary<string, string?> LoadFileValues()
    {
        try
        {
            var directory = Path.GetDirectoryName(typeof(CollectorConfiguration).Assembly.Location);
            var path = string.IsNullOrWhiteSpace(directory)
                ? null
                : Path.Combine(directory, ConfigurationFileName);
            return path is not null && File.Exists(path)
                ? JsonSerializer.Deserialize<Dictionary<string, string?>>(File.ReadAllText(path))
                  ?? new Dictionary<string, string?>()
                : new Dictionary<string, string?>();
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] runtime configuration unavailable: {exception.Message}");
            return new Dictionary<string, string?>();
        }
    }

    private static IReadOnlyDictionary<string, string?> LoadAdapterFileValues()
    {
        try
        {
            var collectorDirectory = Path.GetDirectoryName(
                typeof(CollectorConfiguration).Assembly.Location);
            var modsDirectory = string.IsNullOrWhiteSpace(collectorDirectory)
                ? null
                : Directory.GetParent(collectorDirectory)?.FullName;
            var path = modsDirectory is null
                ? null
                : Path.Combine(
                    modsDirectory,
                    "SlayTheModelAdapter",
                    "SlayTheModelAdapter.runtime.json");
            return path is not null && File.Exists(path)
                ? JsonSerializer.Deserialize<Dictionary<string, string?>>(
                    File.ReadAllText(path)) ?? new Dictionary<string, string?>()
                : new Dictionary<string, string?>();
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(
                $"[SlayTheModel/Collector] adapter configuration unavailable: {exception.Message}");
            return new Dictionary<string, string?>();
        }
    }
}
