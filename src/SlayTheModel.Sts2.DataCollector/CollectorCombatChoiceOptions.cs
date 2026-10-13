using System.Reflection;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Freezes only cards offered by a native combat selector. The returned order
/// is canonical, not the source pile's order, so a draw/discard pile's hidden
/// ordering cannot become a feature of the recorded decision.
/// </summary>
internal static class CollectorCombatChoiceOptions
{
    private static readonly FieldInfo? PileField =
        typeof(NCombatPileCardSelectScreen).GetField(
            "_pile", BindingFlags.Instance | BindingFlags.NonPublic);

    private static readonly FieldInfo? FilterField =
        typeof(NCombatPileCardSelectScreen).GetField(
            "_filter", BindingFlags.Instance | BindingFlags.NonPublic);

    internal static bool TryFreezePile(
        NCombatPileCardSelectScreen screen,
        out IReadOnlyList<CardModel> options,
        out string reason)
    {
        options = [];
        reason = string.Empty;

        if (screen is null)
        {
            reason = "combat_pile_screen_unavailable";
            return false;
        }

        if (PileField is null || FilterField is null)
        {
            reason = "combat_pile_selector_fields_unavailable";
            return false;
        }

        try
        {
            if (PileField.GetValue(screen) is not CardPile pile)
            {
                reason = "combat_pile_unavailable";
                return false;
            }

            if (FilterField.GetValue(screen) is not null
                and not Func<CardModel, bool>)
            {
                reason = "combat_pile_filter_unavailable";
                return false;
            }

            var filter = (Func<CardModel, bool>?)FilterField.GetValue(screen);
            var visible = pile.Cards
                .Where(card => filter is null || filter(card))
                .ToArray();
            return TryCanonicalize(visible, out options, out reason);
        }
        catch (Exception exception)
        {
            reason = $"combat_pile_options_capture_failed:{exception.GetType().Name}";
            return false;
        }
    }

    internal static bool TryFreezeHand(
        NPlayerHand hand,
        Func<CardModel, bool>? filter,
        out IReadOnlyList<CardModel> options,
        out string reason)
    {
        options = [];
        reason = string.Empty;

        if (hand is null)
        {
            reason = "combat_hand_unavailable";
            return false;
        }

        try
        {
            // SelectCards receives the native eligibility predicate. Freeze it
            // against the same internal Hand used by combat observations;
            // animation can temporarily omit cards from the UI holders.
            var manager = CombatManager.Instance;
            var state = manager.DebugOnlyGetState();
            if (!manager.IsInProgress || state is null
                || state.Players.Count != 1
                || !ReferenceEquals(hand, NPlayerHand.Instance))
            {
                reason = "combat_hand_state_unavailable";
                return false;
            }

            var nativeHand = state.Players[0].PlayerCombatState?.Hand;
            if (nativeHand is null)
            {
                reason = "combat_hand_state_unavailable";
                return false;
            }

            var eligible = nativeHand.Cards
                .Where(card => filter is null || filter(card))
                .ToArray();
            return TryCanonicalize(eligible, out options, out reason);
        }
        catch (Exception exception)
        {
            reason = $"combat_hand_options_capture_failed:{exception.GetType().Name}";
            return false;
        }
    }

    private static bool TryCanonicalize(
        IReadOnlyList<CardModel> visible,
        out IReadOnlyList<CardModel> options,
        out string reason)
    {
        options = [];
        reason = string.Empty;

        if (visible.Count == 0)
        {
            reason = "combat_choice_has_no_legal_cards";
            return false;
        }

        var db = NetCombatCardDb.Instance;
        var seen = new HashSet<uint>();
        var entries = new List<(CardModel Card, string ModelId, int Upgrade, uint CombatIndex)>(
            visible.Count);
        foreach (var card in visible)
        {
            if (card is null || !db.TryGetCardId(card, out var combatIndex))
            {
                reason = "combat_choice_card_index_unavailable";
                return false;
            }

            if (!seen.Add(combatIndex))
            {
                reason = "combat_choice_duplicate_card_index";
                return false;
            }

            entries.Add((
                card,
                card.Id.ToString(),
                card.CurrentUpgradeLevel,
                combatIndex));
        }

        // Preserve the identity of duplicate card models without preserving
        // their position inside a hidden pile.
        options = entries
            .OrderBy(entry => entry.ModelId, StringComparer.Ordinal)
            .ThenBy(entry => entry.Upgrade)
            .ThenBy(entry => entry.CombatIndex)
            .Select(entry => entry.Card)
            .ToArray();
        return true;
    }
}
