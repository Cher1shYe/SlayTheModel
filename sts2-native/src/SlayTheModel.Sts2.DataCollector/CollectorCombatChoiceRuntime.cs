using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed class PendingCombatCardChoice(
    object selector,
    IReadOnlyList<CardModel> options,
    CapturedCombatDecision? captured,
    bool canCancel,
    bool requiresManualConfirmation,
    bool expectsNativeCombatCardResult,
    string description,
    long runtimeGeneration,
    Guid? combatId)
{
    internal object Selector { get; } = selector;
    internal IReadOnlyList<CardModel> Options { get; } = options;
    internal CapturedCombatDecision? Captured { get; set; } = captured;
    internal bool CanCancel { get; } = canCancel;
    internal bool RequiresManualConfirmation { get; } = requiresManualConfirmation;
    internal bool ExpectsNativeCombatCardResult { get; } = expectsNativeCombatCardResult;
    internal string Description { get; } = description;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal Guid? CombatId { get; } = combatId;
    internal PreparedCombatChoice? Prepared { get; set; }
    internal Guid? SubmittedAttemptId { get; set; }
    internal Task<IEnumerable<CardModel>>? CompletionTask { get; set; }
    internal IReadOnlyList<uint>? NativeSelectedCardIds { get; set; }
    internal IReadOnlyList<uint>? TaskSelectedCardIds { get; set; }
    internal IReadOnlyList<int>? NativeSelectedOptionIndexes { get; set; }
    internal IReadOnlyList<int>? TaskSelectedOptionIndexes { get; set; }
    internal bool NativeResultObserved { get; set; }
    internal bool NativeResultCompared { get; set; }
    internal bool Completed { get; set; }
    internal bool UnboundReceiptSuperseded { get; set; }
    internal uint? NativeChoiceId { get; set; }
    internal uint? ParentActionId { get; set; }
    internal bool HandConfirmationObserved { get; set; }
    internal IReadOnlyList<CardModel>? HandConfirmedCards { get; set; }
    internal bool IsMctsRequest { get; set; }
    internal object? ManualFallbackSelector { get; set; }
    internal Task<IEnumerable<CardModel>>? ManualFallbackTask { get; set; }
    internal PolicyTrace? PolicyOverride { get; set; }
}

internal static partial class CollectorRuntime
{
    private static readonly Dictionary<object, PendingCombatCardChoice> PendingCombatChoices =
        new(ReferenceEqualityComparer.Instance);
    private static readonly List<PendingCombatCardChoice> NativeCombatChoiceTickets = [];
    private static readonly Dictionary<object, PendingCombatCardChoice> MctsFallbackChoices =
        new(ReferenceEqualityComparer.Instance);
    private static readonly HashSet<GameAction> EarlySettledCombatActions =
        new(ReferenceEqualityComparer.Instance);
    private static (uint ChoiceId, uint? ParentActionId, Guid CombatId, long Generation)?
        _lastReservedNativeChoice;

    internal static void NoteReservedNativeChoiceId(Player player, uint choiceId)
    {
        if (_episodes?.HasActiveEpisode != true)
        {
            return;
        }

        var combatInProgress = CombatManager.Instance.IsInProgress;
        bool? isLocalPlayer = combatInProgress && _combatId is not null
            ? IsLocalSinglePlayer(player)
            : null;
        if (!combatInProgress || _combatId is not { } combatId || isLocalPlayer != true)
        {
            if (combatInProgress || _combatId is not null)
            {
                RecordDiagnostic("native_combat_choice_id_reservation_ignored", new
                {
                    choice_id = choiceId,
                    combat_in_progress = combatInProgress,
                    combat_id = _combatId,
                    local_player = isLocalPlayer,
                });
            }

            return;
        }

        var parentActionId = RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id;
        // Some native choices reserve their ID after CardsSelected has opened
        // the selector. Bind that late reservation to the one frozen selector
        // under this action instead of leaving its ticket without an ID.
        var awaiting = NativeCombatChoiceTickets
            .Where(item => item.RuntimeGeneration == _runGeneration
                           && item.CombatId == combatId
                           && item.ParentActionId == parentActionId
                           && item.NativeChoiceId is null
                           && !item.Completed
                           && item.CompletionTask?.IsCompleted != true
                           && PendingCombatChoices.TryGetValue(item.Selector, out var active)
                           && ReferenceEquals(active, item)
                           && item.Captured is not null)
            .ToArray();
        if (awaiting.Length == 1)
        {
            awaiting[0].NativeChoiceId = choiceId;
            _lastReservedNativeChoice = null;
            RecordDiagnostic("native_combat_choice_id_reserved", new
            {
                choice_id = choiceId,
                parent_action_id = parentActionId,
                binding = "active_selector",
            });
            return;
        }

        RecordDiagnostic("native_combat_choice_id_reserved", new
        {
            choice_id = choiceId,
            parent_action_id = parentActionId,
            awaiting_selector_count = awaiting.Length,
            binding = "buffered",
        });
        _lastReservedNativeChoice = (
            choiceId,
            parentActionId,
            combatId,
            _runGeneration);
    }

    private static uint? TakeReservedNativeChoiceId(uint? parentActionId)
    {
        var reserved = _lastReservedNativeChoice;
        _lastReservedNativeChoice = null;
        return reserved is { } value
               && value.Generation == _runGeneration
               && _combatId is { } combatId
               && value.CombatId == combatId
               && value.ParentActionId == parentActionId
            ? value.ChoiceId
            : null;
    }

    internal static void NoteUncapturedCombatCardSelector() =>
        SupersedeUnboundCombatCardTickets(
            RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id);

    private static void SupersedeUnboundCombatCardTickets(uint? parentActionId)
    {
        if (_combatId is not { } combatId)
        {
            return;
        }

        // If a later selector opens under the same native action, an old
        // ticket without an ID can no longer claim a late card receipt by
        // parent and card contents alone. With no current parent ID, retire
        // all unbound tickets in this combat. This also covers a later
        // selector whose candidates could not be frozen.
        foreach (var ticket in NativeCombatChoiceTickets.Where(item =>
                     item.RuntimeGeneration == _runGeneration
                     && item.CombatId == combatId
                     && (parentActionId is null
                         || item.ParentActionId == parentActionId)
                     && item.ExpectsNativeCombatCardResult
                     && item.NativeChoiceId is null))
        {
            ticket.UnboundReceiptSuperseded = true;
        }
    }

    internal static PendingCombatCardChoice? PrepareCombatCardChoice(
        object selector,
        IReadOnlyList<CardModel> options,
        int minSelections,
        int maxSelections,
        bool canCancel,
        bool expectsNativeCombatCardResult,
        string description,
        bool requiresManualConfirmation = true,
        bool requiresNativeReceipt = true)
    {
        if (_stopping || _episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress
            || !CombatManager.Instance.IsInProgress)
        {
            return null;
        }

        // A native UI shown by the MCTS callback is the same choice. Its task
        // is supporting evidence; the callback return is the actual receipt.
        if (MctsFallbackChoices.TryGetValue(selector, out var fallback)) return fallback;

        DrainCompletedSelectors();
        if (PendingCombatChoices.ContainsKey(selector))
        {
            RecordCoverageGap(
                "combat_choice_selector_reentered",
                new { description },
                invalidatePendingDecision: false);
            return null;
        }

        var parentActionId = RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id;
        SupersedeUnboundCombatCardTickets(parentActionId);
        // Generated choice cards may not have a CombatCard database ID. They
        // can still carry a native Index result, so retain any reservation for
        // either result kind.
        var lastReservedNativeChoice = _lastReservedNativeChoice;
        var nativeChoiceId = requiresNativeReceipt ? TakeReservedNativeChoiceId(parentActionId) : null;
        if (expectsNativeCombatCardResult && nativeChoiceId is null)
        {
            RecordDiagnostic("native_combat_choice_id_unbound_at_open", new
            {
                description,
                parent_action_id = parentActionId,
                last_reserved_choice_id = lastReservedNativeChoice?.ChoiceId,
                last_reserved_parent_action_id = lastReservedNativeChoice?.ParentActionId,
                last_reserved_combat_id = lastReservedNativeChoice?.CombatId,
            });
        }
        CapturedCombatDecision? captured = null;
        if (options.Count == 0)
        {
            if (selector is NPlayerHand)
            {
                // CardSelectCmd normally returns before opening the hand UI
                // when there are no eligible cards. Once this UI is open,
                // even MinSelect=0 waits for a human confirmation. An empty
                // frozen candidate set here means the interface and capture
                // disagree, so it cannot be silently called automatic.
                RecordCoverageGap(
                    "combat_hand_choice_empty_interface_mismatch",
                    new { description, minSelections, maxSelections },
                    invalidatePendingDecision: false);
            }
            else
            {
                RecordDiagnostic("automatic_empty_combat_choice", new { description });
            }
        }
        else if (minSelections < 0 || maxSelections < minSelections
                 || maxSelections < 1)
        {
            RecordCoverageGap(
                "combat_choice_selection_bounds_invalid",
                new { description, minSelections, maxSelections, option_count = options.Count },
                invalidatePendingDecision: false);
        }
        else
        {
            try
            {
                // A selector without a confirmation button only completes
                // when the native maximum has been reached. A selector with
                // confirmation may submit any count in its native interval.
                var effectiveMinSelections = requiresManualConfirmation
                    ? minSelections
                    : maxSelections;
                var state = CombatManager.Instance.DebugOnlyGetState()
                    ?? throw new InvalidOperationException("Combat state unavailable at choice open.");
                captured = CollectorCombatProjector.CaptureCardChoice(
                    state,
                    options,
                    effectiveMinSelections,
                    maxSelections,
                    canCancel,
                    description,
                    _episodes.NextSourceDecisionIndex(),
                    nativeChoiceId,
                    requiresNativeCombatCardIds: expectsNativeCombatCardResult);
                captured = CollectorCombatProjector.WithPendingManualActions(
                    captured,
                    PendingManualActionsAtClick());
                if (captured.Decision.Observation.ActiveChoice?.MaxSelections > 1)
                {
                    RecordDiagnostic("combat_multi_card_interface_frozen", new
                    {
                        description,
                        min_selections = minSelections,
                        max_selections = maxSelections,
                        effective_min_selections = effectiveMinSelections,
                        effective_max_selections = captured.Decision.Observation.ActiveChoice.MaxSelections,
                        requires_manual_confirmation = requiresManualConfirmation,
                        can_cancel = canCancel,
                        option_count = options.Count,
                    });
                }
            }
            catch (Exception exception)
            {
                RecordCoverageGap(
                    "combat_choice_capture_failed",
                    new { description, error = exception.ToString() },
                    invalidatePendingDecision: false);
            }
        }

        var pending = new PendingCombatCardChoice(
            selector,
            options.ToArray(),
            captured,
            canCancel,
            requiresManualConfirmation,
            expectsNativeCombatCardResult,
            description,
            _runGeneration,
            _combatId)
        {
            NativeChoiceId = nativeChoiceId,
            ParentActionId = parentActionId,
        };
        PendingCombatChoices.Add(selector, pending);
        // Index receipts can arrive after a selector was frozen without a
        // reserved native choice ID. Keep that selector available for a
        // later reservation or a uniquely matched manual Index receipt.
        if (requiresNativeReceipt
            && (captured is not null || expectsNativeCombatCardResult || nativeChoiceId.HasValue))
        {
            NativeCombatChoiceTickets.Add(pending);
        }

        return pending;
    }

    internal static void ObserveHandChoiceConfirmation(
        object selector,
        IReadOnlyList<CardModel>? selectedCards)
    {
        if (TryGetCombatChoice(selector, out var pending)
            && pending.RuntimeGeneration == _runGeneration)
        {
            // The native confirm handler submits this exact list to its Task.
            // Keep object identities so duplicate model IDs remain distinct.
            pending.HandConfirmationObserved = true;
            pending.HandConfirmedCards = selectedCards?.ToArray();
        }

        MarkCombatChoiceManualInput(selector);
    }

    internal static void MarkCombatChoiceManualInput(object selector)
    {
        if (!TryGetCombatChoice(selector, out var pending)
            || pending.RuntimeGeneration != _runGeneration
            || pending.Prepared is not null
            || pending.Captured is null)
        {
            return;
        }

        try
        {
            // The selector is now on screen. Freeze only card presentation
            // backed by its visible nodes before the native click mutates it.
            try
            {
                pending.Captured = CollectorCombatProjector.WithChoiceDisplays(
                    pending.Captured,
                    pending.ManualFallbackSelector ?? pending.Selector,
                    pending.Options);
            }
            catch (Exception exception) when (exception is not OutOfMemoryException)
            {
                // Display is optional. A transient UI failure must not turn
                // an otherwise verified human choice into a coverage gap.
                RecordDiagnostic("combat_choice_display_unavailable", new
                {
                    pending.Description,
                    error = exception.GetType().Name,
                });
            }
            if (!SettleCombatParentAtChoiceBoundary(pending))
            {
                return;
            }

            pending.Prepared = _episodes!.PrepareCombatChoice(
                pending.Captured,
                pending.Description);
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "combat_choice_prepare_failed",
                new { pending.Description, error = exception.ToString() },
                invalidatePendingDecision: false);
        }
    }

    private static bool SettleCombatParentAtChoiceBoundary(PendingCombatCardChoice pending)
    {
        if (_episodes is null)
        {
            return false;
        }

        var matchingParents = pending.ParentActionId is { } parentActionId
            ? PendingCombatActions
                .Where(entry => entry.Key.Id == parentActionId)
                .ToArray()
            : [];
        if (matchingParents.Length > 1
            || pending.ParentActionId is null && PendingCombatActions.Count > 0)
        {
            RecordCoverageGap(
                "combat_choice_parent_ambiguous",
                new
                {
                    pending.Description,
                    pending.ParentActionId,
                    parent_count = PendingCombatActions.Count,
                },
                invalidatePendingDecision: false);
            return false;
        }

        if (matchingParents.Length == 1)
        {
            var parent = matchingParents[0];
            if (!EarlySettledCombatActions.Contains(parent.Key))
            {
                if (_episodes.Snapshot.PendingDecisions?.Any(decision =>
                        decision.DecisionId == parent.Value.Receipt.DecisionId
                        && decision.Phase == EpisodePhase.AwaitingExecution) != true)
                {
                    RecordCoverageGap(
                        "combat_choice_parent_not_current",
                        new { pending.Description, parent_action_id = parent.Key.Id },
                        invalidatePendingDecision: false);
                    return false;
                }

                // Opening an actionable child selector proves the parent's
                // play-card submission was accepted. The rest of the native
                // effect can still fail later; that failure is linked back to
                // this attempt by a detached gap.
                _episodes.Commit(
                    parent.Value,
                    CollectorExecutionStatus.ObservedTransition,
                    $"accepted before combat choice {pending.Description}");
                _episodes.ResolveAtCurrentBoundary();
                EarlySettledCombatActions.Add(parent.Key);
            }
        }

        _episodes.ResolveAtCurrentBoundary();
        // Other manual inputs may already be queued. The child selector is
        // still a separate decision and the coordinator will append it after
        // those submitted combat decisions.
        return _episodes.HasActiveEpisode;
    }

    private static bool TryGetCombatChoice(object selector, out PendingCombatCardChoice pending) =>
        PendingCombatChoices.TryGetValue(selector, out pending!)
        || MctsFallbackChoices.TryGetValue(selector, out pending!);

    internal static void ObserveMctsCardChoiceRequested(
        object request, CardModel[] cards, int minSelect, int maxSelect)
    {
        var pending = PrepareCombatCardChoice(
            request, cards, minSelect, maxSelect, canCancel: false,
            expectsNativeCombatCardResult: false, "card_selector",
            requiresManualConfirmation: true, requiresNativeReceipt: false);
        if (pending is null) return;
        pending.IsMctsRequest = true;
        pending.PolicyOverride = new PolicyTrace(ActionActor.Policy, "native-mcts", CollectorPolicyTelemetry.AdapterRevision,
            TeacherInformation: "native_checkpoint_privileged");
        RecordDiagnostic("mcts_card_choice_requested", new
        {
            min_select = minSelect, max_select = maxSelect, option_count = cards.Length,
            receipt_kind = "selector_callback_return",
        });
    }

    internal static void ObserveMctsCardChoiceManualFallback(object request, object selector)
    {
        if (!PendingCombatChoices.TryGetValue(request, out var pending)
            || !pending.IsMctsRequest || pending.RuntimeGeneration != _runGeneration) return;
        if (pending.ManualFallbackSelector is not null || MctsFallbackChoices.ContainsKey(selector))
        {
            RecordCombatChoiceFailure(pending, "mcts_card_choice_fallback_reentered",
                new { pending.Description });
            return;
        }
        pending.ManualFallbackSelector = selector;
        pending.PolicyOverride = new PolicyTrace(ActionActor.Human, "human-demonstration", null,
            TeacherInformation: "public_observation");
        MctsFallbackChoices.Add(selector, pending);
        RecordDiagnostic("mcts_card_choice_manual_fallback", new { pending.Description });
    }

    internal static void ObserveMctsCardChoiceCompleted(
        object request, CardModel[]? cards, Exception? exception)
    {
        if (!PendingCombatChoices.TryGetValue(request, out var pending)
            || !pending.IsMctsRequest || pending.RuntimeGeneration != _runGeneration) return;
        if (exception is null && cards is null)
            exception = new InvalidDataException("MCTS callback returned neither cards nor a failure.");
        if (exception is null && pending.ManualFallbackSelector is not null)
        {
            // A UI task may finish just before its awaiting MCTS continuation.
            // Require both real return values, not a fabricated network receipt.
            if (pending.ManualFallbackTask is not { Status: TaskStatus.RanToCompletion } task
                || !TryMapSelectedCombatOptions(pending.Options, task.Result.ToArray(), out var uiIndexes)
                || !TryMapSelectedCombatOptions(pending.Options, cards!, out var callbackIndexes)
                || !uiIndexes.SequenceEqual(callbackIndexes))
                exception = new InvalidDataException("MCTS fallback UI and callback results do not match.");
        }
        if (exception is null && pending.ManualFallbackSelector is null && pending.Captured is not null)
        {
            // This is an actual policy callback, not synthetic manual input.
            if (SettleCombatParentAtChoiceBoundary(pending))
                pending.Prepared = _episodes!.PrepareCombatChoice(pending.Captured, pending.Description);
        }
        RecordDiagnostic("mcts_card_choice_returned", new
        {
            pending.Description,
            selected_count = cards?.Length,
            manual_fallback = pending.ManualFallbackSelector is not null,
            succeeded = exception is null,
        });
        CompleteCombatChoice(pending, cards, exception);
    }

    internal static void AttachCombatChoiceTask(
        PendingCombatCardChoice? pending,
        Task<IEnumerable<CardModel>> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingCombatChoices.TryGetValue(pending.Selector, out var current)
            || !ReferenceEquals(current, pending))
        {
            return;
        }

        if (pending.IsMctsRequest)
        {
            pending.ManualFallbackTask = task;
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    private static void DrainCompletedCombatChoices()
    {
        foreach (var pending in PendingCombatChoices.Values
                     .Where(item => item.CompletionTask?.IsCompleted == true)
                     .ToArray())
        {
            var task = pending.CompletionTask!;
            CompleteCombatChoice(
                pending,
                task.Status == TaskStatus.RanToCompletion ? task.Result.ToArray() : null,
                SelectorTaskException(task));
        }
    }

    internal static void CompleteCombatChoice(
        PendingCombatCardChoice? pending,
        IReadOnlyList<CardModel>? selected,
        Exception? exception = null)
    {
        if (pending is null || pending.RuntimeGeneration != _runGeneration
            || !PendingCombatChoices.TryGetValue(pending.Selector, out var current)
            || !ReferenceEquals(current, pending))
        {
            return;
        }

        try
        {
            if (pending.Captured is null)
            {
                return; // The unsupported or automatic path was already audited.
            }

            if (exception is not null)
            {
                RecordCombatChoiceFailure(
                    pending,
                    "combat_choice_task_failed",
                    new { pending.Description, error = exception.ToString() });
                return;
            }

            if (pending.Prepared is null)
            {
                RecordCoverageGap(
                    "combat_choice_without_manual_input_evidence",
                    new { pending.Description, selected_count = selected?.Count },
                    invalidatePendingDecision: false);
                return;
            }

            var chosen = selected ?? [];
            var choice = pending.Captured.Decision.Observation.ActiveChoice
                ?? throw new InvalidDataException("Combat choice observation is missing candidates.");
            if (chosen.Count > choice.MaxSelections
                || chosen.Count != 0 && chosen.Count < choice.MinSelections
                || chosen.Count == 0 && choice.MinSelections > 0 && !pending.CanCancel)
            {
                RecordCombatChoiceFailure(
                    pending,
                    "combat_choice_result_cardinality_invalid",
                    new { pending.Description, selected_count = chosen.Count });
                return;
            }

            if (!TryMapSelectedCombatOptions(pending.Options, chosen,
                    out var selectedOptionIndexes))
            {
                RecordCombatChoiceFailure(
                    pending,
                    "combat_choice_result_reference_unmatched",
                    new { pending.Description, selected_count = chosen.Count });
                return;
            }

            // For native hand selectors the confirmation button submits the
            // current selected CardModel objects to this same Task. Compare
            // the interface state at confirmation with the completed result.
            if (choice.MaxSelections > 1 && pending.Selector is NPlayerHand
                || pending.ManualFallbackSelector is not null)
            {
                // Native SelectCardInSimpleMode only updates the selected list
                // and confirmation button. Reaching MaxSelect does not prove
                // that the player confirmed the choice, even when every
                // offered card was selected.
                var confirmationRequired = pending.RequiresManualConfirmation;
                var confirmationMismatch = false;
                if (pending.HandConfirmationObserved)
                {
                    confirmationMismatch = pending.HandConfirmedCards is null
                        || !TryMapSelectedCombatOptions(
                            pending.Options,
                            pending.HandConfirmedCards,
                            out var confirmedOptionIndexes)
                        || !confirmedOptionIndexes.SequenceEqual(selectedOptionIndexes);
                }

                if (confirmationRequired && !pending.HandConfirmationObserved
                    || confirmationMismatch)
                {
                    RecordCombatChoiceFailure(
                        pending,
                        "combat_choice_hand_confirmation_mismatch",
                        new
                        {
                            pending.Description,
                            pending.HandConfirmationObserved,
                            confirmed_count = pending.HandConfirmedCards?.Count,
                            task_option_indexes = selectedOptionIndexes,
                        });
                    return;
                }
            }

            pending.TaskSelectedOptionIndexes = selectedOptionIndexes;
            var choiceCards = choice.Cards;
            var selectedIds = selectedOptionIndexes
                .Select(index => choiceCards[index].CombatCardIndex)
                .Where(id => id.HasValue)
                .Select(id => id!.Value)
                .Order()
                .ToArray();
            if (choice.MaxSelections > 1 && selectedIds.Length != selectedOptionIndexes.Length)
            {
                RecordCombatChoiceFailure(
                    pending,
                    "combat_choice_selected_card_index_missing",
                    new { pending.Description, selected_option_indexes = selectedOptionIndexes });
                return;
            }
            pending.TaskSelectedCardIds = selectedIds;
            var actions = pending.Captured.Decision.LegalActions;
            var ordinal = -1;
            JsonElement? selectedAction = null;
            if (choice.MaxSelections > 1)
            {
                if (selectedIds.Length == 0 && choice.MinSelections > 0)
                {
                    ordinal = actions.ToList().FindIndex(action =>
                        !action.IsSelectionTemplate
                        && action.SelectedCombatCardIds is { Count: 0 });
                }
                else if (actions.SingleOrDefault(action => action.IsSelectionTemplate)
                         is { } template)
                {
                    ordinal = 0;
                    var concrete = template with
                    {
                        SelectedCombatCardIds = selectedIds,
                        IsSelectionTemplate = false,
                    };
                    CombatDecisionPoint.ValidateSubmittedSetAction(
                        pending.Captured.Decision.Observation,
                        template,
                        concrete);
                    selectedAction = JsonSerializer.SerializeToElement(
                        concrete, CollectorJson.Options);
                }
            }
            else
            {
                for (var index = 0; index < actions.Count; index++)
                {
                    var action = actions[index];
                    if (selectedOptionIndexes.Length == 1
                            ? action.OptionIndex == selectedOptionIndexes[0]
                            : action.OptionIndex is null
                              && action.SelectedCombatCardIds is { Count: 0 })
                    {
                        ordinal = index;
                        break;
                    }
                }
            }

            if (ordinal < 0)
            {
                RecordCombatChoiceFailure(
                    pending,
                    "combat_choice_result_not_offered",
                    new { pending.Description, selected_option_indexes = selectedOptionIndexes });
                return;
            }

            var draft = _episodes?.ResolveCombatChoice(
                pending.Prepared, ordinal, selectedAction, pending.PolicyOverride);
            if (draft is not null)
            {
                pending.SubmittedAttemptId = draft.AttemptId;
                _episodes!.Commit(draft, CollectorExecutionStatus.ObservedTransition);
            }

            CheckNativeChoiceResult(pending);
        }
        catch (Exception completionError)
        {
            RecordCombatChoiceFailure(
                pending,
                "combat_choice_completion_failed",
                new { pending.Description, error = completionError.ToString() });
        }
        finally
        {
            pending.Completed = true;
            PendingCombatChoices.Remove(pending.Selector);
            if (pending.ManualFallbackSelector is { } fallbackSelector)
                MctsFallbackChoices.Remove(fallbackSelector);
            FinishPendingRun();
        }
    }

    private static bool TryMapSelectedCombatOptions(
        IReadOnlyList<CardModel> options,
        IReadOnlyList<CardModel> selected,
        out int[] indexes)
    {
        var mapped = new List<int>(selected.Count);
        foreach (var card in selected)
        {
            var matches = options
                .Select((option, index) => (option, index))
                .Where(item => ReferenceEquals(item.option, card))
                .Select(item => item.index)
                .ToArray();
            if (matches.Length != 1 || mapped.Contains(matches[0]))
            {
                indexes = [];
                return false;
            }

            mapped.Add(matches[0]);
        }

        indexes = mapped.Order().ToArray();
        return true;
    }

    private static void RecordCombatChoiceFailure(
        PendingCombatCardChoice pending,
        string reason,
        object data)
    {
        var decisionId = pending.Prepared?.Receipt.DecisionId;
        var isStillPending = decisionId is { } id
                             && _episodes?.HasActiveEpisode == true
                             && _episodes.Snapshot.PendingDecisions?.Any(item =>
                                 item.DecisionId == id) == true;
        RecordCoverageGap(
            reason,
            data,
            invalidatePendingDecision: isStillPending,
            relatedDecisionId: decisionId,
            relatedAttemptId: pending.SubmittedAttemptId,
            targetDecisionId: isStillPending ? decisionId : null);
    }

    internal static bool ObserveNativeCombatCardChoice(
        uint choiceId,
        IReadOnlyList<uint> selectedCardIds,
        uint? parentActionId)
    {
        if (_combatId is not { } combatId)
        {
            return false;
        }

        var exact = NativeCombatChoiceTickets
            .Where(item => item.RuntimeGeneration == _runGeneration
                           && item.CombatId == combatId
                           && item.ExpectsNativeCombatCardResult
                           && item.NativeChoiceId == choiceId
                           && item.ParentActionId == parentActionId)
            .ToArray();
        PendingCombatCardChoice? pending = exact.Length == 1 ? exact[0] : null;
        var matchedByFrozenSelector = false;
        if (pending is null && exact.Length == 0 && parentActionId is not null
            && !NativeCombatChoiceTickets.Any(item =>
                item.RuntimeGeneration == _runGeneration
                && item.CombatId == combatId
                && item.NativeChoiceId == choiceId))
        {
            // FromHand may reserve its native choice ID before an await and
            // open the selector under a different action context. Its UI Task
            // then completes before the CombatCard receipt is emitted. Keep
            // completed tickets and bind only one manually observed choice
            // under the exact native parent action, after comparing card
            // instance IDs with the completed Task result.
            var unbound = NativeCombatChoiceTickets
                .Where(item => item.RuntimeGeneration == _runGeneration
                               && item.CombatId == combatId
                               && item.ExpectsNativeCombatCardResult
                               && item.NativeChoiceId is null
                               && item.ParentActionId == parentActionId
                               && !item.NativeResultObserved)
                .ToArray();
            if (unbound.Length == 1
                && !unbound[0].UnboundReceiptSuperseded
                && unbound[0].Captured is not null
                && unbound[0].Prepared is not null
                && TaskSelectionMatchesNativeCombatCards(unbound[0], selectedCardIds))
            {
                pending = unbound[0];
                pending.NativeChoiceId = choiceId;
                matchedByFrozenSelector = true;
            }
        }

        if (pending is null)
        {
            return false;
        }

        NativeCombatChoiceTickets.Remove(pending);
        pending.NativeSelectedCardIds = selectedCardIds.ToArray();
        pending.NativeResultObserved = true;
        RecordDiagnostic(
            "native_combat_choice_correlated",
            new
            {
                choice_id = choiceId,
                pending.Description,
                selected_card_ids = selectedCardIds,
                matched_by_frozen_selector = matchedByFrozenSelector,
            });
        CheckNativeChoiceResult(pending);
        return true;
    }

    private static bool TaskSelectionMatchesNativeCombatCards(
        PendingCombatCardChoice pending,
        IReadOnlyList<uint> nativeSelectedCardIds)
    {
        if (pending.CompletionTask is not { Status: TaskStatus.RanToCompletion } task
            || pending.Captured?.Decision.Observation.ActiveChoice is not { } choice)
        {
            return false;
        }

        try
        {
            var result = task.Result?.ToArray();
            if (result is null
                || !TryMapSelectedCombatOptions(
                    pending.Options, result, out var selectedOptionIndexes)
                || selectedOptionIndexes.Length > choice.MaxSelections
                || selectedOptionIndexes.Length > 0
                    && selectedOptionIndexes.Length < choice.MinSelections
                || selectedOptionIndexes.Length == 0
                    && choice.MinSelections > 0 && !pending.CanCancel
                || pending.TaskSelectedOptionIndexes is not null
                    && !pending.TaskSelectedOptionIndexes.SequenceEqual(selectedOptionIndexes))
            {
                return false;
            }

            var taskSelectedCardIds = selectedOptionIndexes
                .Select(index => choice.Cards[index].CombatCardIndex)
                .ToArray();
            return taskSelectedCardIds.All(id => id.HasValue)
                   && taskSelectedCardIds.Select(id => id!.Value).Order()
                       .SequenceEqual(nativeSelectedCardIds.Order())
                   && (pending.TaskSelectedCardIds is null
                       || pending.TaskSelectedCardIds.Order()
                           .SequenceEqual(nativeSelectedCardIds.Order()));
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            RecordDiagnostic("native_combat_choice_task_compare_failed", new
            {
                pending.Description,
                error = exception.GetType().Name,
            });
            return false;
        }
    }

    internal static bool ObserveNativeCombatIndexChoice(
        uint choiceId,
        IReadOnlyList<int> selectedOptionIndexes,
        uint? parentActionId)
    {
        var exact = NativeCombatChoiceTickets
            .Where(item => item.RuntimeGeneration == _runGeneration
                           && !item.ExpectsNativeCombatCardResult
                           && item.NativeChoiceId == choiceId
                           && item.ParentActionId == parentActionId)
            .ToArray();
        PendingCombatCardChoice? pending = exact.Length == 1 ? exact[0] : null;
        var matchedByFrozenSelector = false;
        if (pending is null && exact.Length == 0)
        {
            // Generated-card choices may deliver their reservation after the
            // selector opens, or without a reservation visible to this hook.
            // A unique frozen selector with manual input evidence under the
            // same native action and a legal option index can bind this
            // receipt. The selector Task is compared with the index below.
            var unbound = NativeCombatChoiceTickets
                .Where(item => item.RuntimeGeneration == _runGeneration
                               && !item.ExpectsNativeCombatCardResult
                               && item.NativeChoiceId is null
                               && item.ParentActionId == parentActionId
                               && !item.Completed
                               && item.CompletionTask?.IsCompleted != true
                               && PendingCombatChoices.TryGetValue(item.Selector, out var active)
                               && ReferenceEquals(active, item)
                               && item.Prepared is not null
                               && item.Captured?.Decision.Observation.ActiveChoice is { } choice
                               && selectedOptionIndexes.Count >= choice.MinSelections
                               && selectedOptionIndexes.Count <= choice.MaxSelections
                               && selectedOptionIndexes.Distinct().Count() == selectedOptionIndexes.Count
                               && selectedOptionIndexes.All(index =>
                                   index >= 0 && index < choice.Cards.Count))
                .ToArray();
            if (unbound.Length == 1)
            {
                pending = unbound[0];
                pending.NativeChoiceId = choiceId;
                matchedByFrozenSelector = true;
            }
        }

        if (pending is null)
        {
            return false;
        }

        NativeCombatChoiceTickets.Remove(pending);
        pending.NativeSelectedOptionIndexes = selectedOptionIndexes.ToArray();
        pending.NativeResultObserved = true;
        RecordDiagnostic(
            "native_combat_index_choice_correlated",
            new
            {
                choice_id = choiceId,
                pending.Description,
                selected_option_indexes = selectedOptionIndexes,
                matched_by_frozen_selector = matchedByFrozenSelector,
            });
        CheckNativeChoiceResult(pending);
        return true;
    }

    private static void CloseNativeChoiceTicketsForAction(GameAction action)
    {
        foreach (var pending in NativeCombatChoiceTickets
                     .Where(item => item.ParentActionId == action.Id)
                     .ToArray())
        {
            CloseNativeChoiceTicket(pending, "parent_action_finished");
        }
    }

    private static void CloseNativeChoiceTicketsAtCombatEnd()
    {
        foreach (var pending in PendingCombatChoices.Values.Where(item => item.IsMctsRequest).ToArray())
        {
            CompleteCombatChoice(pending, null,
                new OperationCanceledException("Combat ended before the MCTS selector returned."));
        }
        foreach (var pending in NativeCombatChoiceTickets.ToArray())
        {
            CloseNativeChoiceTicket(pending, "combat_ended");
        }
    }

    private static void CloseNativeChoiceTicket(
        PendingCombatCardChoice pending,
        string boundary)
    {
        NativeCombatChoiceTickets.Remove(pending);
        if (pending.Captured is null || pending.Prepared is null)
        {
            // Empty, automatic, and already-gapped choices carry no human BC
            // label. CompleteCombatChoice separately audits missing manual
            // evidence. A manual choice without a native receipt is a gap even
            // when its native choice ID could not be frozen at selector open.
            return;
        }

        RecordCoverageGap(
            "combat_choice_native_result_missing",
            new
            {
                pending.Description,
                pending.NativeChoiceId,
                pending.ParentActionId,
                boundary,
            },
            invalidatePendingDecision: false,
            relatedDecisionId: pending.Prepared?.Receipt.DecisionId,
            relatedAttemptId: pending.SubmittedAttemptId);
    }

    private static void CheckNativeChoiceResult(PendingCombatCardChoice pending)
    {
        if (!pending.NativeResultObserved || pending.TaskSelectedOptionIndexes is null
            || pending.NativeResultCompared)
        {
            return;
        }

        pending.NativeResultCompared = true;

        if (pending.ExpectsNativeCombatCardResult)
        {
            if (pending.NativeSelectedCardIds is null
                || pending.TaskSelectedCardIds is null
                || !pending.TaskSelectedCardIds.Order().SequenceEqual(
                    pending.NativeSelectedCardIds.Order()))
            {
                RecordCoverageGap(
                    "combat_choice_native_result_mismatch",
                    new
                    {
                        pending.Description,
                        task_card_ids = pending.TaskSelectedCardIds,
                        native_card_ids = pending.NativeSelectedCardIds,
                    },
                    invalidatePendingDecision: false,
                    relatedDecisionId: pending.Prepared?.Receipt.DecisionId,
                    relatedAttemptId: pending.SubmittedAttemptId);
            }
        }
        else if (pending.NativeSelectedOptionIndexes is null
                 || !pending.TaskSelectedOptionIndexes.Order().SequenceEqual(
                     pending.NativeSelectedOptionIndexes.Order()))
        {
            RecordCoverageGap(
                "combat_choice_native_index_mismatch",
                new
                {
                    pending.Description,
                    task_option_indexes = pending.TaskSelectedOptionIndexes,
                    native_option_indexes = pending.NativeSelectedOptionIndexes,
                },
                invalidatePendingDecision: false,
                relatedDecisionId: pending.Prepared?.Receipt.DecisionId,
                relatedAttemptId: pending.SubmittedAttemptId);
        }
    }

    private static bool CompleteEarlySettledCombatAction(
        GameAction action,
        CollectorActionDraft draft)
    {
        if (!EarlySettledCombatActions.Remove(action))
        {
            return false;
        }

        if (action.Exception is not null)
        {
            var detail = action.Exception.ToString();
            if (_episodes?.FailStagedExecution(draft, detail) != true)
            {
                RecordCoverageGap(
                    "combat_parent_failed_after_nested_choice",
                    new { action = action.ToString(), error = detail },
                    invalidatePendingDecision: false,
                    relatedDecisionId: draft.Receipt.DecisionId,
                    relatedAttemptId: draft.AttemptId);
            }
        }

        FinishPendingRun();
        return true;
    }

    private static void ClearCombatChoiceState()
    {
        PendingCombatChoices.Clear();
        MctsFallbackChoices.Clear();
        NativeCombatChoiceTickets.Clear();
        EarlySettledCombatActions.Clear();
        _lastReservedNativeChoice = null;
    }
}
