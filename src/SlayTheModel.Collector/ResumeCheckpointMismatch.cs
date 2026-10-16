namespace SlayTheModel.Collector;

/// <summary>Distinct wire names for the saved checkpoint and current journal cursors.</summary>
public sealed record ResumeCheckpointMismatch(
    bool ResumeCheckpointValid,
    long CheckpointEventSequence,
    long JournalEventSequence,
    bool StateFingerprintMatches);
