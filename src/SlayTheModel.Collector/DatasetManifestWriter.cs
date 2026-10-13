using System.Text.Json;

namespace SlayTheModel.Collector;

/// <summary>
/// Creates the shared dataset root manifest for live and headless producers.
/// Episode JSONL is still written exclusively by JsonlEpisodeJournal.
/// </summary>
public static class DatasetManifestWriter
{
    public static string Ensure(string rootDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(rootDirectory);
        var root = Path.GetFullPath(rootDirectory);
        Directory.CreateDirectory(root);
        var path = Path.Combine(root, "dataset-manifest.json");
        if (File.Exists(path))
        {
            return path;
        }

        var manifest = JsonSerializer.Serialize(
            new
            {
                schema_version = 1,
                format = "slay-the-model-trajectory-jsonl",
                source_of_truth = "episodes/*.jsonl",
                compact_views = "episodes/_compact/*.compact.jsonl",
                compact_views_are_derived = true,
                open_episodes = "episodes/_open/*.jsonl.partial",
                quarantined_episodes = "episodes/_quarantine/*.jsonl.partial",
                upload_enabled = false,
                created_at_utc = DateTimeOffset.UtcNow,
            },
            new JsonSerializerOptions { WriteIndented = true });
        var temporary = path + $".{Guid.NewGuid():N}.tmp";
        try
        {
            File.WriteAllText(temporary, manifest + Environment.NewLine);
            try
            {
                File.Move(temporary, path, overwrite: false);
            }
            catch (IOException) when (File.Exists(path))
            {
                // Another producer won the first-writer race for this root.
            }
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }

        return path;
    }
}
