using System.Reflection;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.UI;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal sealed class PendingMultiCardSelection(
    object selector,
    PreparedOutsideDecision prepared,
    IReadOnlyList<CardModel> options,
    IReadOnlyList<int?> optionDeckIndexes,
    int minSelections,
    int maxSelections,
    bool cancelable,
    string description,
    long runtimeGeneration)
{
    internal object Selector { get; } = selector;
    internal PreparedOutsideDecision Prepared { get; } = prepared;
    internal IReadOnlyList<CardModel> Options { get; } = options;
    internal IReadOnlyList<int?> OptionDeckIndexes { get; } = optionDeckIndexes;
    internal int MinSelections { get; } = minSelections;
    internal int MaxSelections { get; } = maxSelections;
    internal bool Cancelable { get; } = cancelable;
    internal string Description { get; } = description;
    internal long RuntimeGeneration { get; } = runtimeGeneration;
    internal Task<IEnumerable<CardModel>>? CompletionTask { get; set; }
    internal HashSet<int> ClickedOptionIndexes { get; } = [];
    internal int[]? LastSelectedOptionIndexes { get; set; }
    internal int[]? CurrentClickBeforeIndexes { get; set; }
    internal int[]? CurrentClickExpectedAfterIndexes { get; set; }
    internal int? CurrentClickedOptionIndex { get; set; }
    internal string? ClickEvidenceFailure { get; set; }
    internal bool CancelledByManualInput { get; set; }
    internal bool ManualConfirmationObserved { get; set; }
    internal bool NativeReceiptObserved { get; set; }
    internal bool NativeReceiptGraceUsed { get; set; }
    internal uint? NativeChoiceId { get; set; }
    internal uint? ParentActionId { get; set; }
    internal string? NativeReceiptKind { get; set; }
    internal int[]? NativeOptionIndexes { get; set; }
    internal int[]? NativeDeckIndexes { get; set; }
}

internal static partial class CollectorRuntime
{
    // One legal template stands for the native set-selection operation. The
    // concrete chosen set is attached only after internal click state, final
    // confirmation where required, Task, and native receipt agree.
    private const BindingFlags PrivateInstance =
        BindingFlags.Instance | BindingFlags.NonPublic;
    private static readonly FieldInfo? GridField =
        typeof(NCardGridSelectionScreen).GetField("_grid", PrivateInstance);
    private static readonly FieldInfo? ScreenCardsField =
        typeof(NCardGridSelectionScreen).GetField("_cards", PrivateInstance);
    private static readonly FieldInfo? GridCardsField =
        typeof(NCardGrid).GetField("_cards", PrivateInstance);
    private static (uint ChoiceId, uint? ParentActionId, long Generation)?
        _lastReservedMultiCardChoice;

    internal static void VerifyMultiCardVisibleClick(object selector, CardModel clicked)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is not null
            && !TryVerifyVisibleGridOptions(
                selector, pending.Options, clicked, out var reason))
        {
            pending.ClickEvidenceFailure = reason;
        }
    }

    internal static void NoteReservedMultiCardChoiceId(Player player, uint choiceId)
    {
        if (_episodes?.HasActiveEpisode != true
            || CombatManager.Instance.IsInProgress
            || !IsLocalSinglePlayer(player))
        {
            return;
        }

        var parentActionId = RunManager.Instance.ActionExecutor.CurrentlyRunningAction?.Id;
        var awaiting = PendingOutsideOperations
            .OfType<PendingMultiCardSelection>()
            .Where(item => item.RuntimeGeneration == _runGeneration
                           && item.ParentActionId == parentActionId
                           && item.NativeChoiceId is null
                           && item.CompletionTask?.IsCompleted != true)
            .ToArray();
        if (awaiting.Length == 1)
        {
            awaiting[0].NativeChoiceId = choiceId;
            _lastReservedMultiCardChoice = null;
            return;
        }

        _lastReservedMultiCardChoice = (choiceId, parentActionId, _runGeneration);
    }

    private static uint? TakeReservedMultiCardChoiceId(uint? parentActionId)
    {
        var reserved = _lastReservedMultiCardChoice;
        _lastReservedMultiCardChoice = null;
        return reserved is { } value
               && value.Generation == _runGeneration
               && value.ParentActionId == parentActionId
            ? value.ChoiceId
            : null;
    }

    internal static PendingMultiCardSelection? PrepareMultiCardSelection(
        object selector,
        IReadOnlyList<CardModel> cards,
        int minSelections,
        int maxSelections,
        bool requiresConfirmation,
        bool cancelable,
        bool removalSelection,
        string contextId)
    {
        PreparedOutsideDecision? prepared = null;
        try
        {
            if (_stopping || _episodes?.HasActiveEpisode != true
                || !RunManager.Instance.IsInProgress)
            {
                return null;
            }

            DrainCompletedSelectors();
            CompleteAcceptedParentActions(contextId, nestedSelectorObserved: true);
            _episodes.ResolveAtCurrentBoundary();
            if (CombatManager.Instance.IsInProgress
                || RunManager.Instance.DebugOnlyGetState() is not { } state
                || state.Players.Count != 1
                || cards.Count == 0
                || selector is not (NSimpleCardSelectScreen
                    or NDeckCardSelectScreen or NDeckEnchantSelectScreen
                    or NDeckTransformSelectScreen or NDeckUpgradeSelectScreen))
            {
                RecordCoverageGap(
                    "multi_card_selection_options_unavailable",
                    new
                    {
                        contextId,
                        option_count = cards.Count,
                        selector_type = selector.GetType().FullName,
                    },
                    invalidatePendingDecision: false);
                return null;
            }

            // NSimple only completes automatically at MaxSelect when there is
            // no manual confirmation button. Enchant, transform, and upgrade
            // screens open a preview with a final confirmation.
            var effectiveRequiresConfirmation = requiresConfirmation
                || selector is NDeckEnchantSelectScreen or NDeckTransformSelectScreen
                    or NDeckUpgradeSelectScreen;
            var effectiveMaxSelections = Math.Min(maxSelections, cards.Count);
            var effectiveMinSelections = selector switch
            {
                NSimpleCardSelectScreen when !effectiveRequiresConfirmation =>
                    effectiveMaxSelections,
                NDeckUpgradeSelectScreen => effectiveMaxSelections,
                NDeckEnchantSelectScreen => Math.Max(1, minSelections),
                _ => minSelections,
            };
            if (effectiveMinSelections < 1
                || effectiveMaxSelections < effectiveMinSelections
                || minSelections > maxSelections)
            {
                RecordCoverageGap(
                    "unsupported_multi_card_selection",
                    new
                    {
                        contextId,
                        min_selections = minSelections,
                        effective_min_selections = effectiveMinSelections,
                        max_selections = effectiveMaxSelections,
                        option_count = cards.Count,
                    },
                    invalidatePendingDecision: false);
                return null;
            }

            if (selector is NSimpleCardSelectScreen
                && !TryMapSimpleGridReceiptIndexes(
                    selector,
                    cards,
                    Enumerable.Range(0, cards.Count).ToArray(),
                    out _))
            {
                RecordCoverageGap(
                    "multi_card_original_option_order_unavailable",
                    new { contextId, option_count = cards.Count },
                    invalidatePendingDecision: false);
                return null;
            }

            var deck = state.Players[0].Deck.Cards.ToArray();
            var optionDeckIndexes = cards.Select(card =>
                (int?)Array.FindIndex(deck, candidate => ReferenceEquals(candidate, card)))
                .Select(index => index >= 0 ? index : null)
                .ToArray();
            if ((removalSelection || selector is NDeckEnchantSelectScreen
                    or NDeckTransformSelectScreen or NDeckUpgradeSelectScreen)
                && optionDeckIndexes.Any(index => index is null))
            {
                RecordCoverageGap(
                    removalSelection
                        ? "multi_card_removal_option_not_in_deck"
                        : selector is NDeckTransformSelectScreen
                            ? "multi_card_transform_option_not_in_deck"
                            : selector is NDeckUpgradeSelectScreen
                                ? "multi_card_upgrade_option_not_in_deck"
                                : "multi_card_enchant_option_not_in_deck",
                    new { contextId },
                    invalidatePendingDecision: false);
                return null;
            }

            var kind = removalSelection
                ? OutsideCombatActionKind.RemoveCardSet
                : OutsideCombatActionKind.ChooseCardSet;
            var candidates = cards.Select((card, index) =>
                    new OutsideSelectedCardReference(
                        index, card.Id.ToString(), optionDeckIndexes[index]))
                .ToArray();
            var actions = new List<OutsideCombatActionDescriptor>(cancelable ? 2 : 1)
            {
                new OutsideCombatActionDescriptor(
                    $"{kind.ToString().ToLowerInvariant()}:0:set",
                    kind,
                    0)
                {
                    IsSelectionTemplate = true,
                },
            };

            if (cancelable)
            {
                actions.Add(new OutsideCombatActionDescriptor(
                    $"cancel_selection:{actions.Count}",
                    OutsideCombatActionKind.CancelSelection,
                    actions.Count,
                    "cancel"));
            }

            var decision = CollectorOutsideProjector.Build(
                state,
                OutsideCombatSurfaceKind.CardGridChoice,
                contextId,
                actions,
                _episodes.NextSourceDecisionIndex(),
                OutsideCombatChoicePhase.Selection,
                effectiveMinSelections,
                effectiveMaxSelections,
                cancelable: cancelable,
                requiresConfirmation: effectiveRequiresConfirmation,
                cardSelectionOptions: candidates);
            var audit = JsonSerializer.SerializeToElement(new
            {
                during_combat = false,
                combat_id = _combatId,
                parent_action_id = RunManager.Instance.ActionExecutor
                    .CurrentlyRunningAction?.Id,
            });
            var parentActionId = RunManager.Instance.ActionExecutor
                .CurrentlyRunningAction?.Id;
            prepared = _episodes.PrepareOutside(decision, contextId, audit);
            var pending = new PendingMultiCardSelection(
                selector,
                prepared,
                cards.ToArray(),
                optionDeckIndexes,
                effectiveMinSelections,
                effectiveMaxSelections,
                cancelable,
                contextId,
                _runGeneration)
            {
                NativeChoiceId = TakeReservedMultiCardChoiceId(parentActionId),
                ParentActionId = parentActionId,
            };
            PendingOutsideOperations.Add(pending);
            return pending;
        }
        catch (Exception exception)
        {
            RecordCoverageGap(
                "multi_card_selection_prepare_failed",
                new { contextId, error = exception.ToString() },
                invalidatePendingDecision: prepared is not null,
                relatedDecisionId: prepared?.Receipt.DecisionId,
                targetDecisionId: prepared?.Receipt.DecisionId);
            return null;
        }
    }

    internal static void ObserveMultiCardClickBefore(
        object selector,
        CardModel clicked,
        IReadOnlyCollection<CardModel>? nativeSelectedCards)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is null)
        {
            return;
        }

        var clickedIndex = IndexOfExactCard(pending.Options, clicked);
        var before = nativeSelectedCards?
            .Select(card => IndexOfExactCard(pending.Options, card))
            .Order().ToArray();
        if (clickedIndex < 0 || before is null
            || before.Any(index => index < 0)
            || before.Distinct().Count() != before.Length
            || before.Length > pending.MaxSelections
            || pending.LastSelectedOptionIndexes is { } previous
               && !before.SequenceEqual(previous)
            || pending.LastSelectedOptionIndexes is null && before.Length != 0)
        {
            pending.ClickEvidenceFailure = "click or prior selected set did not match frozen options";
            return;
        }

        pending.CurrentClickBeforeIndexes = before;
        pending.CurrentClickedOptionIndex = clickedIndex;
        var expected = before.Contains(clickedIndex)
            ? before.Where(index => index != clickedIndex).ToArray()
            : before.Length < pending.MaxSelections
                ? before.Append(clickedIndex).Order().ToArray()
                : before;
        pending.CurrentClickExpectedAfterIndexes = expected;
        // NSimple can complete its Task and open the next selector before the
        // Harmony postfix runs. Task and native receipt must still match this
        // click's predicted native toggle before the label is accepted.
        pending.LastSelectedOptionIndexes = expected;
        pending.ClickedOptionIndexes.Add(clickedIndex);
    }

    internal static void ObserveMultiCardCancel(object selector)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is not null)
        {
            if (TryVerifyVisibleGridOptions(
                    selector, pending.Options, clicked: null, out var reason))
            {
                pending.CancelledByManualInput = true;
            }
            else
            {
                pending.ClickEvidenceFailure = reason;
            }
        }
    }

    internal static void ObserveMultiCardInternalCancel(object selector)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is { Cancelable: true }
            && pending.CompletionTask?.IsCompleted != true)
        {
            pending.CancelledByManualInput = true;
        }
    }

    internal static void ObserveMultiCardInternalConfirm(
        object selector,
        IReadOnlyCollection<CardModel>? nativeSelectedCards)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is null)
        {
            return;
        }

        if (pending.CompletionTask?.IsCompleted == true
            || pending.CancelledByManualInput)
        {
            return;
        }

        var indexes = nativeSelectedCards?
            .Select(card => IndexOfExactCard(pending.Options, card))
            .Order().ToArray();
        if (indexes is null
            || indexes.Length < pending.MinSelections
            || indexes.Length > pending.MaxSelections
            || indexes.Any(index => index < 0)
            || indexes.Distinct().Count() != indexes.Length
            || pending.LastSelectedOptionIndexes is not { } last
            || !indexes.SequenceEqual(last)
            || indexes.Any(index => !pending.ClickedOptionIndexes.Contains(index)))
        {
            pending.ClickEvidenceFailure =
                "native confirmation did not match frozen internal card selection";
            return;
        }

        pending.ManualConfirmationObserved = true;
    }

    internal static void ObserveMultiCardManualConfirm(
        NCardGridSelectionScreen selector,
        NButton button,
        IReadOnlyCollection<CardModel>? nativeSelectedCards)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is null)
        {
            return;
        }

        // ConfirmSelection ignores the empty set. An ignored click must not
        // poison a later valid confirmation or become a behavior label.
        if (nativeSelectedCards is { Count: 0 })
        {
            return;
        }

        var indexes = nativeSelectedCards?
            .Select(card => IndexOfExactCard(pending.Options, card))
            .Order().ToArray();
        if (!GodotObject.IsInstanceValid(selector) || !selector.IsInsideTree()
            || !selector.IsVisibleInTree()
            || !GodotObject.IsInstanceValid(button) || !button.IsInsideTree()
            || !button.IsVisibleInTree() || !button.IsEnabled
            || indexes is null
            || indexes.Length < pending.MinSelections
            || indexes.Length > pending.MaxSelections
            || indexes.Any(index => index < 0)
            || indexes.Distinct().Count() != indexes.Length
            || pending.LastSelectedOptionIndexes is not { } last
            || !indexes.SequenceEqual(last)
            || indexes.Any(index => !pending.ClickedOptionIndexes.Contains(index)))
        {
            pending.ClickEvidenceFailure =
                "manual confirmation did not match visible card selection";
            return;
        }

        pending.ManualConfirmationObserved = true;
    }

    internal static void ObserveMultiCardPreviewBack(
        object selector,
        IReadOnlyCollection<CardModel>? nativeSelectedCards)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is null)
        {
            return;
        }

        if (nativeSelectedCards is not { Count: 0 }
            || pending.NativeReceiptObserved)
        {
            pending.ClickEvidenceFailure = "preview back did not clear native selected cards";
            return;
        }

        pending.LastSelectedOptionIndexes = [];
        pending.ManualConfirmationObserved = false;
        pending.CurrentClickBeforeIndexes = null;
        pending.CurrentClickExpectedAfterIndexes = null;
        pending.CurrentClickedOptionIndex = null;
    }

    internal static void ObserveMultiCardClick(
        object selector,
        CardModel clicked,
        IReadOnlyCollection<CardModel>? nativeSelectedCards)
    {
        var pending = FindPendingMultiCardSelection(selector);
        if (pending is null)
        {
            return;
        }

        var clickedIndex = IndexOfExactCard(pending.Options, clicked);
        var selectedIndexes = nativeSelectedCards?
            .Select(card => IndexOfExactCard(pending.Options, card))
            .Order()
            .ToArray();
        var before = pending.CurrentClickBeforeIndexes;
        var expected = pending.CurrentClickExpectedAfterIndexes;
        var changed = before is null || selectedIndexes is null
            ? Array.Empty<int>()
            : before.Except(selectedIndexes)
                .Concat(selectedIndexes.Except(before))
                .ToArray();
        if (before is not null && selectedIndexes is not null
            && expected is not null && expected.SequenceEqual(before)
            && selectedIndexes.SequenceEqual(before))
        {
            // A click at the native selection limit may be ignored. It is not
            // an additional selected card or evidence of a transition.
            pending.CurrentClickBeforeIndexes = null;
            pending.CurrentClickExpectedAfterIndexes = null;
            pending.CurrentClickedOptionIndex = null;
            return;
        }

        if (clickedIndex < 0 || selectedIndexes is null
            || selectedIndexes.Any(index => index < 0)
            || selectedIndexes.Distinct().Count() != selectedIndexes.Length
            || selectedIndexes.Length > pending.MaxSelections
            || before is null
            || expected is null
            || !selectedIndexes.SequenceEqual(expected)
            || pending.CurrentClickedOptionIndex != clickedIndex
            || changed.Length != 1
            || changed[0] != clickedIndex)
        {
            pending.ClickEvidenceFailure = "native click or selected set did not match frozen options";
            return;
        }

        pending.CurrentClickBeforeIndexes = null;
        pending.CurrentClickExpectedAfterIndexes = null;
        pending.CurrentClickedOptionIndex = null;
        pending.ClickedOptionIndexes.Add(clickedIndex);
        pending.LastSelectedOptionIndexes = selectedIndexes;
    }

    private static PendingMultiCardSelection? FindPendingMultiCardSelection(object selector) =>
        PendingOutsideOperations
            .OfType<PendingMultiCardSelection>()
            .SingleOrDefault(item => ReferenceEquals(item.Selector, selector)
                                     && item.RuntimeGeneration == _runGeneration);

    internal static bool ObserveNativeMultiCardChoice(
        uint choiceId,
        NetPlayerChoiceResult result,
        uint? parentActionId)
    {
        if (CombatManager.Instance.IsInProgress)
        {
            return false;
        }

        var candidates = PendingOutsideOperations
            .OfType<PendingMultiCardSelection>()
            .Where(item => item.RuntimeGeneration == _runGeneration)
            .ToArray();
        if (candidates.Length != 1)
        {
            return false;
        }

        var pending = candidates[0];
        if (pending.NativeChoiceId is { } knownChoiceId
            ? knownChoiceId != choiceId
            : pending.ClickedOptionIndexes.Count == 0
              || pending.ParentActionId != parentActionId)
        {
            return false;
        }
        var kind = result.type.ToString();
        // v0.111.0 also reports a multi-card FromIndexes receipt as "Index"
        // with multiple indexes (observed [0,2]); the array and Task still
        // have to match exactly before the choice is accepted.
        if (pending.Selector is NSimpleCardSelectScreen
            && kind is not ("Index" or "Indexes")
            || (pending.Selector is NDeckCardSelectScreen or NDeckEnchantSelectScreen
                or NDeckTransformSelectScreen or NDeckUpgradeSelectScreen)
                && kind != "DeckCard")
        {
            return false;
        }
        if (kind is "Index" or "Indexes")
        {
            pending.NativeOptionIndexes = result.indexes?
                .Order().ToArray() ?? [];
        }
        else if (kind == "DeckCard")
        {
            pending.NativeDeckIndexes = result.deckCards?
                .Select(card => checked((int)card.DeckIndex))
                .Order().ToArray() ?? [];
        }
        else
        {
            return false;
        }

        pending.NativeChoiceId = choiceId;
        pending.NativeReceiptKind = kind;
        pending.NativeReceiptObserved = true;
        if (pending.CompletionTask?.IsCompleted == true)
        {
            ScheduleOnMainThread(DrainCompletedSelectors);
        }
        RecordDiagnostic("native_multi_card_choice_correlated", new
        {
            choice_id = choiceId,
            pending.Description,
            native_option_indexes = pending.NativeOptionIndexes,
            native_deck_indexes = pending.NativeDeckIndexes,
        });
        return true;
    }

    internal static void AttachMultiCardSelectionTask(
        PendingMultiCardSelection? pending,
        Task<IEnumerable<CardModel>> task)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (pending is null || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        pending.CompletionTask = task;
        ObserveSelectorTask(task);
    }

    private static void DrainCompletedMultiCardSelections()
    {
        foreach (var pending in PendingOutsideOperations
                     .OfType<PendingMultiCardSelection>()
                     .Where(item => item.CompletionTask?.IsCompleted == true)
                     .ToArray())
        {
            var task = pending.CompletionTask!;
            var selected = task.Status == TaskStatus.RanToCompletion
                ? task.Result.ToArray()
                : null;
            if (task.Status == TaskStatus.RanToCompletion
                && !pending.NativeReceiptObserved
                && !pending.NativeReceiptGraceUsed
                && !(pending.Cancelable && pending.CancelledByManualInput
                     && selected is { Length: 0 }))
            {
                pending.NativeReceiptGraceUsed = true;
                ScheduleOnMainThread(DrainCompletedSelectors);
                continue;
            }

            CompleteMultiCardSelection(
                pending,
                selected,
                SelectorTaskException(task));
        }
    }

    internal static void CompleteMultiCardSelection(
        PendingMultiCardSelection? pending,
        IReadOnlyList<CardModel>? selected,
        Exception? exception = null)
    {
        if (pending is null || pending.RuntimeGeneration != _runGeneration
            || !PendingOutsideOperations.Contains(pending))
        {
            return;
        }

        try
        {
            if (exception is not null)
            {
                FailMultiCardSelection(pending, "multi_card_selection_failed",
                    new { pending.Description, error = exception.ToString() });
                return;
            }

            var chosen = selected ?? [];
            if (chosen.Count == 0 && pending.Cancelable
                && pending.CancelledByManualInput
                && pending.ClickEvidenceFailure is null)
            {
                var cancelDraft = _episodes?.ResolveOutside(
                    pending.Prepared, selectedActionIndex: 1);
                if (cancelDraft is not null)
                {
                    var cancelCapture = new NativeActionCapture(
                        cancelDraft, pending.Description, _runGeneration);
                    PendingOutsideOperations.Add(cancelCapture);
                    MarkNativeActionAccepted(cancelCapture);
                }

                return;
            }

            var indexes = chosen
                .Select(card => IndexOfExactCard(pending.Options, card))
                .Order().ToArray();
            if (indexes.Length < pending.MinSelections
                || indexes.Length > pending.MaxSelections
                || indexes.Any(index => index < 0)
                || indexes.Distinct().Count() != indexes.Length
                || pending.CancelledByManualInput
                || (pending.Selector is NDeckEnchantSelectScreen
                    or NDeckTransformSelectScreen or NDeckUpgradeSelectScreen)
                   && !pending.ManualConfirmationObserved
                || pending.ClickEvidenceFailure is not null
                || pending.LastSelectedOptionIndexes is null
                || !indexes.SequenceEqual(pending.LastSelectedOptionIndexes)
                || pending.CurrentClickBeforeIndexes is not null
                   && (pending.CurrentClickExpectedAfterIndexes is null
                       || !indexes.SequenceEqual(
                           pending.CurrentClickExpectedAfterIndexes))
                || indexes.Any(index => !pending.ClickedOptionIndexes.Contains(index)))
            {
                FailMultiCardSelection(pending, "multi_card_selection_evidence_mismatch",
                    new
                    {
                        pending.Description,
                        selected_count = chosen.Count,
                        pending.ClickEvidenceFailure,
                        pending.ManualConfirmationObserved,
                        task_option_indexes = indexes,
                        clicked_option_indexes = pending.ClickedOptionIndexes.Order().ToArray(),
                        ui_option_indexes = pending.LastSelectedOptionIndexes,
                    });
                return;
            }

            var expectedNativeOptionIndexes = indexes;
            if (pending.Selector is NSimpleCardSelectScreen
                && !TryMapSimpleGridReceiptIndexes(
                    pending.Selector,
                    pending.Options,
                    indexes,
                    out expectedNativeOptionIndexes))
            {
                FailMultiCardSelection(pending, "multi_card_original_option_order_unavailable",
                    new { pending.Description, task_option_indexes = indexes });
                return;
            }

            if (!pending.NativeReceiptObserved
                || pending.NativeOptionIndexes is { } nativeOptions
                   && !expectedNativeOptionIndexes.SequenceEqual(nativeOptions)
                || pending.NativeDeckIndexes is { } nativeDeck
                   && !indexes.Select(index => pending.OptionDeckIndexes[index])
                       .All(index => index is not null)
                || pending.NativeDeckIndexes is { } nativeDeckIndexes
                   && !indexes.Select(index => pending.OptionDeckIndexes[index]!.Value)
                       .Order().SequenceEqual(nativeDeckIndexes))
            {
                FailMultiCardSelection(pending, "multi_card_native_result_mismatch",
                    new
                    {
                        pending.Description,
                        task_option_indexes = indexes,
                        pending.NativeReceiptKind,
                        pending.NativeOptionIndexes,
                        pending.NativeDeckIndexes,
                    });
                return;
            }

            var template = pending.Prepared.Decision.LegalActions
                .Deserialize<OutsideCombatActionDescriptor[]>(CollectorJson.Options)?[0]
                ?? throw new InvalidDataException("Card-set template is missing.");
            var concrete = template with
            {
                IsSelectionTemplate = false,
                SelectedCards = indexes.Select(index =>
                    new OutsideSelectedCardReference(
                        index,
                        pending.Options[index].Id.ToString(),
                        pending.OptionDeckIndexes[index])).ToArray(),
            };
            var draft = _episodes?.ResolveOutside(
                pending.Prepared,
                selectedActionIndex: 0,
                selectedAction: JsonSerializer.SerializeToElement(
                    concrete, CollectorJson.Options));
            if (draft is not null)
            {
                var capture = new NativeActionCapture(draft, pending.Description, _runGeneration);
                PendingOutsideOperations.Add(capture);
                MarkNativeActionAccepted(capture);
            }
        }
        finally
        {
            ForgetSimpleGridOriginalOrder(pending.Selector);
            CompletePendingOutsideOperation(pending);
        }
    }

    private static void FailMultiCardSelection(
        PendingMultiCardSelection pending,
        string reason,
        object data)
    {
        var decisionId = pending.Prepared.Receipt.DecisionId;
        RecordCoverageGap(
            reason,
            data,
            relatedDecisionId: decisionId,
            targetDecisionId: decisionId);
    }

    private static int IndexOfExactCard(
        IReadOnlyList<CardModel> options,
        CardModel selected)
    {
        for (var index = 0; index < options.Count; index++)
        {
            if (ReferenceEquals(options[index], selected))
            {
                return index;
            }
        }

        return -1;
    }

    private static bool TryVerifyVisibleGridOptions(
        object selector,
        IReadOnlyList<CardModel> frozenOptions,
        CardModel? clicked,
        out string reason)
    {
        reason = "card_grid_ui_unavailable";
        try
        {
            if (selector is not NCardGridSelectionScreen screen
                || !GodotObject.IsInstanceValid(screen)
                || !screen.IsInsideTree() || !screen.IsVisibleInTree()
                || GridField?.GetValue(screen) is not NCardGrid grid
                || !GodotObject.IsInstanceValid(grid)
                || !grid.IsInsideTree() || !grid.IsVisibleInTree()
                || ScreenCardsField?.GetValue(screen) is not IReadOnlyList<CardModel> screenCards
                || GridCardsField?.GetValue(grid) is not IReadOnlyList<CardModel> gridCards
                || screenCards.Count != frozenOptions.Count
                || gridCards.Count != frozenOptions.Count
                || frozenOptions.Count == 0)
            {
                return false;
            }

            var identities = new HashSet<CardModel>(ReferenceEqualityComparer.Instance);
            for (var index = 0; index < frozenOptions.Count; index++)
            {
                if (frozenOptions[index] is null
                    || !identities.Add(frozenOptions[index])
                    || !ReferenceEquals(screenCards[index], frozenOptions[index]))
                {
                    reason = "card_grid_candidate_identity_or_order_changed";
                    return false;
                }
            }

            // Enchant and upgrade screens ask NCardGrid to sort their visible holders.
            // Native DeckCard receipts use deck indexes, not that display
            // order. Keep the frozen selector order for action option indexes
            // and require the grid to contain exactly the same card objects.
            if (selector is NDeckEnchantSelectScreen or NDeckUpgradeSelectScreen)
            {
                var gridIdentities = new HashSet<CardModel>(
                    ReferenceEqualityComparer.Instance);
                if (gridCards.Any(card => !identities.Contains(card)
                    || !gridIdentities.Add(card)))
                {
                    reason = "card_grid_candidate_identity_changed";
                    return false;
                }
            }
            else if (gridCards.Where((card, index) =>
                         !ReferenceEquals(card, frozenOptions[index])).Any())
            {
                reason = "card_grid_candidate_identity_or_order_changed";
                return false;
            }

            var displayed = new HashSet<CardModel>(ReferenceEqualityComparer.Instance);
            var clickedVisibleCount = 0;
            foreach (var holder in grid.CurrentlyDisplayedCardHolders)
            {
                if (holder is null || !GodotObject.IsInstanceValid(holder)
                    || !holder.IsInsideTree() || !holder.IsVisibleInTree())
                {
                    continue;
                }

                var cardNode = holder.CardNode;
                if (cardNode is null || !GodotObject.IsInstanceValid(cardNode)
                    || !cardNode.IsInsideTree() || !cardNode.IsVisibleInTree()
                    || cardNode.Visibility != ModelVisibility.Visible
                    || cardNode.Model is not CardModel model
                    || !identities.Contains(model)
                    || !displayed.Add(model))
                {
                    reason = "card_grid_visible_holder_mismatch";
                    return false;
                }

                if (clicked is not null && ReferenceEquals(model, clicked)
                    && holder.Hitbox is { } hitbox
                    && GodotObject.IsInstanceValid(hitbox)
                    && hitbox.IsVisibleInTree())
                {
                    clickedVisibleCount++;
                }
            }

            if (displayed.Count == 0
                || clicked is not null && clickedVisibleCount != 1)
            {
                reason = "clicked_card_not_uniquely_visible_in_grid";
                return false;
            }

            reason = string.Empty;
            return true;
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            reason = $"card_grid_visibility_check_failed:{exception.GetType().Name}";
            return false;
        }
    }

}
