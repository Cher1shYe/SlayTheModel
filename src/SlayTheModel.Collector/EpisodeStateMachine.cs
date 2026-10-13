using System.Text.Json;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Collector;

internal sealed record PendingDecision(
    DecisionPayload Decision,
    long GlobalStep,
    ActionSubmittedPayload? Submission = null,
    EpisodePhase Phase = EpisodePhase.AwaitingAction);

internal sealed record ManualCombatInputState(
    long NativeActionId,
    int TimelineGeneration,
    bool HasOutcome,
    bool IsStructured);

/// <summary>
/// Pure replayable state. Validation is run on a clone before durable append,
/// then applied to the live instance only after the journal flush succeeds.
/// </summary>
internal sealed class EpisodeStateMachine
{
    private readonly Guid _expectedEpisodeId;
    private readonly HashSet<Guid> _eventIds;
    private readonly HashSet<Guid> _attemptIds;
    private readonly Dictionary<Guid, ManualCombatInputState> _manualCombatInputs;
    private readonly List<PendingDecision> _pendingDecisions;

    public EpisodeStateMachine(Guid expectedEpisodeId)
    {
        if (expectedEpisodeId == Guid.Empty)
        {
            throw new ArgumentException("Episode ID cannot be empty.", nameof(expectedEpisodeId));
        }

        _expectedEpisodeId = expectedEpisodeId;
        _eventIds = [];
        _attemptIds = [];
        _manualCombatInputs = [];
        _pendingDecisions = [];
    }

    private EpisodeStateMachine(EpisodeStateMachine source)
    {
        _expectedEpisodeId = source._expectedEpisodeId;
        _eventIds = new HashSet<Guid>(source._eventIds);
        _attemptIds = new HashSet<Guid>(source._attemptIds);
        _manualCombatInputs = new Dictionary<Guid, ManualCombatInputState>(source._manualCombatInputs);
        _pendingDecisions = new List<PendingDecision>(source._pendingDecisions);
        Phase = source.Phase;
        Source = source.Source;
        Build = source.Build;
        RewardVersion = source.RewardVersion;
        NoSlExpected = source.NoSlExpected;
        NextEventSequence = source.NextEventSequence;
        NextGlobalStep = source.NextGlobalStep;
        TimelineGeneration = source.TimelineGeneration;
        LastEventHash = source.LastEventHash;
        ContainsSaveLoad = source.ContainsSaveLoad;
        SaveLoadCount = source.SaveLoadCount;
        UnknownSaveLoadCount = source.UnknownSaveLoadCount;
        RewindCount = source.RewindCount;
        InvalidatedPendingCount = source.InvalidatedPendingCount;
        UncertainExecutionCount = source.UncertainExecutionCount;
        CoverageGapCount = source.CoverageGapCount;
        ManualCombatInputCount = source.ManualCombatInputCount;
        UnresolvedManualCombatInputCount = source.UnresolvedManualCombatInputCount;
        UnstructuredManualCombatInputCount = source.UnstructuredManualCombatInputCount;
        UnstructuredUnsafeManualCombatInputCount =
            source.UnstructuredUnsafeManualCombatInputCount;
    }

    public EpisodePhase Phase { get; private set; } = EpisodePhase.New;

    public CollectorSource? Source { get; private set; }

    public BuildIdentity? Build { get; private set; }

    public string? RewardVersion { get; private set; }

    public bool NoSlExpected { get; private set; }

    public long NextEventSequence { get; private set; }

    public long NextGlobalStep { get; private set; }

    public int TimelineGeneration { get; private set; }

    public string LastEventHash { get; private set; } = CollectorJson.InitialPreviousHash;

    public bool ContainsSaveLoad { get; private set; }

    public int SaveLoadCount { get; private set; }

    public int UnknownSaveLoadCount { get; private set; }

    public int RewindCount { get; private set; }

    public int InvalidatedPendingCount { get; private set; }

    public int UncertainExecutionCount { get; private set; }

    public int CoverageGapCount { get; private set; }

    public int ManualCombatInputCount { get; private set; }

    public int UnresolvedManualCombatInputCount { get; private set; }

    public int UnstructuredManualCombatInputCount { get; private set; }

    public int UnstructuredUnsafeManualCombatInputCount { get; private set; }

    /// <summary>The oldest active decision, retained for legacy single-step callers.</summary>
    public PendingDecision? Pending => _pendingDecisions.Count == 0
        ? null
        : _pendingDecisions[0];

    public IReadOnlyList<PendingDecisionReference> PendingReferences =>
        _pendingDecisions.Select(pending => new PendingDecisionReference(
            pending.Decision.DecisionId,
            pending.GlobalStep,
            pending.Phase)).ToArray();

    public PendingDecision? FindPending(Guid decisionId) =>
        _pendingDecisions.FirstOrDefault(pending =>
            pending.Decision.DecisionId == decisionId);

    public void ValidateNext(CollectorEventEnvelope envelope)
    {
        var clone = new EpisodeStateMachine(this);
        clone.Apply(envelope);
    }

    public void Apply(CollectorEventEnvelope envelope)
    {
        ValidateEnvelope(envelope);
        switch (envelope.EventType)
        {
            case CollectorEventType.EpisodeStarted:
                ApplyStart(envelope);
                break;
            case CollectorEventType.Decision:
                ApplyDecision(envelope);
                break;
            case CollectorEventType.ActionSubmitted:
                ApplyAction(envelope);
                break;
            case CollectorEventType.ExecutionResult:
                ApplyExecution(envelope);
                break;
            case CollectorEventType.Reward:
                ApplyReward(envelope);
                break;
            case CollectorEventType.SaveLoad:
                ApplySaveLoad(envelope);
                break;
            case CollectorEventType.CoverageGap:
                ApplyCoverageGap(envelope);
                break;
            case CollectorEventType.Diagnostic:
                ApplyDiagnostic(envelope);
                break;
            case CollectorEventType.ManualCombatInput:
                ApplyManualCombatInput(envelope);
                break;
            case CollectorEventType.ManualCombatInputOutcome:
                ApplyManualCombatInputOutcome(envelope);
                break;
            case CollectorEventType.EpisodeFinished:
                ApplyFinish(envelope);
                break;
            default:
                throw new InvalidDataException(
                    $"Unsupported collector event type {envelope.EventType}.");
        }

        _eventIds.Add(envelope.EventId);
        LastEventHash = envelope.EventSha256;
        NextEventSequence++;
    }

    public EpisodeSnapshot Snapshot(bool published) => new(
        _expectedEpisodeId,
        Phase,
        NextEventSequence,
        NextGlobalStep,
        TimelineGeneration,
        ContainsSaveLoad,
        SaveLoadCount,
        UnknownSaveLoadCount,
        RewindCount,
        InvalidatedPendingCount,
        UncertainExecutionCount,
        CoverageGapCount,
        Pending?.Decision.DecisionId,
        Pending?.GlobalStep,
        Phase != EpisodePhase.Finished,
        published,
        ManualCombatInputCount,
        UnresolvedManualCombatInputCount,
        UnstructuredManualCombatInputCount,
        UnstructuredUnsafeManualCombatInputCount,
        PendingReferences);

    private void ValidateEnvelope(CollectorEventEnvelope envelope)
    {
        ArgumentNullException.ThrowIfNull(envelope);
        if (envelope.SchemaVersion != CollectorEventEnvelope.CurrentSchemaVersion)
        {
            throw new InvalidDataException(
                $"Unsupported collector schema {envelope.SchemaVersion}.");
        }

        if (!Enum.IsDefined(envelope.EventType)
            || !Enum.IsDefined(envelope.Source)
            || envelope.EventId == Guid.Empty
            || envelope.EpisodeId != _expectedEpisodeId)
        {
            throw new InvalidDataException("Collector event identity is invalid.");
        }

        if (_eventIds.Contains(envelope.EventId))
        {
            throw new InvalidDataException($"Duplicate collector event ID {envelope.EventId}.");
        }

        if (envelope.EventSequence != NextEventSequence)
        {
            throw new InvalidDataException(
                $"Expected event sequence {NextEventSequence}, "
                + $"found {envelope.EventSequence}.");
        }

        if (envelope.GlobalStep is < 0 || envelope.TimelineGeneration < 0)
        {
            throw new InvalidDataException("Collector event step or generation is invalid.");
        }

        if (envelope.RecordedAtUtc.Offset != TimeSpan.Zero)
        {
            throw new InvalidDataException("Collector timestamps must be UTC.");
        }

        CollectorJson.ValidateHash(
            envelope.PreviousEventSha256,
            nameof(envelope.PreviousEventSha256));
        CollectorJson.ValidateHash(envelope.EventSha256, nameof(envelope.EventSha256));
        if (!string.Equals(
                envelope.PreviousEventSha256,
                LastEventHash,
                StringComparison.Ordinal))
        {
            throw new InvalidDataException("Collector event hash chain is broken.");
        }

        var computedHash = CollectorJson.ComputeHash(envelope.WithoutHash());
        if (!string.Equals(computedHash, envelope.EventSha256, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Collector event content hash is invalid.");
        }

        if (Phase != EpisodePhase.New && envelope.Source != Source)
        {
            throw new InvalidDataException("Collector source changed within an episode.");
        }

        if (Phase == EpisodePhase.Finished)
        {
            throw new InvalidDataException("No event may follow episode_finished.");
        }
    }

    private void ApplyStart(CollectorEventEnvelope envelope)
    {
        if (Phase != EpisodePhase.New
            || envelope.EventSequence != 0
            || envelope.GlobalStep is not null
            || envelope.TimelineGeneration != 0
            || envelope.PreviousEventSha256 != CollectorJson.InitialPreviousHash)
        {
            throw new InvalidDataException("episode_started is not the first event.");
        }

        var payload = CollectorJson.ReadPayload<EpisodeStartedPayload>(envelope);
        ValidateBuild(payload.Build);
        RequireText(payload.CollectorRevision, "collector revision");
        RequireText(payload.RewardVersion, "reward version");
        ArgumentNullException.ThrowIfNull(payload.Metadata);
        foreach (var pair in payload.Metadata)
        {
            RequireText(pair.Key, "metadata key");
            ArgumentNullException.ThrowIfNull(pair.Value);
        }

        Source = envelope.Source;
        Build = payload.Build;
        RewardVersion = payload.RewardVersion;
        NoSlExpected = payload.NoSlExpected;
        Phase = EpisodePhase.Ready;
    }

    private void ApplyDecision(CollectorEventEnvelope envelope)
    {
        if (envelope.GlobalStep != NextGlobalStep
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("Decision step or generation is not current.");
        }

        var payload = CollectorJson.ReadPayload<DecisionPayload>(envelope);
        if (payload.DecisionId != envelope.EventId
            || payload.SourceDecisionIndex < 0
            || !Enum.IsDefined(payload.Domain)
            || !Enum.IsDefined(payload.InformationRegime))
        {
            throw new InvalidDataException("Decision identity is invalid.");
        }

        if (payload.QueuedCombatInput && payload.QueuedOutsideInput)
        {
            throw new InvalidDataException(
                "A decision cannot be queued in both combat and outside domains.");
        }

        if (payload.QueuedCombatInput)
        {
            if (payload.Domain != CollectorDecisionDomain.Combat
                || Phase == EpisodePhase.New
                || (_pendingDecisions.Count == 0 && Phase != EpisodePhase.Ready)
                || _pendingDecisions.Any(pending =>
                    pending.Decision.Domain != CollectorDecisionDomain.Combat
                    || pending.Phase == EpisodePhase.AwaitingAction))
            {
                throw new InvalidDataException(
                    "Queued combat decision requires a submitted combat-action queue.");
            }
        }
        else if (payload.QueuedOutsideInput)
        {
            if (payload.Domain != CollectorDecisionDomain.OutsideCombat
                || _pendingDecisions.Count == 0
                || _pendingDecisions.Any(pending =>
                    pending.Decision.Domain != CollectorDecisionDomain.OutsideCombat
                    || pending.Phase is not (EpisodePhase.AwaitingExecution
                        or EpisodePhase.AwaitingReward)))
            {
                throw new InvalidDataException(
                    "Queued outside decision requires a submitted, unsettled outside-action queue.");
            }
        }
        else
        {
            RequirePhase(EpisodePhase.Ready, envelope.EventType);
        }

        ProtocolJson.ValidateFingerprint(payload.StateFingerprint);
        ArgumentNullException.ThrowIfNull(payload.ActionKeys);
        if (payload.LegalActions.ValueKind != JsonValueKind.Array
            || payload.Observation.ValueKind != JsonValueKind.Object
            || payload.ActionKeys.Count == 0
            || payload.LegalActions.GetArrayLength() != payload.ActionKeys.Count
            || payload.ActionKeys.Any(string.IsNullOrWhiteSpace)
            || payload.ActionKeys.Distinct(StringComparer.Ordinal).Count()
                != payload.ActionKeys.Count)
        {
            throw new InvalidDataException("Decision actions or observation are invalid.");
        }

        ValidateDecisionProtocol(payload);
        if (payload.Context is { } context
            && context.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException(
                "Decision context must be a JSON object when present.");
        }

        _pendingDecisions.Add(new PendingDecision(payload, envelope.GlobalStep.Value));
        NextGlobalStep++;
        RefreshPhase();
    }

    private void ApplyAction(CollectorEventEnvelope envelope)
    {
        var payload = CollectorJson.ReadPayload<ActionSubmittedPayload>(envelope);
        var pending = FindPending(payload.DecisionId)
            ?? throw new InvalidDataException("Action has no pending decision.");
        if (pending.Phase != EpisodePhase.AwaitingAction)
        {
            throw new InvalidDataException("Action decision is not awaiting a submission.");
        }
        if (envelope.GlobalStep != pending.GlobalStep
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("Action step or generation does not match.");
        }

        if (payload.DecisionId != pending.Decision.DecisionId
            || payload.AttemptId == Guid.Empty
            || _attemptIds.Contains(payload.AttemptId)
            || payload.SelectedActionIndex < 0
            || payload.SelectedActionIndex >= pending.Decision.ActionKeys.Count
            || !string.Equals(
                payload.SelectedActionKey,
                pending.Decision.ActionKeys[payload.SelectedActionIndex],
                StringComparison.Ordinal))
        {
            throw new InvalidDataException("Submitted action does not match its decision.");
        }

        ValidateSubmittedSelection(
            pending.Decision.Domain,
            pending.Decision.Observation,
            pending.Decision.LegalActions,
            payload.SelectedActionIndex,
            payload.SelectedAction);
        ValidatePolicy(payload.Policy, pending.Decision.ActionKeys.Count);
        _attemptIds.Add(payload.AttemptId);
        ReplacePending(pending with
        {
            Submission = payload,
            Phase = EpisodePhase.AwaitingExecution,
        });
    }

    internal static void ValidateSubmittedSelection(
        CollectorDecisionDomain domain,
        JsonElement observationJson,
        JsonElement legalActions,
        int selectedActionIndex,
        JsonElement? selectedAction)
    {
        if (selectedAction is { ValueKind: not JsonValueKind.Object })
        {
            throw new InvalidDataException("Selected action must be a JSON object.");
        }

        var templateJson = legalActions[selectedActionIndex];
        if (domain == CollectorDecisionDomain.OutsideCombat)
        {
            var template = templateJson.Deserialize<OutsideCombatActionDescriptor>(
                CollectorJson.Options)
                ?? throw new InvalidDataException("Outside action template is missing.");
            if (!template.IsSelectionTemplate)
            {
                if (selectedAction is not null)
                {
                    throw new InvalidDataException(
                        "Concrete outside action is allowed only for a set template.");
                }
                return;
            }

            var selected = selectedAction?.Deserialize<OutsideCombatActionDescriptor>(
                CollectorJson.Options)
                ?? throw new InvalidDataException(
                    "Set-action submission requires its concrete selected cards.");
            var observation = observationJson.Deserialize<OutsideCombatObservation>(
                CollectorJson.Options)
                ?? throw new InvalidDataException("Outside observation is missing.");
            OutsideCombatDecisionPoint.ValidateSubmittedSetAction(
                observation, template, selected);
            return;
        }

        var combatTemplate = templateJson.Deserialize<CombatActionDescriptor>(
            CollectorJson.Options)
            ?? throw new InvalidDataException("Combat action template is missing.");
        if (!combatTemplate.IsSelectionTemplate)
        {
            if (selectedAction is not null)
            {
                throw new InvalidDataException(
                    "Concrete combat action is allowed only for a set template.");
            }
            return;
        }

        var combatSelected = selectedAction?.Deserialize<CombatActionDescriptor>(
            CollectorJson.Options)
            ?? throw new InvalidDataException(
                "Set-action submission requires its concrete selected cards.");
        var combatObservation = observationJson.Deserialize<CombatObservation>(
            CollectorJson.Options)
            ?? throw new InvalidDataException("Combat observation is missing.");
        CombatDecisionPoint.ValidateSubmittedSetAction(
            combatObservation, combatTemplate, combatSelected);
    }

    private void ApplyExecution(CollectorEventEnvelope envelope)
    {
        var payload = CollectorJson.ReadPayload<ExecutionResultPayload>(envelope);
        var pending = FindPending(payload.DecisionId)
            ?? throw new InvalidDataException("Execution has no pending decision.");
        if (pending.Phase != EpisodePhase.AwaitingExecution)
        {
            throw new InvalidDataException("Decision is not awaiting execution.");
        }
        var submission = pending.Submission
            ?? throw new InvalidDataException("Execution has no submitted action.");
        if (envelope.GlobalStep != pending.GlobalStep
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("Execution step or generation does not match.");
        }

        if (payload.DecisionId != pending.Decision.DecisionId
            || payload.AttemptId != submission.AttemptId
            || payload.SelectedActionIndex != submission.SelectedActionIndex
            || !string.Equals(
                payload.SelectedActionKey,
                submission.SelectedActionKey,
                StringComparison.Ordinal)
            || !string.Equals(
                payload.ExpectedStateFingerprint,
                pending.Decision.StateFingerprint,
                StringComparison.OrdinalIgnoreCase)
            || !Enum.IsDefined(payload.Status))
        {
            throw new InvalidDataException("Execution result does not match its action.");
        }

        ProtocolJson.ValidateFingerprint(payload.ExpectedStateFingerprint);
        if (payload.NextStateFingerprint is { } next)
        {
            ProtocolJson.ValidateFingerprint(next);
        }

        if (payload.Status is CollectorExecutionStatus.Failed
                or CollectorExecutionStatus.Rejected
                or CollectorExecutionStatus.TimedOut
                or CollectorExecutionStatus.Stale
            && string.IsNullOrWhiteSpace(payload.Detail))
        {
            throw new InvalidDataException(
                $"Execution status {payload.Status} requires diagnostic detail.");
        }

        if (payload.Status is CollectorExecutionStatus.Applied
            or CollectorExecutionStatus.ObservedTransition)
        {
            // Native execution order can differ from click order: a parent
            // action may open a child selector before a previously queued
            // manual action executes. The IDs, not queue position, identify
            // which decision this result advances.
            ReplacePending(pending with { Phase = EpisodePhase.AwaitingReward });
        }
        else if (payload.Status == CollectorExecutionStatus.Rejected)
        {
            // Rejected means the action was definitively not submitted, so the
            // same observation can accept another uniquely identified attempt.
            ReplacePending(pending with
            {
                Submission = null,
                Phase = EpisodePhase.AwaitingAction,
            });
        }
        else
        {
            // Failed/timed-out outcomes do not prove zero side effects. Stale
            // proves the expected observation no longer describes reality.
            // Both are audit-worthy gaps; cancelled is the only clean abandon.
            if (payload.Status is CollectorExecutionStatus.Failed
                or CollectorExecutionStatus.TimedOut
                or CollectorExecutionStatus.Stale)
            {
                UncertainExecutionCount++;
            }

            RemovePending(pending);
        }
    }

    private void ApplyReward(CollectorEventEnvelope envelope)
    {
        var payload = CollectorJson.ReadPayload<RewardPayload>(envelope);
        var pending = FindPending(payload.DecisionId)
            ?? throw new InvalidDataException("Reward has no pending decision.");
        if (pending.Phase != EpisodePhase.AwaitingReward)
        {
            throw new InvalidDataException("Decision is not awaiting a reward.");
        }
        if (envelope.GlobalStep != pending.GlobalStep
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("Reward step or generation does not match.");
        }

        if (payload.DecisionId != pending.Decision.DecisionId
            || !string.Equals(payload.RewardVersion, RewardVersion, StringComparison.Ordinal)
            || payload.Components is null
            || payload.Components.Count == 0)
        {
            throw new InvalidDataException("Reward does not match its decision or version.");
        }

        foreach (var component in payload.Components)
        {
            RequireText(component.Key, "reward component");
            if (!double.IsFinite(component.Value))
            {
                throw new InvalidDataException("Reward components must be finite.");
            }
        }

        RemovePending(pending);
    }

    private void ApplySaveLoad(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New)
        {
            throw new InvalidDataException("save_load cannot precede episode_started.");
        }

        if (envelope.TimelineGeneration != TimelineGeneration + 1)
        {
            throw new InvalidDataException("save_load did not advance timeline generation.");
        }

        var payload = CollectorJson.ReadPayload<SaveLoadPayload>(envelope);
        RequireText(payload.Reason, "save/load reason");
        if (!Enum.IsDefined(payload.Kind)
            || payload.FromTimelineGeneration != TimelineGeneration
            || payload.ToTimelineGeneration != TimelineGeneration + 1
            || payload.InvalidatedPhase != Phase
            || payload.InvalidatedDecisionId != Pending?.Decision.DecisionId
            || payload.InvalidatedGlobalStep != Pending?.GlobalStep
            || envelope.GlobalStep != Pending?.GlobalStep
            || payload.CreatesDataGap != (Pending is not null)
            || !ReferencesMatch(payload.InvalidatedDecisions))
        {
            throw new InvalidDataException("save_load invalidation metadata is inconsistent.");
        }

        ValidateOptionalFingerprint(payload.BeforeStateFingerprint);
        ValidateOptionalFingerprint(payload.RestoredStateFingerprint);
        if (payload.CheckpointSha256 is { } checkpoint)
        {
            CollectorJson.ValidateHash(checkpoint, "checkpoint_sha256");
        }

        TimelineGeneration++;
        ContainsSaveLoad = true;
        SaveLoadCount++;
        if (payload.Kind == SaveLoadKind.Unknown)
        {
            UnknownSaveLoadCount++;
        }
        if (payload.Kind == SaveLoadKind.Rewind)
        {
            RewindCount++;
        }

        if (payload.CreatesDataGap)
        {
            InvalidatedPendingCount += _pendingDecisions.Count;
        }

        _pendingDecisions.Clear();
        RefreshPhase();
    }

    private void ApplyCoverageGap(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("coverage_gap header is invalid.");
        }

        var payload = CollectorJson.ReadPayload<CoverageGapPayload>(envelope);
        RequireText(payload.Reason, "coverage-gap reason");
        if (payload.RelatedDecisionId == Guid.Empty
            || payload.RelatedAttemptId == Guid.Empty
            || payload.TargetDecisionId == Guid.Empty
            || (payload.RelatedAttemptId is not null
                && payload.RelatedDecisionId is null)
            || (payload.TargetDecisionId is not null
                && !payload.InvalidatesPendingDecision))
        {
            throw new InvalidDataException(
                "coverage_gap related decision or attempt is invalid.");
        }
        if (payload.InvalidatedPhase != Phase)
        {
            throw new InvalidDataException(
                "coverage_gap invalidation metadata is inconsistent.");
        }

        if (payload.InvalidatesPendingDecision)
        {
            var pending = payload.TargetDecisionId is { } targetDecisionId
                ? FindPending(targetDecisionId)
                : Pending;
            pending = pending
                ?? throw new InvalidDataException(
                    "coverage_gap cannot invalidate a missing decision.");
            var referencesMatch = payload.TargetDecisionId is null
                ? ReferencesMatch(payload.InvalidatedDecisions)
                : payload.InvalidatedDecisions is { Count: 1 }
                    && payload.InvalidatedDecisions[0].DecisionId
                        == pending.Decision.DecisionId
                    && payload.InvalidatedDecisions[0].GlobalStep
                        == pending.GlobalStep
                    && payload.InvalidatedDecisions[0].Phase == pending.Phase;
            if (payload.InvalidatedDecisionId != pending.Decision.DecisionId
                || payload.InvalidatedGlobalStep != pending.GlobalStep
                || envelope.GlobalStep != pending.GlobalStep
                || !referencesMatch)
            {
                throw new InvalidDataException(
                    "coverage_gap pending-decision metadata is inconsistent.");
            }

            if (payload.TargetDecisionId is null)
            {
                _pendingDecisions.Clear();
                RefreshPhase();
            }
            else
            {
                RemovePending(pending);
            }
        }
        else if (payload.InvalidatedDecisionId is not null
                 || payload.InvalidatedGlobalStep is not null
                 || envelope.GlobalStep is not null
                 || !ReferencesMatch(payload.InvalidatedDecisions, expectEmpty: true))
        {
            throw new InvalidDataException(
                "A detached coverage_gap cannot reference the current decision.");
        }

        CoverageGapCount++;
    }

    private void ApplyFinish(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New
            || envelope.GlobalStep is not null
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("episode_finished header is invalid.");
        }

        var payload = CollectorJson.ReadPayload<EpisodeFinishedPayload>(envelope);
        var hasUnsafeInputCount = envelope.Payload.TryGetProperty(
            "unstructured_unsafe_manual_combat_input_count", out _);
        RequireText(payload.Outcome, "episode outcome");
        RequireText(payload.TerminationReason, "termination reason");
        if (!Enum.IsDefined(payload.Completeness)
            || payload.PreviousPhase != Phase
            || payload.ContainsSaveLoad != ContainsSaveLoad
            || payload.SaveLoadCount != SaveLoadCount
            || payload.UnknownSaveLoadCount != UnknownSaveLoadCount
            || payload.RewindCount != RewindCount
            || payload.InvalidatedPendingCount != InvalidatedPendingCount
            || payload.UncertainExecutionCount != UncertainExecutionCount
            || payload.CoverageGapCount != CoverageGapCount
            || payload.ManualCombatInputCount != ManualCombatInputCount
            || payload.UnresolvedManualCombatInputCount != UnresolvedManualCombatInputCount
            || payload.UnstructuredManualCombatInputCount != UnstructuredManualCombatInputCount
            || hasUnsafeInputCount
                && payload.UnstructuredUnsafeManualCombatInputCount
                    != UnstructuredUnsafeManualCombatInputCount
            || payload.IncompleteDecisionId != Pending?.Decision.DecisionId
            || !ReferencesMatch(payload.IncompleteDecisions))
        {
            throw new InvalidDataException("episode_finished metadata is inconsistent.");
        }

        if (payload.Completeness == EpisodeCompleteness.Complete
            && (_pendingDecisions.Count != 0
                || UnresolvedManualCombatInputCount != 0
                || (hasUnsafeInputCount
                    ? UnstructuredUnsafeManualCombatInputCount != 0
                    : UnstructuredManualCombatInputCount != 0)
                || string.Equals(payload.Outcome, "abandoned", StringComparison.OrdinalIgnoreCase)
                || string.Equals(payload.Outcome, "interrupted", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException(
                "A complete episode cannot be pending, abandoned, or interrupted.");
        }

        var expectedValueTarget = payload.Completeness == EpisodeCompleteness.Complete
            && _pendingDecisions.Count == 0
            && UnknownSaveLoadCount == 0
            && RewindCount == 0
            && InvalidatedPendingCount == 0
            && UncertainExecutionCount == 0
            && CoverageGapCount == 0
            && UnresolvedManualCombatInputCount == 0
            && (hasUnsafeInputCount
                ? UnstructuredUnsafeManualCombatInputCount == 0
                : UnstructuredManualCombatInputCount == 0);
        if (payload.ValueTargetValid != expectedValueTarget)
        {
            throw new InvalidDataException("episode value-target validity is inconsistent.");
        }

        if (payload.Summary is { ValueKind: JsonValueKind.Undefined })
        {
            throw new InvalidDataException("Episode summary cannot be undefined JSON.");
        }

        _pendingDecisions.Clear();
        Phase = EpisodePhase.Finished;
    }

    private void ApplyDiagnostic(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New
            || envelope.GlobalStep is not null
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("Diagnostic event header is invalid.");
        }

        var payload = CollectorJson.ReadPayload<DiagnosticPayload>(envelope);
        RequireText(payload.Code, "diagnostic code");
        if (payload.Data.ValueKind == JsonValueKind.Undefined)
        {
            throw new InvalidDataException("Diagnostic data cannot be undefined JSON.");
        }
    }

    private void ApplyManualCombatInput(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New
            || envelope.GlobalStep is not null
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("manual_combat_input header is invalid.");
        }

        var payload = CollectorJson.ReadPayload<ManualCombatInputPayload>(envelope);
        if (payload.IntentId == Guid.Empty
            || payload.NativeActionId < 0
            || _manualCombatInputs.ContainsKey(payload.IntentId)
            || payload.RelatedDecisionId == Guid.Empty
            || payload.RelatedAttemptId == Guid.Empty
            || (payload.RelatedDecisionId is null) != (payload.RelatedAttemptId is null)
            || (payload.RelatedDecisionId is not null
                && FindPending(payload.RelatedDecisionId.Value)?.Submission?.AttemptId
                    != payload.RelatedAttemptId)
            || payload.Data.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidDataException("manual_combat_input identity or data is invalid.");
        }

        RequireText(payload.ActionKind, "manual-combat-input action kind");
        _manualCombatInputs.Add(payload.IntentId,
            new ManualCombatInputState(
                payload.NativeActionId,
                TimelineGeneration,
                HasOutcome: false,
                IsStructured: payload.RelatedDecisionId is not null));
        ManualCombatInputCount++;
        UnresolvedManualCombatInputCount++;
        if (payload.RelatedDecisionId is null)
        {
            UnstructuredManualCombatInputCount++;
        }
    }

    private void ApplyManualCombatInputOutcome(CollectorEventEnvelope envelope)
    {
        if (Phase == EpisodePhase.New
            || envelope.GlobalStep is not null
            || envelope.TimelineGeneration != TimelineGeneration)
        {
            throw new InvalidDataException("manual_combat_input_outcome header is invalid.");
        }

        var payload = CollectorJson.ReadPayload<ManualCombatInputOutcomePayload>(envelope);
        if (payload.IntentId == Guid.Empty
            || payload.NativeActionId < 0
            || !Enum.IsDefined(payload.Status)
            || !_manualCombatInputs.TryGetValue(payload.IntentId, out var intent)
            || intent.HasOutcome
            || intent.NativeActionId != payload.NativeActionId
            || intent.TimelineGeneration != TimelineGeneration
            || payload.Detail is not null && string.IsNullOrWhiteSpace(payload.Detail)
            || payload.Data is { ValueKind: JsonValueKind.Undefined or JsonValueKind.Null })
        {
            throw new InvalidDataException("manual_combat_input_outcome does not match one open input.");
        }

        _manualCombatInputs[payload.IntentId] = intent with { HasOutcome = true };
        UnresolvedManualCombatInputCount--;
        if (!intent.IsStructured && payload.Status is not
            (CollectorExecutionStatus.Cancelled or CollectorExecutionStatus.Rejected))
        {
            UnstructuredUnsafeManualCombatInputCount++;
        }
    }

    private bool ReferencesMatch(
        IReadOnlyList<PendingDecisionReference>? references,
        bool expectEmpty = false)
    {
        if (references is null)
        {
            // Existing schema-v1 JSONL only stored the oldest pending ID and
            // step. It remains replayable, but cannot describe a multi-input
            // invalidation. New writes always include the full list.
            return expectEmpty || _pendingDecisions.Count <= 1;
        }

        if (expectEmpty)
        {
            return references.Count == 0;
        }

        return references.Count == _pendingDecisions.Count
            && references.Zip(_pendingDecisions).All(pair =>
                pair.First.DecisionId == pair.Second.Decision.DecisionId
                && pair.First.GlobalStep == pair.Second.GlobalStep
                && pair.First.Phase == pair.Second.Phase);
    }

    private void ReplacePending(PendingDecision replacement)
    {
        var index = _pendingDecisions.FindIndex(pending =>
            pending.Decision.DecisionId == replacement.Decision.DecisionId);
        if (index < 0)
        {
            throw new InvalidDataException("Decision is no longer pending.");
        }

        _pendingDecisions[index] = replacement;
        RefreshPhase();
    }

    private void RemovePending(PendingDecision pending)
    {
        var index = _pendingDecisions.FindIndex(candidate =>
            candidate.Decision.DecisionId == pending.Decision.DecisionId);
        if (index < 0)
        {
            throw new InvalidDataException("Decision is no longer pending.");
        }

        _pendingDecisions.RemoveAt(index);
        RefreshPhase();
    }

    private void RefreshPhase()
    {
        Phase = Pending?.Phase ?? EpisodePhase.Ready;
    }

    private void ValidateDecisionProtocol(DecisionPayload payload)
    {
        if (payload.Domain == CollectorDecisionDomain.Combat)
        {
            if (payload.Build is not null)
            {
                throw new InvalidDataException("Combat decision must use episode build identity.");
            }

            var observation = payload.Observation.Deserialize<CombatObservation>(
                CollectorJson.Options)
                ?? throw new InvalidDataException("Combat observation is missing.");
            var actions = payload.LegalActions.Deserialize<CombatActionDescriptor[]>(
                CollectorJson.Options)
                ?? throw new InvalidDataException("Combat actions are missing.");
            new CombatDecisionPoint(
                CombatDecisionPoint.CurrentSchemaVersion,
                payload.SourceDecisionIndex,
                payload.StateFingerprint,
                observation,
                actions).Validate();
            var expectedKeys = actions
                .Select(DecisionInput.ComputeCombatActionKey)
                .ToArray();
            RequireActionKeys(payload.ActionKeys, expectedKeys);
            return;
        }

        if (payload.Build is null || payload.Build != Build)
        {
            throw new InvalidDataException(
                "Outside-combat decision build differs from episode build.");
        }

        var outsideObservation = payload.Observation.Deserialize<OutsideCombatObservation>(
            CollectorJson.Options)
            ?? throw new InvalidDataException("Outside-combat observation is missing.");
        var outsideActions = payload.LegalActions.Deserialize<OutsideCombatActionDescriptor[]>(
            CollectorJson.Options)
            ?? throw new InvalidDataException("Outside-combat actions are missing.");
        new OutsideCombatDecisionPoint(
            OutsideCombatDecisionPoint.CurrentSchemaVersion,
            payload.Build,
            payload.SourceDecisionIndex,
            payload.StateFingerprint,
            outsideObservation,
            outsideActions).Validate();
        RequireActionKeys(
            payload.ActionKeys,
            outsideActions.Select(action => action.ActionId));
    }

    private static void RequireActionKeys(
        IReadOnlyList<string> recorded,
        IEnumerable<string> expected)
    {
        if (!recorded.SequenceEqual(expected, StringComparer.Ordinal))
        {
            throw new InvalidDataException(
                "Decision action keys do not match the serialized legal actions.");
        }
    }

    private static void ValidatePolicy(PolicyTrace policy, int actionCount)
    {
        ArgumentNullException.ThrowIfNull(policy);
        if (!Enum.IsDefined(policy.Actor)
            || policy.PolicyId is not null && string.IsNullOrWhiteSpace(policy.PolicyId)
            || policy.Actor != ActionActor.Human && policy.PolicyId is null
            || policy.ModelRevision is not null && string.IsNullOrWhiteSpace(policy.ModelRevision))
        {
            throw new InvalidDataException("Policy metadata is invalid.");
        }

        if (policy.Logits is { } logits
            && (logits.Count != actionCount || logits.Any(value => !double.IsFinite(value))))
        {
            throw new InvalidDataException("Policy logits must be finite and action-aligned.");
        }

        if (policy.MctsVisitCounts is { } visits
            && (visits.Count != actionCount
                || visits.Any(value => value < 0)
                || visits.All(value => value == 0)))
        {
            throw new InvalidDataException(
                "MCTS visits must be non-negative, non-empty, and action-aligned.");
        }
    }

    private static void ValidateBuild(BuildIdentity build)
    {
        ArgumentNullException.ThrowIfNull(build);
        RequireText(build.GameVersion, "game version");
        ProtocolJson.ValidateFingerprint(build.AssemblySha256);
        if (!Guid.TryParse(build.AssemblyModuleVersionId, out _))
        {
            throw new InvalidDataException("Build module version ID is invalid.");
        }
    }

    private static void ValidateOptionalFingerprint(string? value)
    {
        if (value is not null)
        {
            ProtocolJson.ValidateFingerprint(value);
        }
    }

    private static void RequireText(string? value, string name)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new InvalidDataException($"Collector {name} cannot be empty.");
        }
    }

    private void RequirePhase(EpisodePhase expected, CollectorEventType eventType)
    {
        if (Phase != expected)
        {
            throw new InvalidDataException(
                $"Event {eventType} requires phase {expected}, found {Phase}.");
        }
    }
}
