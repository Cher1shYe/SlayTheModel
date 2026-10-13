using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Collector;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed class PendingBundleSelection(
    NChooseABundleSelectionScreen screen,
    string description,
    uint? nativeChoiceId,
    long runtimeGeneration)
{
    internal NChooseABundleSelectionScreen Screen { get; } = screen;
    internal string Description { get; } = description;
    internal uint? NativeChoiceId { get; } = nativeChoiceId;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal Task<IEnumerable<IReadOnlyList<CardModel>>>? CompletionTask { get; set; }
    internal PreparedOutsideDecision? Prepared { get; set; }
    internal IReadOnlyList<CardModel>[]? NativeBundles { get; set; }
    internal CardModel[][]? FrozenCards { get; set; }
    internal NCardBundle[]? VisibleBundles { get; set; }
    internal int? ClickedOrdinal { get; set; }
    internal int? ConfirmedOrdinal { get; set; }
    internal int? NativeOrdinal { get; set; }
    internal bool NativeResultObserved { get; set; }
    internal bool NativeReceiptGraceUsed { get; set; }
    internal bool Faulted { get; set; }
    internal bool GapRecorded { get; set; }
}

internal static partial class CollectorRuntime
{
    private static readonly Dictionary<NChooseABundleSelectionScreen, PendingBundleSelection>
        PendingBundleSelections = new(ReferenceEqualityComparer.Instance);

    private static (uint ChoiceId, uint? ParentActionId, long Generation)?
        _lastReservedBundleChoice;

    internal static void NoteReservedBundleChoiceId(Player player, uint choiceId)
    {
        if (_stopping || _episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress
            || CombatManager.Instance.IsInProgress
            || !IsLocalSinglePlayer(player))
        {
            return;
        }

        _lastReservedBundleChoice = (
            choiceId,
            RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id,
            _runGeneration);
    }

    internal static PendingBundleSelection? BeginBundleSelection(
        NChooseABundleSelectionScreen screen)
    {
        if (_stopping || _episodes?.HasActiveEpisode != true
            || !RunManager.Instance.IsInProgress)
        {
            return null;
        }

        var description = $"card_bundle:{screen.GetType().FullName}";
        try
        {
            DrainCompletedSelectors();
            if (PendingBundleSelections.ContainsKey(screen))
            {
                RecordCoverageGap(
                    "card_bundle_selector_reentered",
                    new { description },
                    invalidatePendingDecision: false);
                return null;
            }

            // The parent event/reward action has already opened the selector.
            // Settle its reward before the player's next decision is recorded.
            CompleteAcceptedParentActions(description, nestedSelectorObserved: true);
            _episodes.ResolveAtCurrentBoundary();

            var reserved = _lastReservedBundleChoice;
            _lastReservedBundleChoice = null;
            var parentActionId = RunManager.Instance.ActionExecutor
                .CurrentlyRunningAction?.Id;
            uint? choiceId = reserved is { } value
                             && value.Generation == _runGeneration
                             && value.ParentActionId == parentActionId
                ? value.ChoiceId
                : null;
            var pending = new PendingBundleSelection(
                screen,
                description,
                choiceId,
                _runGeneration);
            PendingBundleSelections.Add(screen, pending);
            PendingOutsideOperations.Add(pending);
            if (choiceId is null)
            {
                FailBundleSelection(
                    pending,
                    "card_bundle_native_choice_id_unavailable",
                    new { description });
            }

            if (CombatManager.Instance.IsInProgress)
            {
                FailBundleSelection(
                    pending,
                    "combat_card_bundle_selection_not_supported",
                    new { description });
            }

            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "card_bundle_selection_begin_failed",
                new { description, error = exception.ToString() },
                invalidatePendingDecision: false);
            return null;
        }
    }

    internal static void ObserveBundleClicked(
        NChooseABundleSelectionScreen screen,
        NCardBundle clicked,
        IReadOnlyList<IReadOnlyList<CardModel>>? nativeBundles,
        Control? bundleRow)
    {
        if (!TryGetBundleSelection(screen, out var pending) || pending.Faulted)
        {
            return;
        }

        try
        {
            if (!TryFreezeVisibleBundles(
                    screen, clicked, nativeBundles, bundleRow,
                    out var native, out var cards, out var nodes,
                    out var clickedOrdinal, out var reason))
            {
                FailBundleSelection(
                    pending,
                    "card_bundle_visible_options_unavailable",
                    new { pending.Description, reason });
                return;
            }

            if (pending.Prepared is null)
            {
                if (RunManager.Instance.DebugOnlyGetState() is not { } state
                    || state.Players.Count != 1)
                {
                    FailBundleSelection(
                        pending,
                        "card_bundle_run_state_unavailable",
                        new { pending.Description });
                    return;
                }

                var decision = CollectorOutsideProjector.ForCardBundleChoice(
                    state,
                    cards,
                    pending.Description,
                    _episodes!.NextSourceDecisionIndex());
                var audit = JsonSerializer.SerializeToElement(new
                {
                    during_combat = false,
                    parent_action_id = RunManager.Instance.ActionExecutor
                        .CurrentlyRunningAction?.Id,
                    native_choice_id = pending.NativeChoiceId,
                });
                pending.Prepared = _episodes.PrepareOutside(
                    decision,
                    pending.Description,
                    audit);
                pending.NativeBundles = native;
                pending.FrozenCards = cards;
                pending.VisibleBundles = nodes;
            }
            else if (!SameFrozenBundles(pending, native, cards, nodes))
            {
                FailBundleSelection(
                    pending,
                    "card_bundle_options_changed_after_freeze",
                    new { pending.Description });
                return;
            }

            pending.ClickedOrdinal = clickedOrdinal;
            pending.ConfirmedOrdinal = null;
        }
        catch (Exception exception)
        {
            FailBundleSelection(
                pending,
                "card_bundle_click_capture_failed",
                new { pending.Description, error = exception.ToString() });
        }
    }

    internal static void ObserveBundlePreviewBack(
        NChooseABundleSelectionScreen screen)
    {
        if (TryGetBundleSelection(screen, out var pending))
        {
            pending.ClickedOrdinal = null;
            pending.ConfirmedOrdinal = null;
        }
    }

    internal static void ObserveBundleConfirmed(
        NChooseABundleSelectionScreen screen,
        NCardBundle? nativeSelected)
    {
        if (!TryGetBundleSelection(screen, out var pending) || pending.Faulted)
        {
            return;
        }

        var ordinal = pending.ClickedOrdinal;
        if (ordinal is null || nativeSelected is null
            || pending.VisibleBundles is null
            || !ReferenceEquals(pending.VisibleBundles[ordinal.Value], nativeSelected))
        {
            FailBundleSelection(
                pending,
                "card_bundle_confirm_without_matching_click",
                new { pending.Description, clicked_ordinal = ordinal });
            return;
        }

        pending.ConfirmedOrdinal = ordinal;
    }

    internal static void AttachBundleSelectionTask(
        PendingBundleSelection? pending,
        Task<IEnumerable<IReadOnlyList<CardModel>>> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    internal static bool ObserveNativeBundleChoice(
        uint choiceId,
        NetPlayerChoiceResult result)
    {
        if (_stopping || CombatManager.Instance.IsInProgress
            || result.type.ToString() != "Index")
        {
            return false;
        }

        var matches = PendingBundleSelections.Values
            .Where(pending => pending.RuntimeGeneration == _runGeneration
                              && pending.NativeChoiceId == choiceId
                              && PendingOutsideOperations.Contains(pending))
            .ToArray();
        if (matches.Length != 1)
        {
            return false;
        }

        var match = matches[0];
        var indexes = result.indexes?.ToArray() ?? [];
        match.NativeResultObserved = true;
        match.NativeOrdinal = indexes.Length == 1 ? indexes[0] : null;
        if (match.CompletionTask?.IsCompleted == true)
        {
            ScheduleOnMainThread(DrainCompletedSelectors);
        }
        return true;
    }

    internal static void DrainCompletedBundleSelections()
    {
        foreach (var pending in PendingBundleSelections.Values
                     .Where(item => item.CompletionTask?.IsCompleted == true)
                     .ToArray())
        {
            var task = pending.CompletionTask!;
            if (!pending.Faulted && task.Status == TaskStatus.RanToCompletion
                && !pending.NativeResultObserved
                && !pending.NativeReceiptGraceUsed)
            {
                pending.NativeReceiptGraceUsed = true;
                ScheduleOnMainThread(DrainCompletedSelectors);
                continue;
            }

            CompleteBundleSelection(
                pending,
                task.Status == TaskStatus.RanToCompletion
                    ? task.Result.ToArray()
                    : null,
                SelectorTaskException(task));
        }
    }

    internal static void CompleteBundleSelection(
        PendingBundleSelection? pending,
        IReadOnlyList<IReadOnlyList<CardModel>>? selected,
        Exception? exception = null)
    {
        if (pending is null
            || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        try
        {
            if (pending.Faulted)
            {
                return;
            }

            if (exception is not null || pending.Prepared is null
                || pending.FrozenCards is null || pending.NativeBundles is null
                || pending.ConfirmedOrdinal is not { } ordinal
                || pending.ClickedOrdinal != ordinal
                || !pending.NativeResultObserved
                || pending.NativeOrdinal != ordinal
                || selected is not { Count: 1 }
                || ordinal < 0 || ordinal >= pending.NativeBundles.Length
                || !ReferenceEquals(selected[0], pending.NativeBundles[ordinal])
                || !SameCardSequence(selected[0], pending.FrozenCards[ordinal]))
            {
                FailBundleSelection(
                    pending,
                    "card_bundle_result_unverified",
                    new
                    {
                        pending.Description,
                        task_error = exception?.ToString(),
                        pending.ClickedOrdinal,
                        pending.ConfirmedOrdinal,
                        pending.NativeOrdinal,
                        pending.NativeResultObserved,
                        result_count = selected?.Count,
                    });
                return;
            }

            var draft = _episodes?.ResolveOutside(pending.Prepared, ordinal);
            if (draft is not null)
            {
                var capture = new NativeActionCapture(
                    draft,
                    pending.Description,
                    _runGeneration);
                PendingOutsideOperations.Add(capture);
                MarkNativeActionAccepted(capture);
            }
        }
        finally
        {
            PendingBundleSelections.Remove(pending.Screen);
            CompletePendingOutsideOperation(pending);
        }
    }

    private static bool TryGetBundleSelection(
        NChooseABundleSelectionScreen screen,
        out PendingBundleSelection pending)
    {
        if (PendingBundleSelections.TryGetValue(screen, out pending!)
            && pending.RuntimeGeneration == _runGeneration
            && PendingOutsideOperations.Contains(pending))
        {
            return true;
        }

        pending = null!;
        return false;
    }

    private static bool TryFreezeVisibleBundles(
        NChooseABundleSelectionScreen screen,
        NCardBundle clicked,
        IReadOnlyList<IReadOnlyList<CardModel>>? nativeBundles,
        Control? row,
        out IReadOnlyList<CardModel>[] native,
        out CardModel[][] cards,
        out NCardBundle[] nodes,
        out int clickedOrdinal,
        out string reason)
    {
        native = [];
        cards = [];
        nodes = [];
        clickedOrdinal = -1;
        reason = "unavailable";
        if (!GodotObject.IsInstanceValid(screen) || !screen.IsInsideTree()
            || !screen.IsVisibleInTree() || row is null
            || !GodotObject.IsInstanceValid(row) || !row.IsInsideTree()
            || !row.IsVisibleInTree() || nativeBundles is null
            || nativeBundles.Count == 0 || row.GetChildCount() != nativeBundles.Count)
        {
            reason = "screen_or_bundle_row_not_visible";
            return false;
        }

        native = nativeBundles.ToArray();
        cards = new CardModel[native.Length][];
        nodes = new NCardBundle[native.Length];
        for (var index = 0; index < native.Length; index++)
        {
            if (row.GetChild(index) is not NCardBundle node
                || !GodotObject.IsInstanceValid(node)
                || !node.IsInsideTree() || !node.IsVisibleInTree()
                || !GodotObject.IsInstanceValid(node.Hitbox)
                || !node.Hitbox.IsVisibleInTree()
                || !ReferenceEquals(node.Bundle, native[index])
                || native[index].Count == 0
                || node.CardNodes.Count != native[index].Count)
            {
                reason = $"bundle_node_mismatch_at_{index}";
                return false;
            }

            var frozen = new CardModel[native[index].Count];
            for (var cardIndex = 0; cardIndex < frozen.Length; cardIndex++)
            {
                var cardNode = node.CardNodes[cardIndex];
                var card = native[index][cardIndex];
                if (card is null || cardNode is null
                    || !GodotObject.IsInstanceValid(cardNode)
                    || !cardNode.IsVisibleInTree()
                    || !ReferenceEquals(cardNode.Model, card))
                {
                    reason = $"bundle_card_mismatch_at_{index}_{cardIndex}";
                    return false;
                }

                frozen[cardIndex] = card;
            }

            cards[index] = frozen;
            nodes[index] = node;
            if (ReferenceEquals(node, clicked))
            {
                clickedOrdinal = index;
            }
        }

        if (clickedOrdinal < 0)
        {
            reason = "clicked_bundle_not_in_visible_row";
            return false;
        }

        reason = string.Empty;
        return true;
    }

    private static bool SameFrozenBundles(
        PendingBundleSelection pending,
        IReadOnlyList<CardModel>[] native,
        CardModel[][] cards,
        NCardBundle[] nodes)
    {
        if (pending.NativeBundles is null || pending.FrozenCards is null
            || pending.VisibleBundles is null
            || pending.NativeBundles.Length != native.Length)
        {
            return false;
        }

        for (var index = 0; index < native.Length; index++)
        {
            if (!ReferenceEquals(pending.NativeBundles[index], native[index])
                || !ReferenceEquals(pending.VisibleBundles[index], nodes[index])
                || !SameCardSequence(pending.FrozenCards[index], cards[index]))
            {
                return false;
            }
        }

        return true;
    }

    private static bool SameCardSequence(
        IReadOnlyList<CardModel> left,
        IReadOnlyList<CardModel> right) =>
        left.Count == right.Count
        && !left.Where((card, index) => !ReferenceEquals(card, right[index])).Any();

    private static void FailBundleSelection(
        PendingBundleSelection pending,
        string reason,
        object detail)
    {
        pending.Faulted = true;
        if (pending.GapRecorded)
        {
            return;
        }

        pending.GapRecorded = true;
        RecordCoverageGap(
            reason,
            detail,
            invalidatePendingDecision: pending.Prepared is not null,
            targetDecisionId: pending.Prepared?.Receipt.DecisionId);
    }
}
