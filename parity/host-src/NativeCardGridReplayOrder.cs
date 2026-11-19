using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using MegaCrit.Sts2.Core.CardSelection;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;

namespace SlayTheModel.Headless;

/// <summary>
/// Keeps native selector input order for replay diagnostics. The grid has an
/// independent display copy, so its visible index is not a card instance
/// identity across processes. This metadata is not a model feature.
/// </summary>
internal static class NativeCardGridReplayOrder
{
    private sealed record OriginalOrder(CardModel[] Cards);
    private static readonly ConditionalWeakTable<NSimpleCardSelectScreen, OriginalOrder> Orders = new();
    private static readonly Harmony Patcher = new("SlayTheModel.Headless.CardGridReplayOrder");
    private static bool _installed;

    internal static void Install()
    {
        if (_installed) return;
        var postfix = Hook(nameof(CreatePostfix));
        Patcher.Patch(RequiredCreate(typeof(IReadOnlyList<CardModel>)),
            prefix: Hook(nameof(CardsCreatePrefix)), postfix: postfix);
        Patcher.Patch(RequiredCreate(typeof(IReadOnlyList<CardCreationResult>)),
            prefix: Hook(nameof(RewardsCreatePrefix)), postfix: postfix);
        _installed = true;
    }

    private static MethodInfo RequiredCreate(Type inputType) =>
        AccessTools.Method(typeof(NSimpleCardSelectScreen), nameof(NSimpleCardSelectScreen.Create),
            [inputType, typeof(CardSelectorPrefs)])
        ?? throw new MissingMethodException(typeof(NSimpleCardSelectScreen).FullName,
            nameof(NSimpleCardSelectScreen.Create) + "(" + inputType.Name + ")");

    private static HarmonyMethod Hook(string methodName) => new(
        typeof(NativeCardGridReplayOrder).GetMethod(methodName,
            BindingFlags.NonPublic | BindingFlags.Static)
        ?? throw new MissingMethodException(typeof(NativeCardGridReplayOrder).FullName, methodName));

    private static void CardsCreatePrefix(IReadOnlyList<CardModel> __0, out CardModel[] __state) =>
        __state = __0.ToArray();

    private static void RewardsCreatePrefix(IReadOnlyList<CardCreationResult> __0,
        out CardModel[] __state) =>
        __state = __0.Select(result => result.Card).ToArray();

    private static void CreatePostfix(NSimpleCardSelectScreen __result, CardModel[] __state)
    {
        Orders.Remove(__result);
        Orders.Add(__result, new OriginalOrder(__state));
    }

    internal static int? ReplayOrdinal(NCardGridSelectionScreen screen,
        IReadOnlyList<CardModel> displayedCards, CardModel selected)
    {
        CardModel[] source;
        if (screen is NSimpleCardSelectScreen simple
            && Orders.TryGetValue(simple, out var order))
            source = order.Cards;
        else if (screen is NDeckEnchantSelectScreen or NDeckTransformSelectScreen
                     or NDeckUpgradeSelectScreen or NDeckCardSelectScreen
            && NativeView.Get(screen, "_cards") is IEnumerable<CardModel> deckCards)
            // These deck selectors retain the native candidate list in the
            // screen's _cards; their grid has an independent display copy.
            source = deckCards.ToArray();
        else
            return null;
        var visible = displayedCards.ToHashSet(ReferenceEqualityComparer.Instance);
        var original = source.ToHashSet(ReferenceEqualityComparer.Instance);
        if (visible.Count != displayedCards.Count
            || original.Count != source.Length
            || visible.Any(card => !original.Contains(card)))
            return null;
        // The native selector can filter the input (for example, Spiral's
        // starting-card choice excludes Bash). Match the displayed subset in
        // the unsorted input order used by the native card command.
        var eligible = source.Where(visible.Contains).ToArray();
        int selectedIndex = Array.FindIndex(eligible,
            card => ReferenceEquals(card, selected));
        if (selectedIndex < 0) return null;
        string model = selected.Id.ToString();
        int upgrade = selected.CurrentUpgradeLevel;
        string enchantment = selected.Enchantment?.Id.ToString() ?? "";
        return eligible.Take(selectedIndex).Count(card => card.Id.ToString() == model
            && card.CurrentUpgradeLevel == upgrade
            && (card.Enchantment?.Id.ToString() ?? "") == enchantment);
    }
}
