using System.Text.Json;

namespace SlayTheModel.Collector;

/// <summary>
/// Thread-safe writer for one episode. Every mutation is validated against a
/// cloned state machine before it is synchronously committed to the JSONL WAL.
/// Dispose leaves an unfinished .partial file for an explicit future resume.
/// </summary>
public sealed class EpisodeSession : IDisposable
{
    private readonly object _gate = new();
    private readonly ICollectorClock _clock;
    private readonly EpisodeStateMachine _state;
    private readonly JsonlEpisodeJournal _journal;
    private bool _disposed;

    private EpisodeSession(
        Guid episodeId,
        ICollectorClock clock,
        EpisodeStateMachine state,
        JsonlEpisodeJournal journal)
    {
        EpisodeId = episodeId;
        _clock = clock;
        _state = state;
        _journal = journal;
    }

    public Guid EpisodeId { get; }

    public string RewardVersion
    {
        get
        {
            lock (_gate)
            {
                ThrowIfDisposed();
                return _state.RewardVersion
                    ?? throw new InvalidDataException(
                        "Episode has no reward version.");
            }
        }
    }

    /// <summary>
    /// False when explicit recovery found an already-committed finish and only
    /// completed its interrupted partial-to-final publication.
    /// </summary>
    public bool CanAppend
    {
        get
        {
            lock (_gate)
            {
                return !_disposed && _state.Phase != EpisodePhase.Finished;
            }
        }
    }

    public EpisodeSnapshot Snapshot
    {
        get
        {
            lock (_gate)
            {
                ThrowIfDisposed();
                return _state.Snapshot(_journal.IsPublished);
            }
        }
    }

    /// <summary>
    /// A compact-view failure never invalidates the canonical episode. Callers
    /// may surface this after Finish and regenerate it through CollectorStore.
    /// </summary>
    public Exception? CompactViewError
    {
        get
        {
            lock (_gate)
            {
                return _journal.CompactViewError;
            }
        }
    }

    internal static EpisodeSession Start(
        EpisodeStartInput input,
        ICollectorClock clock,
        DateTimeOffset recordedAtUtc,
        string partialPath,
        string completedPath,
        string? compactPath)
    {
        ArgumentNullException.ThrowIfNull(input);
        ArgumentNullException.ThrowIfNull(clock);
        var state = new EpisodeStateMachine(input.EpisodeId);
        var metadata = new SortedDictionary<string, string>(StringComparer.Ordinal);
        if (input.Metadata is not null)
        {
            foreach (var pair in input.Metadata)
            {
                metadata.Add(pair.Key, pair.Value);
            }
        }

        // Validate the first record before claiming a path. Bad configuration
        // must not strand an empty .partial file which looks crash-recoverable.
        var started = CollectorJson.CreateEnvelope(
            CollectorEventType.EpisodeStarted,
            input.EventId,
            input.EpisodeId,
            eventSequence: 0,
            globalStep: null,
            timelineGeneration: 0,
            recordedAtUtc.ToUniversalTime(),
            input.Source,
            CollectorJson.InitialPreviousHash,
            new EpisodeStartedPayload(
                input.Build,
                input.CollectorRevision,
                input.RewardVersion,
                input.NoSlExpected,
                metadata));
        state.ValidateNext(started);

        var journal = JsonlEpisodeJournal.Create(
            partialPath, completedPath, compactPath);
        try
        {
            journal.Append(started);
            state.Apply(started);
            return new EpisodeSession(input.EpisodeId, clock, state, journal);
        }
        catch
        {
            journal.Dispose();
            throw;
        }
    }

    internal static EpisodeSession Resume(
        Guid episodeId,
        ICollectorClock clock,
        string partialPath,
        Func<IReadOnlyList<CollectorEventEnvelope>, string> resolveCompletedPath,
        Func<string, string?> resolveCompactPath)
    {
        ArgumentNullException.ThrowIfNull(clock);
        var journal = JsonlEpisodeJournal.Resume(
            partialPath,
            resolveCompletedPath,
            resolveCompactPath,
            out var events);
        try
        {
            var state = Replay(episodeId, events);
            var session = new EpisodeSession(episodeId, clock, state, journal);
            if (state.Phase == EpisodePhase.Finished)
            {
                journal.Publish();
            }

            return session;
        }
        catch
        {
            journal.Dispose();
            throw;
        }
    }

    internal static EpisodeStateMachine Replay(
        Guid episodeId,
        IReadOnlyList<CollectorEventEnvelope> events)
    {
        ArgumentNullException.ThrowIfNull(events);
        if (events.Count == 0)
        {
            throw new InvalidDataException("Collector episode has no committed events.");
        }

        var state = new EpisodeStateMachine(episodeId);
        foreach (var episodeEvent in events)
        {
            state.Apply(episodeEvent);
        }

        return state;
    }

    public DecisionReceipt RecordDecision(DecisionInput input)
        => RecordDecisionCore(input, queuedCombatInput: false, queuedOutsideInput: false);

    /// <summary>
    /// Records a complete click-time combat decision while earlier combat
    /// actions are still in flight. The same event writer and global-step
    /// sequence are available to live and headless producers.
    /// </summary>
    public DecisionReceipt RecordQueuedCombatDecision(DecisionInput input)
        => RecordDecisionCore(input, queuedCombatInput: true, queuedOutsideInput: false);

    /// <summary>
    /// Records a click-time outside decision while an earlier submitted
    /// outside action remains unsettled. The producer must still prove a
    /// complete legal set and bind the native input to its own decision ID.
    /// </summary>
    public DecisionReceipt RecordQueuedOutsideDecision(DecisionInput input)
        => RecordDecisionCore(input, queuedCombatInput: false, queuedOutsideInput: true);

    private DecisionReceipt RecordDecisionCore(
        DecisionInput input,
        bool queuedCombatInput,
        bool queuedOutsideInput)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var globalStep = _state.NextGlobalStep;
            var keys = input.ActionKeys.ToArray();
            var payload = new DecisionPayload(
                input.EventId,
                input.Domain,
                input.InformationRegime,
                input.SourceDecisionIndex,
                input.StateFingerprint,
                input.Observation.Clone(),
                input.LegalActions.Clone(),
                keys,
                input.Build,
                input.Context?.Clone(),
                queuedCombatInput,
                queuedOutsideInput);
            AppendCurrent(
                CollectorEventType.Decision,
                input.EventId,
                globalStep,
                _state.TimelineGeneration,
                payload);
            return new DecisionReceipt(input.EventId, globalStep, keys);
        }
    }

    public void SubmitAction(ActionSubmissionInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var pending = RequirePending(input.DecisionId);
            var policy = input.Policy with
            {
                Logits = input.Policy.Logits?.ToArray(),
                MctsVisitCounts = input.Policy.MctsVisitCounts?.ToArray(),
            };
            AppendCurrent(
                CollectorEventType.ActionSubmitted,
                input.EventId,
                pending.GlobalStep,
                _state.TimelineGeneration,
                new ActionSubmittedPayload(
                    input.DecisionId,
                    input.AttemptId,
                    input.SelectedActionIndex,
                    input.SelectedActionKey,
                    policy,
                    input.SelectedAction?.Clone()));
        }
    }

    public void RecordExecution(ExecutionInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var pending = RequirePending(input.DecisionId);
            AppendCurrent(
                CollectorEventType.ExecutionResult,
                input.EventId,
                pending.GlobalStep,
                _state.TimelineGeneration,
                new ExecutionResultPayload(
                    input.DecisionId,
                    input.AttemptId,
                    input.SelectedActionIndex,
                    input.SelectedActionKey,
                    input.ExpectedStateFingerprint,
                    input.Status,
                    input.NextStateFingerprint,
                    input.Detail));
        }
    }

    public void RecordReward(RewardInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var pending = RequirePending(input.DecisionId);
            var components = new SortedDictionary<string, double>(StringComparer.Ordinal);
            foreach (var pair in input.Components)
            {
                components.Add(pair.Key, pair.Value);
            }

            AppendCurrent(
                CollectorEventType.Reward,
                input.EventId,
                pending.GlobalStep,
                _state.TimelineGeneration,
                new RewardPayload(
                    input.DecisionId,
                    input.RewardVersion,
                    components));
        }
    }

    public void MarkSaveLoad(SaveLoadInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var pending = _state.Pending;
            var pendingDecisions = _state.PendingReferences;
            var fromGeneration = _state.TimelineGeneration;
            AppendCurrent(
                CollectorEventType.SaveLoad,
                input.EventId,
                pending?.GlobalStep,
                fromGeneration + 1,
                new SaveLoadPayload(
                    input.Kind,
                    input.Reason,
                    fromGeneration,
                    fromGeneration + 1,
                    input.BeforeStateFingerprint,
                    input.RestoredStateFingerprint,
                    input.CheckpointSha256,
                    pending?.Decision.DecisionId,
                    pending?.GlobalStep,
                    _state.Phase,
                    CreatesDataGap: pending is not null,
                    InvalidatedDecisions: pendingDecisions));
        }
    }

    public void RecordCoverageGap(CoverageGapInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            if (input.TargetDecisionId is not null
                && !input.InvalidatePendingDecision)
            {
                throw new InvalidDataException(
                    "A targeted coverage gap must invalidate its target decision.");
            }

            var pending = input.TargetDecisionId is { } targetDecisionId
                ? _state.FindPending(targetDecisionId)
                    ?? throw new InvalidDataException(
                        "The targeted coverage-gap decision is not pending.")
                : _state.Pending;
            var pendingDecisions = input.TargetDecisionId is null
                ? _state.PendingReferences
                : new[]
                {
                    new PendingDecisionReference(
                        pending!.Decision.DecisionId,
                        pending.GlobalStep,
                        pending.Phase),
                };
            var invalidatesPending = input.InvalidatePendingDecision
                                     && pending is not null;
            AppendCurrent(
                CollectorEventType.CoverageGap,
                input.EventId,
                invalidatesPending ? pending!.GlobalStep : null,
                _state.TimelineGeneration,
                new CoverageGapPayload(
                    input.Reason,
                    invalidatesPending ? pending!.Decision.DecisionId : null,
                    invalidatesPending ? pending!.GlobalStep : null,
                    _state.Phase,
                    invalidatesPending,
                    input.RelatedDecisionId,
                    input.RelatedAttemptId,
                    invalidatesPending ? pendingDecisions : [],
                    input.TargetDecisionId));
        }
    }

    /// <summary>
    /// Records audit-only native data on the same durable hash chain. It is
    /// deliberately emitted without a global_step and leaves the policy state
    /// machine completely unchanged.
    /// </summary>
    public void RecordDiagnostic(DiagnosticInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            AppendCurrent(
                CollectorEventType.Diagnostic,
                input.EventId,
                globalStep: null,
                _state.TimelineGeneration,
                new DiagnosticPayload(input.Code, input.Data.Clone()));
        }
    }

    public Guid RecordDiagnostic(string code, JsonElement data)
    {
        var eventId = Guid.NewGuid();
        RecordDiagnostic(new DiagnosticInput(eventId, code, data));
        return eventId;
    }

    /// <summary>
    /// Durably records a manual input even while a previous structured
    /// decision is pending. This side channel has no global step and does not
    /// claim that the native action forms a clean training transition.
    /// </summary>
    public void RecordManualCombatInput(ManualCombatInputInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            AppendCurrent(
                CollectorEventType.ManualCombatInput,
                input.EventId,
                globalStep: null,
                _state.TimelineGeneration,
                new ManualCombatInputPayload(
                    input.IntentId,
                    input.NativeActionId,
                    input.ActionKind,
                    input.Data.Clone(),
                    input.RelatedDecisionId,
                    input.RelatedAttemptId));
        }
    }

    public void RecordManualCombatInputOutcome(ManualCombatInputOutcomeInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            AppendCurrent(
                CollectorEventType.ManualCombatInputOutcome,
                input.EventId,
                globalStep: null,
                _state.TimelineGeneration,
                new ManualCombatInputOutcomePayload(
                    input.IntentId,
                    input.NativeActionId,
                    input.Status,
                    input.Detail,
                    input.Data?.Clone()));
        }
    }

    public void Finish(EpisodeFinishInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        lock (_gate)
        {
            ThrowIfDisposed();
            var previousPhase = _state.Phase;
            var incompleteDecision = _state.Pending?.Decision.DecisionId;
            var completeness = _state.UnresolvedManualCombatInputCount == 0
                               && _state.UnstructuredUnsafeManualCombatInputCount == 0
                ? input.Completeness
                : EpisodeCompleteness.Incomplete;
            var valueTargetValid = completeness == EpisodeCompleteness.Complete
                && previousPhase == EpisodePhase.Ready
                && _state.UnknownSaveLoadCount == 0
                && _state.RewindCount == 0
                && _state.InvalidatedPendingCount == 0
                && _state.UncertainExecutionCount == 0
                && _state.CoverageGapCount == 0;
            AppendCurrent(
                CollectorEventType.EpisodeFinished,
                input.EventId,
                globalStep: null,
                _state.TimelineGeneration,
                new EpisodeFinishedPayload(
                    input.Outcome,
                    input.TerminationReason,
                    completeness,
                    _state.ContainsSaveLoad,
                    _state.SaveLoadCount,
                    _state.UnknownSaveLoadCount,
                    _state.RewindCount,
                    _state.InvalidatedPendingCount,
                    _state.UncertainExecutionCount,
                    _state.CoverageGapCount,
                    valueTargetValid,
                    incompleteDecision,
                    previousPhase,
                    input.Summary?.Clone(),
                    _state.ManualCombatInputCount,
                    _state.UnresolvedManualCombatInputCount,
                    _state.UnstructuredManualCombatInputCount,
                    _state.UnstructuredUnsafeManualCombatInputCount,
                    _state.PendingReferences));
            _journal.Publish();
        }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                return;
            }

            _journal.Dispose();
            _disposed = true;
        }
    }

    private PendingDecision RequirePending(Guid decisionId) =>
        _state.FindPending(decisionId)
        ?? throw new InvalidOperationException(
            $"There is no pending collector decision {decisionId}.");

    private void AppendCurrent<TPayload>(
        CollectorEventType eventType,
        Guid eventId,
        long? globalStep,
        int timelineGeneration,
        TPayload payload)
    {
        var source = _state.Source
            ?? throw new InvalidOperationException("The collector episode has not started.");
        Append(eventType, eventId, globalStep, timelineGeneration, source, payload);
    }

    private void Append<TPayload>(
        CollectorEventType eventType,
        Guid eventId,
        long? globalStep,
        int timelineGeneration,
        CollectorSource source,
        TPayload payload)
    {
        var timestamp = _clock.UtcNow.ToUniversalTime();
        var envelope = CollectorJson.CreateEnvelope(
            eventType,
            eventId,
            EpisodeId,
            _state.NextEventSequence,
            globalStep,
            timelineGeneration,
            timestamp,
            source,
            _state.LastEventHash,
            payload);

        // Never append a record which cannot be replayed. Once Flush(true)
        // succeeds, applying the same deterministic validation cannot fail.
        _state.ValidateNext(envelope);
        _journal.Append(envelope);
        _state.Apply(envelope);
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
        {
            throw new ObjectDisposedException(nameof(EpisodeSession));
        }
    }
}
