using System.Reflection;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Adds current costs for every card in the internal Hand, independent of
/// hand animation. Native dynamic preview values and rendered description
/// are omitted from ordinary combat observations. Selector choices may still
/// use ReadDisplay to capture their separate visible candidate presentation.
/// </summary>
internal static class CollectorCardDisplayProjector
{
    private static readonly FieldInfo? DescriptionLabelField = typeof(NCard).GetField(
        "_descriptionLabel",
        BindingFlags.Instance | BindingFlags.NonPublic);

    internal static CombatObservation Capture(
        CombatState state,
        CombatObservation observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);

        var nativePlayers = state.Players.ToDictionary(player => player.NetId);
        var players = observation.Players.Select(playerObservation =>
        {
            if (!nativePlayers.TryGetValue(playerObservation.PlayerId, out var nativePlayer)
                || nativePlayer.PlayerCombatState is null)
            {
                throw new InvalidDataException(
                    $"Combat observation player {playerObservation.PlayerId} has no native state.");
            }

            var nativeCards = new Dictionary<uint, (string PileType, CardModel Card)>();
            foreach (var pile in nativePlayer.PlayerCombatState.AllPiles)
            {
                foreach (var card in pile.Cards)
                {
                    var cardId = NetCombatCard.FromModel(card).CombatCardIndex;
                    if (!nativeCards.TryAdd(cardId, (pile.Type.ToString(), card)))
                    {
                        throw new InvalidDataException(
                            $"Native combat card {cardId} appears in multiple piles.");
                    }
                }
            }

            var observedCardCount = 0;
            var piles = playerObservation.Piles.Select(pileObservation =>
                pileObservation with
                {
                    Cards = pileObservation.Cards.Select(cardObservation =>
                    {
                        observedCardCount++;
                        if (!nativeCards.TryGetValue(cardObservation.CombatCardIndex, out var match)
                            || !string.Equals(match.PileType, pileObservation.PileType,
                                StringComparison.Ordinal)
                            || !string.Equals(match.Card.Id.ToString(), cardObservation.ModelId,
                                StringComparison.Ordinal))
                        {
                            throw new InvalidDataException(
                                $"Combat card {cardObservation.CombatCardIndex} no longer matches its observation.");
                        }

                        var card = match.Card;
                        return cardObservation with
                        {
                            UpgradeLevel = card.CurrentUpgradeLevel,
                            EnchantmentId = card.Enchantment?.Id.ToString(),
                            EnchantmentAmount = null,
                            EnchantmentDisplay = CollectorEnchantmentDisplayProjector.Capture(card),
                            Display = string.Equals(match.PileType, PileType.Hand.ToString(),
                                          StringComparison.Ordinal)
                                ? ReadInternalHandDisplay(card)
                                : null,
                        };
                    }).ToArray(),
                }).ToArray();

            if (observedCardCount != nativeCards.Count)
            {
                throw new InvalidDataException(
                    "Combat observation and native card counts differ.");
            }

            return playerObservation with { Piles = piles };
        }).ToArray();

        return observation with { Players = players };
    }

    private static CombatCardDisplayObservation ReadInternalHandDisplay(CardModel card)
    {
        var (energyCost, starCost, costsX) = ReadCosts(card);
        return new CombatCardDisplayObservation(
            Description: null,
            energyCost,
            starCost,
            costsX,
            []);
    }

    internal static CombatCardDisplayObservation ReadDisplay(CardModel card, NCard cardNode)
    {
        var (energyCost, starCost, costsX) = ReadCosts(card);
        return new CombatCardDisplayObservation(
            ReadDescription(cardNode),
            energyCost,
            starCost,
            costsX,
            []);
    }

    private static (int? EnergyCost, int? StarCost, bool? CostsX) ReadCosts(CardModel card)
    {
        int? energyCost = null;
        int? starCost = null;
        bool? costsX = null;

        try
        {
            energyCost = card.EnergyCost.GetWithModifiers(CostModifiers.All);
            costsX = card.EnergyCost.CostsX;
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            // A transient UI/cost state must not erase the rest of the card.
        }

        try
        {
            starCost = card.GetStarCostWithModifiers();
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
        }

        return (energyCost, starCost, costsX);
    }

    private static string? ReadDescription(NCard cardNode)
    {
        try
        {
            if (DescriptionLabelField?.GetValue(cardNode) is not RichTextLabel label
                || !GodotObject.IsInstanceValid(label)
                || !label.IsInsideTree()
                || !label.IsVisibleInTree())
            {
                return null;
            }

            var text = label.Text;
            return string.IsNullOrWhiteSpace(text) ? null : text;
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            return null;
        }
    }
}
