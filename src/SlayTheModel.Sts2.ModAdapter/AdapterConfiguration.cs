namespace SlayTheModel.Sts2.ModAdapter;

internal enum AdapterRunMode
{
    Play,
    Train,
}

internal enum CombatPolicyKind
{
    Manual,
    FirstLegal,
    Mcts,
}

internal enum OutsideCombatPolicyKind
{
    Manual,
    FirstLegal,
}

/// <summary>
/// The stable launch contract for runtime purpose, in-combat policy, and
/// outside-combat policy. Controllers consume this object instead of reading
/// process environment variables independently.
/// </summary>
internal sealed record AdapterConfiguration(
    AdapterRunMode RunMode,
    CombatPolicyKind CombatPolicy,
    OutsideCombatPolicyKind OutsideCombatPolicy,
    bool UsedLegacyCombatPolicy = false)
{
    internal const string RunModeVariable = "SLAY_THE_MODEL_RUN_MODE";
    internal const string CombatPolicyVariable = "SLAY_THE_MODEL_COMBAT_POLICY";
    internal const string OutsideCombatPolicyVariable = "SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY";
    internal const string LegacyCombatPolicyVariable = "SLAY_THE_MODEL_LIVE_POLICY";

    internal static AdapterConfiguration Default { get; } = new(
        AdapterRunMode.Play,
        CombatPolicyKind.Manual,
        OutsideCombatPolicyKind.Manual);

    // RuntimeConfiguration gives process environment variables priority and
    // falls back to the JSON written beside the installed mod. Parsing remains
    // centralized here so controllers never interpret raw launch strings.
    internal static AdapterConfiguration LoadFromEnvironment() =>
        Load(RuntimeConfiguration.Get);

    internal static AdapterConfiguration Load(Func<string, string?> read)
    {
        ArgumentNullException.ThrowIfNull(read);

        var runMode = ParseRunMode(read(RunModeVariable));
        var combatValue = read(CombatPolicyVariable);
        var legacyValue = read(LegacyCombatPolicyVariable);
        var usedLegacy = string.IsNullOrWhiteSpace(combatValue) && !string.IsNullOrWhiteSpace(legacyValue);
        if (usedLegacy) combatValue = legacyValue;

        return new AdapterConfiguration(
            runMode,
            ParseCombatPolicy(combatValue),
            ParseOutsideCombatPolicy(read(OutsideCombatPolicyVariable)),
            usedLegacy);
    }

    internal string Describe() =>
        $"run_mode={Name(RunMode)} combat_policy={Name(CombatPolicy)} outside_combat_policy={Name(OutsideCombatPolicy)}";

    private static AdapterRunMode ParseRunMode(string? value) => Normalize(value) switch
    {
        "" or "play" => AdapterRunMode.Play,
        "train" => AdapterRunMode.Train,
        var unknown => throw Invalid(RunModeVariable, unknown, "play, train"),
    };

    private static CombatPolicyKind ParseCombatPolicy(string? value) => Normalize(value) switch
    {
        "" or "manual" => CombatPolicyKind.Manual,
        "first-legal" => CombatPolicyKind.FirstLegal,
        "mcts" => CombatPolicyKind.Mcts,
        var unknown => throw Invalid(CombatPolicyVariable, unknown, "manual, first-legal, mcts"),
    };

    private static OutsideCombatPolicyKind ParseOutsideCombatPolicy(string? value) => Normalize(value) switch
    {
        "" or "manual" => OutsideCombatPolicyKind.Manual,
        "first-legal" => OutsideCombatPolicyKind.FirstLegal,
        var unknown => throw Invalid(OutsideCombatPolicyVariable, unknown, "manual, first-legal"),
    };

    private static string Normalize(string? value) =>
        value?.Trim().Replace('_', '-').ToLowerInvariant() ?? "";

    private static ArgumentException Invalid(string variable, string value, string expected) =>
        new($"Unknown {variable} value '{value}'; expected one of: {expected}.");

    private static string Name(AdapterRunMode value) => value switch
    {
        AdapterRunMode.Play => "play",
        AdapterRunMode.Train => "train",
        _ => throw new ArgumentOutOfRangeException(nameof(value)),
    };

    private static string Name(CombatPolicyKind value) => value switch
    {
        CombatPolicyKind.Manual => "manual",
        CombatPolicyKind.FirstLegal => "first-legal",
        CombatPolicyKind.Mcts => "mcts",
        _ => throw new ArgumentOutOfRangeException(nameof(value)),
    };

    private static string Name(OutsideCombatPolicyKind value) => value switch
    {
        OutsideCombatPolicyKind.Manual => "manual",
        OutsideCombatPolicyKind.FirstLegal => "first-legal",
        _ => throw new ArgumentOutOfRangeException(nameof(value)),
    };
}
