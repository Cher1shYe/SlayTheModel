using System.Text;
using System.Text.Json;

namespace SlayTheModel.Collector;

/// <summary>
/// One durable append-only JSONL file per episode. A file stays under _open
/// with a .partial suffix until its episode_finished record is durable, then a
/// same-volume rename publishes it as the immutable completed episode.
/// </summary>
internal sealed class JsonlEpisodeJournal : IDisposable
{
    private const int ScanBufferSize = 8192;
    private const int MaximumLineBytes = 64 * 1024 * 1024;
    private static readonly Encoding Utf8 = new UTF8Encoding(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    private FileStream? _stream;
    private bool _faulted;

    private JsonlEpisodeJournal(
        string partialPath,
        string completedPath,
        string? compactPath,
        FileStream stream)
    {
        PartialPath = partialPath;
        CompletedPath = completedPath;
        CompactPath = compactPath;
        _stream = stream;
    }

    public string PartialPath { get; }

    public string CompletedPath { get; }

    public string? CompactPath { get; }

    public Exception? CompactViewError { get; private set; }

    public bool IsPublished { get; private set; }

    public static JsonlEpisodeJournal Create(
        string partialPath,
        string completedPath,
        string? compactPath)
    {
        EnsureDestinationIsFree(completedPath);
        var stream = new FileStream(
            partialPath,
            FileMode.CreateNew,
            FileAccess.ReadWrite,
            FileShare.Read,
            bufferSize: ScanBufferSize,
            FileOptions.WriteThrough);
        return new JsonlEpisodeJournal(
            partialPath, completedPath, compactPath, stream);
    }

    /// <summary>
    /// Opens an unfinished episode only when explicitly requested. Bytes after
    /// the last newline are an uncommitted torn append and are truncated; every
    /// complete JSONL record remains subject to schema/hash/state replay checks.
    /// </summary>
    public static JsonlEpisodeJournal Resume(
        string partialPath,
        Func<IReadOnlyList<CollectorEventEnvelope>, string> resolveCompletedPath,
        Func<string, string?> resolveCompactPath,
        out IReadOnlyList<CollectorEventEnvelope> events)
    {
        ArgumentNullException.ThrowIfNull(resolveCompletedPath);
        ArgumentNullException.ThrowIfNull(resolveCompactPath);
        var stream = new FileStream(
            partialPath,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.Read,
            bufferSize: ScanBufferSize,
            FileOptions.WriteThrough);
        try
        {
            var committedLength = FindCommittedLength(stream);
            if (committedLength != stream.Length)
            {
                stream.SetLength(committedLength);
                stream.Flush(flushToDisk: true);
            }

            events = ReadLines(stream, requireTerminatingNewline: false);
            var completedPath = resolveCompletedPath(events);
            var compactPath = resolveCompactPath(completedPath);
            EnsureDestinationIsFree(completedPath);
            stream.Position = stream.Length;
            return new JsonlEpisodeJournal(
                partialPath, completedPath, compactPath, stream);
        }
        catch
        {
            stream.Dispose();
            throw;
        }
    }

    public static IReadOnlyList<CollectorEventEnvelope> ReadCompleted(string completedPath)
    {
        using var stream = new FileStream(
            completedPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: ScanBufferSize,
            FileOptions.SequentialScan);
        return ReadLines(stream, requireTerminatingNewline: true);
    }

    public static CollectorEventEnvelope ReadFirstEvent(string partialPath)
    {
        using var stream = new FileStream(
            partialPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite,
            bufferSize: ScanBufferSize,
            FileOptions.SequentialScan);
        using var reader = new StreamReader(
            stream,
            Utf8,
            detectEncodingFromByteOrderMarks: false,
            bufferSize: ScanBufferSize);
        var line = reader.ReadLine();
        if (string.IsNullOrEmpty(line) || Utf8.GetByteCount(line) > MaximumLineBytes)
        {
            throw new InvalidDataException("Collector partial has no valid first event.");
        }

        return CollectorJson.Deserialize(line);
    }

    public void Append(CollectorEventEnvelope envelope)
    {
        ArgumentNullException.ThrowIfNull(envelope);
        var stream = RequireWritable();
        var bytes = Utf8.GetBytes(CollectorJson.Serialize(envelope));
        if (bytes.Length > MaximumLineBytes)
        {
            throw new InvalidDataException(
                $"Collector JSONL record exceeds {MaximumLineBytes} UTF-8 bytes.");
        }

        try
        {
            stream.Write(bytes);
            stream.WriteByte((byte)'\n');
            // Flush(true) is the commit boundary for one record. A later
            // process crash can at most leave bytes after the last newline.
            stream.Flush(flushToDisk: true);
        }
        catch
        {
            // The caller cannot know whether the OS persisted none, some, or
            // all of this record. Force an explicit dispose + resume/replay.
            _faulted = true;
            throw;
        }
    }

    public void Publish()
    {
        var stream = RequireWritable();
        EnsureDestinationIsFree(CompletedPath);
        stream.Flush(flushToDisk: true);
        stream.Dispose();
        _stream = null;

        // Both paths are created below the same episodes directory, so this is
        // an atomic visibility transition on the supported local filesystems.
        File.Move(PartialPath, CompletedPath, overwrite: false);
        IsPublished = true;
        if (CompactPath is not null)
        {
            try
            {
                CompactEpisodeJournal.Export(
                    CompletedPath, CompactPath, overwrite: true);
            }
            catch (Exception exception)
            {
                // The canonical episode is already durable and immutable. A
                // derived readability view must not make callers retry Finish
                // and create a misleading second terminal record.
                CompactViewError = exception;
            }
        }
    }

    public void Dispose()
    {
        _stream?.Dispose();
        _stream = null;
    }

    private FileStream RequireWritable()
    {
        if (_faulted)
        {
            throw new InvalidOperationException(
                "The episode journal had an I/O failure; dispose it and explicitly resume it.");
        }

        return _stream
            ?? throw new ObjectDisposedException(nameof(JsonlEpisodeJournal));
    }

    private static void EnsureDestinationIsFree(string completedPath)
    {
        if (File.Exists(completedPath))
        {
            throw new IOException(
                $"Completed collector episode already exists: {completedPath}");
        }
    }

    private static long FindCommittedLength(FileStream stream)
    {
        var length = stream.Length;
        if (length == 0)
        {
            return 0;
        }

        stream.Position = length - 1;
        if (stream.ReadByte() == '\n')
        {
            return length;
        }

        var buffer = new byte[ScanBufferSize];
        var cursor = length;
        while (cursor > 0)
        {
            var start = Math.Max(0, cursor - buffer.Length);
            var count = checked((int)(cursor - start));
            stream.Position = start;
            stream.ReadExactly(buffer.AsSpan(0, count));
            for (var index = count - 1; index >= 0; index--)
            {
                if (buffer[index] == (byte)'\n')
                {
                    return start + index + 1;
                }
            }

            cursor = start;
        }

        return 0;
    }

    private static IReadOnlyList<CollectorEventEnvelope> ReadLines(
        FileStream stream,
        bool requireTerminatingNewline)
    {
        if (requireTerminatingNewline && stream.Length > 0)
        {
            stream.Position = stream.Length - 1;
            if (stream.ReadByte() != '\n')
            {
                throw new InvalidDataException(
                    "Completed collector JSONL is missing its terminating newline.");
            }
        }

        stream.Position = 0;
        var events = new List<CollectorEventEnvelope>();
        try
        {
            using var reader = new StreamReader(
                stream,
                Utf8,
                detectEncodingFromByteOrderMarks: false,
                bufferSize: ScanBufferSize,
                leaveOpen: true);
            string? line;
            while ((line = reader.ReadLine()) is not null)
            {
                if (line.Length == 0 || Utf8.GetByteCount(line) > MaximumLineBytes)
                {
                    throw new InvalidDataException(
                        "Collector JSONL contains an empty or oversized record.");
                }

                events.Add(CollectorJson.Deserialize(line));
            }
        }
        catch (JsonException exception)
        {
            throw new InvalidDataException(
                $"Collector JSONL record {events.Count} is not valid JSON.",
                exception);
        }
        catch (DecoderFallbackException exception)
        {
            throw new InvalidDataException("Collector JSONL is not valid UTF-8.", exception);
        }

        return events;
    }
}
