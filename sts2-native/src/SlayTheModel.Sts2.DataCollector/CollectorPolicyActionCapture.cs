using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.GameActions;
using SlayTheModel.Collector;

namespace SlayTheModel.Sts2.DataCollector;

internal static partial class CollectorRuntime
{
    private sealed record PolicyActionInput(
        ManualCombatInputEvidence Input,
        PolicyTrace Policy,
        object? SearchSummary,
        long Generation);

    private static readonly Dictionary<GameAction, PolicyActionInput> PolicyActionInputs =
        new(ReferenceEqualityComparer.Instance);
    private static readonly HashSet<GameAction> CapturedPolicyActions =
        new(ReferenceEqualityComparer.Instance);

    internal static void ObservePolicyActionSubmitting(GameAction action, string policyJson)
    {
        if (_stopping || _episodes?.HasActiveEpisode != true || _actionQueue is null) return;
        try
        {
            var policy = CollectorPolicyOrigin.Parse(policyJson);
            var summary = CollectorPolicyOrigin.SearchSummary(policyJson);
            if (PolicyActionInputs.ContainsKey(action))
                throw new InvalidDataException("One native action received two policy submissions.");
            // The exact native object is still unqueued here, so its internal
            // hand and legal set are frozen before GameAction.OnEnqueued.
            PolicyActionInputs.Add(action, new PolicyActionInput(
                CaptureManualCombatPreState(), policy, summary, _runGeneration));
        }
        catch (Exception exception)
        {
            RecordCoverageGap("policy_action_origin_capture_failed",
                new { error = exception.ToString() }, invalidatePendingDecision: false);
        }
    }

    private static void ClearPolicyActionInputs()
    {
        PolicyActionInputs.Clear();
        CapturedPolicyActions.Clear();
    }

    private static void OnPolicyActionStarting(GameAction action)
    {
        if (!CapturedPolicyActions.Contains(action)
            || !PendingCombatActions.TryGetValue(action, out var draft)) return;
        try
        {
            _episodes?.ResolveAtCurrentBoundary();
            if (_episodes is not null)
                PendingCombatActions[action] = _episodes.AtCombatExecutionStart(draft);
        }
        catch (Exception exception)
        {
            RecordCoverageGap("policy_action_execution_boundary_failed",
                new { error = exception.ToString() }, invalidatePendingDecision: false,
                relatedDecisionId: draft.Receipt.DecisionId, relatedAttemptId: draft.AttemptId);
        }
    }

    private static bool TryCapturePolicyAction(GameAction action, bool hasManualEvidence)
    {
        if (!PolicyActionInputs.Remove(action, out var input)) return false;
        if (input.Generation != _runGeneration || _episodes?.HasActiveEpisode != true) return true;
        Guid? decisionId = null;
        try
        {
            if (hasManualEvidence)
                throw new InvalidDataException("Native action has conflicting human and policy origins.");
            if (!CombatManager.Instance.IsInProgress)
                throw new InvalidDataException("Policy action was submitted outside an active combat.");
            var descriptor = CollectorCombatProjector.Describe(action)
                ?? throw new InvalidDataException("Policy submitted an unsupported native action.");
            var captured = input.Input.PreSubmissionDecision
                ?? throw new InvalidDataException(input.Input.CaptureFailure ?? "Policy prestate unavailable.");
            var index = CollectorCombatProjector.FindAction(captured.Decision.LegalActions, descriptor);
            if (index < 0) throw new InvalidDataException("Policy action is absent from its frozen legal set.");
            var kind = action switch
            {
                PlayCardAction => "play_card",
                UsePotionAction => "use_potion",
                EndPlayerTurnAction => "end_turn",
                _ => "combat_action",
            };
            var draft = PendingCombatActions.Count > 0 || input.Input.QueuedAtClick
                ? _episodes.DraftQueuedCombat(captured, index, kind, input.Policy)
                : _episodes.DraftCombat(captured, index, kind, input.Policy);
            decisionId = draft.Receipt.DecisionId;
            PendingCombatActions.Add(action, draft);
            CapturedPolicyActions.Add(action);
            _episodes.RecordDiagnostic("policy_action_origin", new
            {
                decision_id = draft.Receipt.DecisionId,
                attempt_id = draft.AttemptId,
                policy_id = input.Policy.PolicyId,
                teacher_information = input.Policy.TeacherInformation,
                search = input.SearchSummary,
            });
        }
        catch (Exception exception)
        {
            RecordCoverageGap("policy_action_capture_failed",
                new { error = exception.ToString(), policy_id = input.Policy.PolicyId },
                invalidatePendingDecision: decisionId is not null,
                targetDecisionId: decisionId);
        }
        return true;
    }
}
