using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SlayTheModel.Collector;

public sealed record CollectorEventEnvelope(
    int SchemaVersion,
    CollectorEventType EventType,
    Guid EventId,
    Guid EpisodeId,
    long EventSequence,
    long? GlobalStep,
    int TimelineGeneration,
    DateTimeOffset RecordedAtUtc,
    CollectorSource Source,
    string PreviousEventSha256,
    JsonElement Payload,
    string EventSha256)
{
    public const int CurrentSchemaVersion = 1;

    internal CollectorUnsignedEvent WithoutHash() => new(
        SchemaVersion,
        EventType,
        EventId,
        EpisodeId,
        EventSequence,
        GlobalStep,
        TimelineGeneration,
        RecordedAtUtc,
        Source,
        PreviousEventSha256,
        Payload);
}

internal sealed record CollectorUnsignedEvent(
    int SchemaVersion,
    CollectorEventType EventType,
    Guid EventId,
    Guid EpisodeId,
    long EventSequence,
    long? GlobalStep,
    int TimelineGeneration,
    DateTimeOffset RecordedAtUtc,
    CollectorSource Source,
    string PreviousEventSha256,
    JsonElement Payload);

public static class CollectorJson
{
    public const string InitialPreviousHash =
        "0000000000000000000000000000000000000000000000000000000000000000";

    public static JsonSerializerOptions Options { get; } = CreateOptions();

    public static string Serialize(CollectorEventEnvelope value) =>
        JsonSerializer.Serialize(value, Options);

    public static CollectorEventEnvelope Deserialize(string json) =>
        JsonSerializer.Deserialize<CollectorEventEnvelope>(json, Options)
        ?? throw new InvalidDataException("Could not deserialize collector event.");

    internal static CollectorEventEnvelope CreateEnvelope<TPayload>(
        CollectorEventType eventType,
        Guid eventId,
        Guid episodeId,
        long eventSequence,
        long? globalStep,
        int timelineGeneration,
        DateTimeOffset recordedAtUtc,
        CollectorSource source,
        string previousEventSha256,
        TPayload payload)
    {
        var payloadElement = JsonSerializer.SerializeToElement(payload, Options);
        var unsigned = new CollectorUnsignedEvent(
            CollectorEventEnvelope.CurrentSchemaVersion,
            eventType,
            eventId,
            episodeId,
            eventSequence,
            globalStep,
            timelineGeneration,
            recordedAtUtc,
            source,
            previousEventSha256,
            payloadElement);
        var digest = ComputeHash(unsigned);
        return new CollectorEventEnvelope(
            unsigned.SchemaVersion,
            unsigned.EventType,
            unsigned.EventId,
            unsigned.EpisodeId,
            unsigned.EventSequence,
            unsigned.GlobalStep,
            unsigned.TimelineGeneration,
            unsigned.RecordedAtUtc,
            unsigned.Source,
            unsigned.PreviousEventSha256,
            unsigned.Payload,
            digest);
    }

    internal static string ComputeHash(CollectorUnsignedEvent value) =>
        Convert.ToHexString(
            SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(value, Options)))
            .ToLowerInvariant();

    internal static TPayload ReadPayload<TPayload>(CollectorEventEnvelope envelope) =>
        envelope.Payload.Deserialize<TPayload>(Options)
        ?? throw new InvalidDataException(
            $"Collector event {envelope.EventSequence} has no valid "
            + $"{typeof(TPayload).Name} payload.");

    internal static void ValidateHash(string? value, string fieldName)
    {
        if (value is null
            || value.Length != 64
            || value.Any(character => !Uri.IsHexDigit(character)))
        {
            throw new InvalidDataException(
                $"{fieldName} must be a 64-character SHA-256 hex string.");
        }
    }

    private static JsonSerializerOptions CreateOptions()
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            WriteIndented = false,
            RespectRequiredConstructorParameters = true,
            UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        };
        options.Converters.Add(
            new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
        options.MakeReadOnly(populateMissingResolver: true);
        return options;
    }
}
