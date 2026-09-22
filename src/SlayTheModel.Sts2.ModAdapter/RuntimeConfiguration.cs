using System.Reflection;
using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

internal static class RuntimeConfiguration
{
    private const string FileName = "SlayTheModelAdapter.runtime.json";
    private static readonly Lazy<IReadOnlyDictionary<string, string?>> Values = new(Load);

    public static string? Get(string name)
    {
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
