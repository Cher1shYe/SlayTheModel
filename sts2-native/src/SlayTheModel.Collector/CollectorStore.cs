using System.Globalization;
using System.Text;

namespace SlayTheModel.Collector;

public sealed record CollectorOptions
{
    public CollectorOptions(string rootDirectory, ICollectorClock? clock = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(rootDirectory);
        RootDirectory = Path.GetFullPath(rootDirectory);
        Clock = clock ?? SystemCollectorClock.Instance;
    }

    public string RootDirectory { get; }

    public ICollectorClock Clock { get; }

    /// <summary>
    /// Publish a derived event-sourced view under episodes/_compact after the
    /// canonical hash-chained journal is safely published.
    /// </summary>
    public bool WriteCompactEpisodes { get; init; } = true;
}

/// <summary>
/// Filesystem boundary for independent episode journals. Construction creates
/// directories but deliberately does not scan, resume, or finish open episodes.
/// </summary>
public sealed class CollectorStore
{
    private readonly ICollectorClock _clock;
    private readonly string _episodesDirectory;
    private readonly string _openDirectory;
    private readonly string _compactDirectory;
    private readonly bool _writeCompactEpisodes;

    public CollectorStore(string rootDirectory, ICollectorClock? clock = null)
        : this(new CollectorOptions(rootDirectory, clock))
    {
    }

    public CollectorStore(CollectorOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        RootDirectory = options.RootDirectory;
        _clock = options.Clock;
        _writeCompactEpisodes = options.WriteCompactEpisodes;
        _episodesDirectory = Path.Combine(RootDirectory, "episodes");
        _openDirectory = Path.Combine(_episodesDirectory, "_open");
        _compactDirectory = Path.Combine(_episodesDirectory, "_compact");
        Directory.CreateDirectory(_openDirectory);
        if (_writeCompactEpisodes)
        {
            Directory.CreateDirectory(_compactDirectory);
        }
    }

    public string RootDirectory { get; }

    public EpisodeSession StartEpisode(EpisodeStartInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        ValidateEpisodeId(input.EpisodeId);
        if (FindExistingCompletedPath(input.EpisodeId) is { } existing)
        {
            throw new IOException($"Completed collector episode already exists: {existing}");
        }

        var recordedAtUtc = _clock.UtcNow.ToUniversalTime();
        var completedPath = BuildCompletedPath(
            input.EpisodeId, input.Metadata, recordedAtUtc);
        return EpisodeSession.Start(
            input,
            _clock,
            recordedAtUtc,
            GetOpenEpisodePath(input.EpisodeId),
            completedPath,
            _writeCompactEpisodes ? BuildCompactPath(completedPath) : null);
    }

    /// <summary>
    /// Explicitly resumes a .partial episode. This validates and replays every
    /// committed event; it never invents an episode_finished record for a crash.
    /// If episode_finished was committed before a rename failure, resume only
    /// completes that already-recorded publication.
    /// </summary>
    public EpisodeSession ResumeEpisode(Guid episodeId)
    {
        ValidateEpisodeId(episodeId);
        return EpisodeSession.Resume(
            episodeId,
            _clock,
            GetOpenEpisodePath(episodeId),
            events => ResolveCompletedPath(episodeId, events),
            completedPath => _writeCompactEpisodes ? BuildCompactPath(completedPath) : null);
    }

    /// <summary>Reads and fully validates an immutable completed episode.</summary>
    public IReadOnlyList<CollectorEventEnvelope> ReadEpisode(Guid episodeId)
    {
        ValidateEpisodeId(episodeId);
        var events = JsonlEpisodeJournal.ReadCompleted(GetCompletedEpisodePath(episodeId));
        var state = EpisodeSession.Replay(episodeId, events);
        if (state.Phase != EpisodePhase.Finished)
        {
            throw new InvalidDataException(
                "A completed episode file does not end with episode_finished.");
        }

        return events;
    }

    public string GetOpenEpisodePath(Guid episodeId)
    {
        ValidateEpisodeId(episodeId);
        return Path.Combine(_openDirectory, $"{episodeId:N}.jsonl.partial");
    }

    public string GetCompletedEpisodePath(Guid episodeId)
    {
        ValidateEpisodeId(episodeId);
        if (FindExistingCompletedPath(episodeId) is { } existing)
        {
            return existing;
        }

        var partialPath = GetOpenEpisodePath(episodeId);
        return File.Exists(partialPath)
            ? BuildCompletedPathFromStartEvent(
                episodeId,
                JsonlEpisodeJournal.ReadFirstEvent(partialPath))
            : Path.Combine(_episodesDirectory, $"{episodeId:N}.jsonl");
    }

    /// <summary>Returns the deterministic path of the derived compact view.</summary>
    public string GetCompactEpisodePath(Guid episodeId)
    {
        ValidateEpisodeId(episodeId);
        return BuildCompactPath(GetCompletedEpisodePath(episodeId));
    }

    /// <summary>
    /// Regenerates a compact view for an existing completed episode. This also
    /// supports episodes published before compact views existed.
    /// </summary>
    public CompactEpisodeExportResult ExportCompactEpisode(
        Guid episodeId,
        bool overwrite = false)
    {
        ValidateEpisodeId(episodeId);
        var source = GetCompletedEpisodePath(episodeId);
        return CompactEpisodeJournal.Export(
            source,
            BuildCompactPath(source),
            overwrite: overwrite);
    }

    private string ResolveCompletedPath(
        Guid episodeId,
        IReadOnlyList<CollectorEventEnvelope> events)
    {
        // An existing destination, including a legacy UUID path, must block
        // publication rather than allow a second file for the same episode.
        if (FindExistingCompletedPath(episodeId) is { } existing)
        {
            return existing;
        }

        if (events.Count == 0)
        {
            throw new InvalidDataException("Collector episode has no committed events.");
        }

        return BuildCompletedPathFromStartEvent(episodeId, events[0]);
    }

    private string BuildCompletedPathFromStartEvent(
        Guid episodeId,
        CollectorEventEnvelope started)
    {
        if (started.EventType != CollectorEventType.EpisodeStarted
            || started.EpisodeId != episodeId)
        {
            throw new InvalidDataException(
                "Collector partial does not begin with the expected episode_started event.");
        }

        var payload = CollectorJson.ReadPayload<EpisodeStartedPayload>(started);
        return BuildCompletedPath(episodeId, payload.Metadata, started.RecordedAtUtc);
    }

    private string BuildCompletedPath(
        Guid episodeId,
        IReadOnlyDictionary<string, string>? metadata,
        DateTimeOffset recordedAtUtc)
    {
        var steamId = "steam-unavailable";
        if (metadata?.TryGetValue("steam_id64", out var rawSteamId) == true
            && ulong.TryParse(rawSteamId, NumberStyles.None, CultureInfo.InvariantCulture,
                out var parsedSteamId)
            && parsedSteamId != 0)
        {
            steamId = parsedSteamId.ToString(CultureInfo.InvariantCulture);
        }

        string? rawCharacter = null;
        metadata?.TryGetValue("character_id", out rawCharacter);
        var character = SafeCharacter(rawCharacter);
        var ascension = "unknown";
        if (metadata?.TryGetValue("ascension", out var rawAscension) == true
            && int.TryParse(rawAscension, NumberStyles.None, CultureInfo.InvariantCulture,
                out var parsedAscension))
        {
            ascension = parsedAscension.ToString(CultureInfo.InvariantCulture);
        }

        var timestamp = recordedAtUtc.ToUniversalTime();
        if (metadata?.TryGetValue("run_started_at_utc", out var rawStartedAt) == true
            && DateTimeOffset.TryParse(rawStartedAt, CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal,
                out var runStartedAt))
        {
            timestamp = runStartedAt.ToUniversalTime();
        }

        var stamp = timestamp.ToString("yyyyMMdd'T'HHmmssfff'Z'", CultureInfo.InvariantCulture);
        return Path.Combine(
            _episodesDirectory,
            $"{steamId}_{character}_A{ascension}_{stamp}_{episodeId:N}.jsonl");
    }

    private string BuildCompactPath(string completedPath)
    {
        var fileName = Path.GetFileNameWithoutExtension(completedPath);
        return Path.Combine(_compactDirectory, $"{fileName}.compact.jsonl");
    }

    private string? FindExistingCompletedPath(Guid episodeId)
    {
        var legacy = Path.Combine(_episodesDirectory, $"{episodeId:N}.jsonl");
        var matches = Directory.EnumerateFiles(
                _episodesDirectory,
                $"*_{episodeId:N}.jsonl",
                SearchOption.TopDirectoryOnly)
            .ToList();
        if (File.Exists(legacy))
        {
            matches.Add(legacy);
        }

        return matches.Count switch
        {
            0 => null,
            1 => matches[0],
            _ => throw new InvalidDataException(
                $"Multiple completed files claim collector episode {episodeId:N}."),
        };
    }

    private static string SafeCharacter(string? characterId)
    {
        if (string.IsNullOrWhiteSpace(characterId))
        {
            return "unknown";
        }

        var raw = characterId.StartsWith("CHARACTER.", StringComparison.OrdinalIgnoreCase)
            ? characterId["CHARACTER.".Length..]
            : characterId;
        var slug = new StringBuilder(Math.Min(raw.Length, 48));
        foreach (var character in raw)
        {
            if (slug.Length >= 48)
            {
                break;
            }

            if (character is >= 'A' and <= 'Z' or >= 'a' and <= 'z'
                or >= '0' and <= '9')
            {
                slug.Append(character);
            }
            else if (slug.Length > 0 && slug[^1] != '-')
            {
                slug.Append('-');
            }
        }

        return slug.ToString().Trim('-') is { Length: > 0 } safe
            ? safe
            : "unknown";
    }

    private static void ValidateEpisodeId(Guid episodeId)
    {
        if (episodeId == Guid.Empty)
        {
            throw new ArgumentException("Episode ID cannot be empty.", nameof(episodeId));
        }
    }
}
