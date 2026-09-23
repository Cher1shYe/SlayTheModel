using System.Reflection;
using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

internal static class RuntimeConfiguration
{
    private const string FileName = "SlayTheModelAdapter.runtime.json";
    // Read the fallback file once per process. Launch configuration is immutable
    // after the game starts, and avoiding repeated disk I/O keeps controller
    // callbacks deterministic and cheap.
    private static readonly Lazy<IReadOnlyDictionary<string, string?>> Values = new(Load);

    public static string? Get(string name)
    {
        // A value supplied to this game process is always the most explicit
        // choice. The file exists mainly for Steam launches that do not inherit
        // the temporary environment created by a shell script.
        var environment = Environment.GetEnvironmentVariable(name);
        if (!string.IsNullOrWhiteSpace(environment)) return environment;
        return Values.Value.TryGetValue(name, out var value) ? value : null;
    }

    private static IReadOnlyDictionary<string, string?> Load()
    {
        try
        {
            var directory = Path.GetDirectoryName(typeof(RuntimeConfiguration).Assembly.Location);
            if (string.IsNullOrWhiteSpace(directory)) return new Dictionary<string, string?>();
            var path = Path.Combine(directory, FileName);
            if (!File.Exists(path)) return new Dictionary<string, string?>();
            return JsonSerializer.Deserialize<Dictionary<string, string?>>(File.ReadAllText(path))
                ?? new Dictionary<string, string?>();
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[SlayTheModel] runtime config unavailable: {exception.Message}");
            return new Dictionary<string, string?>();
        }
    }
}
