using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SlayTheModel.Sts2.Protocol;

public static class ProtocolJson
{
    public static JsonSerializerOptions Options { get; } = CreateOptions();

    public static string Serialize<T>(T value) => JsonSerializer.Serialize(value, Options);

    public static T Deserialize<T>(string json) =>
        JsonSerializer.Deserialize<T>(json, Options)
        ?? throw new InvalidDataException($"Could not deserialize {typeof(T).Name}.");

    public static string ComputeStateFingerprint(CombatSnapshot state)
    {
        state.Validate();
        var semanticState = state with { DecisionIndex = 0 };
        var bytes = JsonSerializer.SerializeToUtf8Bytes(semanticState, Options);
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    public static void ValidateFingerprint(string fingerprint)
    {
        if (fingerprint.Length != 64 || fingerprint.Any(character => !Uri.IsHexDigit(character)))
        {
            throw new InvalidDataException(
                "State fingerprint must be a 64-character SHA-256 hex string.");
        }
    }

    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            WriteIndented = false,
        };
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
        return options;
    }
}
