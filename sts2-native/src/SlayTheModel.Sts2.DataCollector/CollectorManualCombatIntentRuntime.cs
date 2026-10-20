using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.GameActions;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed class PendingManualCombatIntent(
    Guid intentId,
    long nativeActionId,
    long runtimeGeneration,
    bool hasStructuredStep,
    bool queuedAtClick,
    CombatActionDescriptor action,
    string? unstructuredGapReason,
    Guid? overlappingParentAttemptId)
{
    internal Guid IntentId { get; } = intentId;
    internal long NativeActionId { get; } = nativeActionId;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal bool HasStructuredStep { get; } = hasStructuredStep;
    internal bool QueuedAtClick { get; } = queuedAtClick;
    internal CombatActionDescriptor Action { get; } = action;
    internal string? UnstructuredGapReason { get; } = unstructuredGapReason;
    internal Guid? OverlappingParentAttemptId { get; } = overlappingParentAttemptId;
    internal DateTimeOffset? ExecutionStartedAtUtc { get; set; }
    internal CombatObservation? ExecutionStartObservation { get; set; }
    internal string? ExecutionStartCaptureFailure { get; set; }
}

internal static partial class CollectorRuntime
{
    private static readonly Dictionary<GameAction, PendingManualCombatIntent>
        PendingManualCombatIntents = new(ReferenceEqualityComparer.Instance);

    private static IReadOnlyList<CombatActionDescriptor> PendingManualActionsAtClick() =>
        PendingManualCombatIntents.Values
            .Where(intent => intent.RuntimeGeneration == _runGeneration)
            .OrderBy(intent => intent.NativeActionId)
            .Select(intent => intent.Action)
            .ToArray();

    private static void TrackManualCombatInput(
        GameAction action,
        CombatActionDescriptor descriptor,
        ManualCombatInputEvidence evidence,
        CollectorActionDraft? ownDraft = null,
        CollectorActionDraft? overlappingParent = null,
        string? unstructuredGapReason = null)
    {
        var episodes = _episodes;
        if (episodes?.HasActiveEpisode != true)
        {
            return;
        }

        var intentId = Guid.NewGuid();
        var nativeActionId = action.Id is { } nativeId
            ? checked((long)nativeId)
            : throw new InvalidDataException(
                "Native GameAction ID is missing at the enqueue boundary.");
        var captured = evidence.PreSubmissionDecision;
        var data = JsonSerializer.SerializeToElement(
            new
            {
                evidence.InputAtUtc,
                Action = descriptor,
                ClickObservation = evidence.ClickObservation,
                ClickObservationStatus = captured is not null
                    ? evidence.QueuedAtClick
                        ? "queued_legal_set"
                        : "structured_legal_set"
                    : evidence.ClickObservation is not null
                        ? "internal_only_unstable"
                        : "unavailable",
                ClickLegalActions = captured?.Decision.LegalActions,
                ClickObservationFingerprint = captured?.ObservationFingerprint,
                evidence.CaptureFailure,
                evidence.QueuedAtClick,
                OverlapsDecisionId = overlappingParent?.Receipt.DecisionId,
                OverlapsAttemptId = overlappingParent?.AttemptId,
                NativeActionStateAtEnqueue = action.State.ToString(),
            },
            ProtocolJson.Options);
        if (!episodes.RecordManualCombatInput(new ManualCombatInputInput(
                Guid.NewGuid(),
                intentId,
                nativeActionId,
                descriptor.Kind.ToString(),
                data,
                ownDraft?.Receipt.DecisionId,
                ownDraft?.AttemptId)))
        {
            return;
        }

        PendingManualCombatIntents[action] = new PendingManualCombatIntent(
            intentId,
            nativeActionId,
            _runGeneration,
            ownDraft is not null,
            evidence.QueuedAtClick,
            descriptor,
            unstructuredGapReason,
            overlappingParent?.AttemptId);
    }

    private static void OnManualCombatActionStarting(GameAction action)
    {
        if (!PendingManualCombatIntents.TryGetValue(action, out var intent)
            || intent.RuntimeGeneration != _runGeneration)
        {
            return;
        }

        try
        {
            // A verified next player decision is a causal boundary for the
            // previous action. An unstructured transition click may execute
            // during an enemy or turn-transition phase, so it cannot prove
            // the previous reward is ready to settle.
            if (intent.HasStructuredStep)
            {
                _episodes?.ResolveAtCurrentBoundary();
            }
            else if (_episodes?.StagedActionAwaitingBoundary is { } parent)
            {
                _episodes.MarkTransitionContaminated(parent);
            }
            if (intent.QueuedAtClick
                && PendingCombatActions.TryGetValue(action, out var draft)
                && _episodes is { } episodes)
            {
                PendingCombatActions[action] = episodes.AtCombatExecutionStart(draft);
            }

            if (!intent.HasStructuredStep || intent.QueuedAtClick)
            {
                intent.ExecutionStartedAtUtc = DateTimeOffset.UtcNow;
                intent.ExecutionStartObservation = TryCaptureManualIntentObservation(
                    out var failure);
                intent.ExecutionStartCaptureFailure = failure;
            }
        }
        catch (Exception exception)
        {
            if (_episodes?.StagedActionAwaitingBoundary is { } parent)
            {
                _episodes.MarkTransitionContaminated(parent);
            }
            RecordCoverageGap(
                "manual_combat_execution_boundary_failed",
                new { native_action_id = action.Id, error = exception.ToString() },
                invalidatePendingDecision: false);
        }
    }

    private static bool FinishManualCombatInput(
        GameAction action,
        CollectorExecutionStatus status,
        string? detail)
    {
        if (!PendingManualCombatIntents.Remove(action, out var intent)
            || intent.RuntimeGeneration != _runGeneration)
        {
            return false;
        }

        CombatObservation? endObservation = null;
        string? endFailure = null;
        if (!intent.HasStructuredStep || intent.QueuedAtClick)
        {
            endObservation = TryCaptureManualIntentObservation(out endFailure);
        }

        var data = JsonSerializer.SerializeToElement(
            new
            {
                intent.ExecutionStartedAtUtc,
                intent.ExecutionStartObservation,
                intent.ExecutionStartCaptureFailure,
                ExecutionFinishedAtUtc = DateTimeOffset.UtcNow,
                ExecutionEndObservation = endObservation,
                ExecutionEndCaptureFailure = endFailure,
            },
            ProtocolJson.Options);
        _episodes?.RecordManualCombatInputOutcome(new ManualCombatInputOutcomeInput(
            Guid.NewGuid(),
            intent.IntentId,
            intent.NativeActionId,
            status,
            detail,
            data));
        if (intent.UnstructuredGapReason is { } gapReason
            && status is not (CollectorExecutionStatus.Cancelled
                or CollectorExecutionStatus.Rejected))
        {
            RecordCoverageGap(
                gapReason,
                new
                {
                    native_action_id = intent.NativeActionId,
                    intent_id = intent.IntentId,
                    overlapping_parent_attempt_id = intent.OverlappingParentAttemptId,
                    execution_status = status.ToString(),
                },
                invalidatePendingDecision: false);
        }
        return true;
    }

    private static CombatObservation? TryCaptureManualIntentObservation(
        out string? failure)
    {
        try
        {
            if (CombatManager.Instance.DebugOnlyGetState() is not { } state)
            {
                failure = "Native combat state unavailable.";
                return null;
            }

            var pendingActions = PendingManualActionsAtClick();
            failure = null;
            return CollectorCombatProjector.CaptureInternalObservation(state) with
            {
                PendingManualActions = pendingActions,
            };
        }
        catch (Exception exception)
        {
            failure = exception.ToString();
            return null;
        }
    }
}
