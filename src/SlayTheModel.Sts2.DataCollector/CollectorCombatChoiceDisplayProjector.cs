using System.Reflection;
using Godot;
using MegaCrit.Sts2.Core.Entities.UI;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Reads card presentation from the selector that is actually on screen when
/// a person starts selecting. Off-screen and ambiguous candidates stay null.
/// </summary>
internal static class CollectorCombatChoiceDisplayProjector
{
    private static readonly MethodInfo? HandHoldersGetter =
        typeof(NPlayerHand).GetMethod(
            "get_Holders", BindingFlags.Instance | BindingFlags.NonPublic);

    private static readonly FieldInfo? GridField =
        typeof(NCardGridSelectionScreen).GetField(
            "_grid", BindingFlags.Instance | BindingFlags.NonPublic);

    private static readonly FieldInfo? ChoiceRowField =
        typeof(NChooseACardSelectionScreen).GetField(
            "_cardRow", BindingFlags.Instance | BindingFlags.NonPublic);

    internal static IReadOnlyDictionary<CardModel, CombatCardDisplayObservation> Capture(
        object selector,
        IReadOnlyList<CardModel> offeredCards)
    {
        var displays = new Dictionary<CardModel, CombatCardDisplayObservation>(
            ReferenceEqualityComparer.Instance);
        if (selector is not CanvasItem item
            || !GodotObject.IsInstanceValid(item)
            || !item.IsInsideTree()
            || !item.IsVisibleInTree()
            || offeredCards.Count == 0)
        {
            return displays;
        }

        try
        {
            var offered = new HashSet<CardModel>(
                offeredCards, ReferenceEqualityComparer.Instance);
            var ambiguous = new HashSet<CardModel>(ReferenceEqualityComparer.Instance);
            foreach (var holder in VisibleHolders(selector))
            {
                if (holder is null || !GodotObject.IsInstanceValid(holder))
                {
                    continue;
                }

                var cardNode = holder.CardNode;
                if (cardNode is null || !GodotObject.IsInstanceValid(cardNode)
                    || !cardNode.IsInsideTree() || !cardNode.IsVisibleInTree()
                    || cardNode.Visibility != ModelVisibility.Visible
                    || cardNode.Model is not CardModel card
                    || !offered.Contains(card)
                    || ambiguous.Contains(card))
                {
                    continue;
                }

                if (displays.ContainsKey(card))
                {
                    // A second visible node may be a preview of the same
                    // model. Neither presentation is uniquely attributable.
                    displays.Remove(card);
                    ambiguous.Add(card);
                    continue;
                }

                displays.Add(card, CollectorCardDisplayProjector.ReadDisplay(card, cardNode));
            }
        }
        catch (Exception exception) when (exception is not OutOfMemoryException)
        {
            // UI nodes can disappear while a selector is animating. Do not
            // convert a best-effort feature into a made-up display value.
            displays.Clear();
        }

        return displays;
    }

    private static IEnumerable<NCardHolder> VisibleHolders(object selector)
    {
        switch (selector)
        {
            case NPlayerHand hand when hand.IsInCardSelection:
                if (HandHoldersGetter?.Invoke(hand, null)
                    is IReadOnlyList<NHandCardHolder> handHolders)
                {
                    foreach (var holder in handHolders)
                    {
                        yield return holder;
                    }
                }

                break;

            case NCardGridSelectionScreen screen:
                if (GridField?.GetValue(screen) is NCardGrid grid
                    && GodotObject.IsInstanceValid(grid))
                {
                    foreach (var holder in grid.CurrentlyDisplayedCardHolders)
                    {
                        yield return holder;
                    }
                }

                break;

            case NChooseACardSelectionScreen screen:
                if (ChoiceRowField?.GetValue(screen) is Node row
                    && GodotObject.IsInstanceValid(row))
                {
                    foreach (var holder in DescendantHolders(row))
                    {
                        yield return holder;
                    }
                }

                break;
        }
    }

    private static IEnumerable<NCardHolder> DescendantHolders(Node root)
    {
        var pending = new Stack<Node>();
        pending.Push(root);
        while (pending.TryPop(out var node))
        {
            if (!GodotObject.IsInstanceValid(node))
            {
                continue;
            }

            if (node is NCardHolder holder)
            {
                yield return holder;
            }

            foreach (var child in node.GetChildren())
            {
                pending.Push(child);
            }
        }
    }
}
