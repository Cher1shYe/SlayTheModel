using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Independent outside-policy switch. Disabled means the controller falls
/// back to its normal automatic outside policy; it does not pause combat.
/// </summary>
internal static class ArmGSwitch
{
    private const string FileName = "SlayTheModelAdapter.armg-toggle.json";
    private static readonly object Gate = new();
    private static int _available;
    private static int _enabled;
    private static long _generation;

    internal static bool Available => Volatile.Read(ref _available) != 0;
    internal static bool Enabled => Available && Volatile.Read(ref _enabled) != 0;
    // A request begun before any switch change must never be applied afterward.
    internal static long Generation => Interlocked.Read(ref _generation);

    internal static void Configure(bool available)
    {
        lock (Gate)
        {
            var enabled = available && ReadInitialState();
            Volatile.Write(ref _enabled, enabled ? 1 : 0);
            Volatile.Write(ref _available, available ? 1 : 0);
            Interlocked.Increment(ref _generation);
        }
    }

    internal static void Toggle()
    {
        lock (Gate)
        {
            if (!Available) return;
            var enabled = Volatile.Read(ref _enabled) == 0;
            Volatile.Write(ref _enabled, enabled ? 1 : 0);
            Interlocked.Increment(ref _generation);
            try
            {
                var path = StatePath();
                if (path is null) return;
                var temp = path + ".tmp";
                try
                {
                    File.WriteAllText(temp, JsonSerializer.Serialize(new ToggleState(enabled)));
                    File.Move(temp, path, overwrite: true);
                }
                finally { if (File.Exists(temp)) File.Delete(temp); }
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Console.Error.WriteLine($"[SlayTheModel] could not save ArmG switch: {ex.Message}");
            }
        }
    }

    internal static AiControlStatus GetStatus()
    {
        if (!Available)
            return new AiControlStatus("局外网络：未配置", "启动时选择 armg 局外策略后可使用此开关。", "#9da8b3", false);
        return Enabled
            ? new AiControlStatus("局外网络：开启", "点击关闭局外网络；关闭后继续使用自动局外兜底。战斗 MCTS 开关不受影响。", "#75e0ae", true)
            : new AiControlStatus("局外网络：关闭", "当前使用自动局外兜底。点击开启 ArmG；战斗 MCTS 开关不受影响。", "#e8ba65", true);
    }

    private static bool ReadInitialState()
    {
        try
        {
            var path = StatePath();
            if (path is not null && File.Exists(path))
            {
                var saved = JsonSerializer.Deserialize<ToggleState>(File.ReadAllText(path));
                if (saved is not null) return saved.Enabled;
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            Console.Error.WriteLine($"[SlayTheModel] could not read ArmG switch: {ex.Message}");
        }
        return (RuntimeConfiguration.Get("SLAY_THE_MODEL_ARMG_ENABLED") ?? "1").Trim().ToLowerInvariant()
            is not ("0" or "false" or "off");
    }

    private static string? StatePath()
    {
        var directory = Path.GetDirectoryName(typeof(ArmGSwitch).Assembly.Location);
        return string.IsNullOrWhiteSpace(directory) ? null : Path.Combine(directory, FileName);
    }

    private sealed record ToggleState(bool Enabled);
}
