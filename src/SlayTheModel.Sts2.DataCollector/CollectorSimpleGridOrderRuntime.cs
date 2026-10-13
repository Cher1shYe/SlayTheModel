using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;

namespace SlayTheModel.Sts2.DataCollector;

internal static partial class CollectorRuntime
{
    private sealed record SimpleGridOriginalOrder(
        long RuntimeGeneration,
        CardModel[] Cards);

    // NSimpleCardSelectScreen.Create may sort its own copy for display, while
    // CardSelectCmd reports indexes in the unsorted input list. Key by the
    // screen instance so adjacent selectors cannot exchange index spaces.
    private static ConditionalWeakTable<NSimpleCardSelectScreen,
        SimpleGridOriginalOrder> SimpleGridOriginalOrders = new();

    internal static void RegisterSimpleGridOriginalOrder(
        NSimpleCardSelectScreen screen,
        IReadOnlyList<CardModel>? originalCards)
    {
        if (originalCards is null)
        {
            return;
        }

        SimpleGridOriginalOrders.Remove(screen);
        SimpleGridOriginalOrders.Add(
            screen,
            new SimpleGridOriginalOrder(_runGeneration, originalCards.ToArray()));
    }

    internal static bool TryMapSimpleGridReceiptIndexes(
        object selector,
        IReadOnlyList<CardModel> uiOptions,
        IReadOnlyList<int> selectedUiIndexes,
        out int[] originalIndexes)
    {
        originalIndexes = [];
        if (selector is not NSimpleCardSelectScreen screen
            || !SimpleGridOriginalOrders.TryGetValue(screen, out var order)
            || order.RuntimeGeneration != _runGeneration
            || order.Cards.Length != uiOptions.Count)
        {
            return false;
        }

        var positions = new Dictionary<CardModel, int>(
            ReferenceEqualityComparer.Instance);
        for (var index = 0; index < order.Cards.Length; index++)
        {
            var card = order.Cards[index];
            if (card is null || !positions.TryAdd(card, index))
            {
                return false;
            }
        }

        var uiToOriginal = new int[uiOptions.Count];
        var visibleIdentities = new HashSet<CardModel>(
            ReferenceEqualityComparer.Instance);
        for (var index = 0; index < uiOptions.Count; index++)
        {
            var card = uiOptions[index];
            if (card is null || !visibleIdentities.Add(card)
                || !positions.TryGetValue(card, out uiToOriginal[index]))
            {
                return false;
            }
        }

        var selected = new HashSet<int>();
        foreach (var uiIndex in selectedUiIndexes)
        {
            if (uiIndex < 0 || uiIndex >= uiToOriginal.Length
                || !selected.Add(uiIndex))
            {
                return false;
            }
        }

        originalIndexes = selected.Select(index => uiToOriginal[index])
            .Order().ToArray();
        return true;
    }

    internal static void ForgetSimpleGridOriginalOrder(object selector)
    {
        if (selector is NSimpleCardSelectScreen screen)
        {
            SimpleGridOriginalOrders.Remove(screen);
        }
    }

    internal static void ClearSimpleGridOriginalOrders() =>
        SimpleGridOriginalOrders = new ConditionalWeakTable<
            NSimpleCardSelectScreen, SimpleGridOriginalOrder>();
}
