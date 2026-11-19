using System.Reflection;
using System.Runtime.CompilerServices;
using HarmonyLib;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;

namespace SlayTheModel.Headless;

/// <summary>Public memory of explicitly visible cards placed on top. Never reads draw order.</summary>
internal static class NativePublicHistory
{
    private sealed class TopMemory { internal readonly List<CardModel> Cards = []; }
    private static readonly ConditionalWeakTable<CardPile, TopMemory> Known = new();
    private static readonly Harmony Patcher = new("SlayTheModel.Headless.PublicHistory");
    private static bool _installed;

    internal static void Install()
    {
        if (_installed) return;
        Patcher.Patch(AccessTools.Method(typeof(CardPileCmd), nameof(CardPileCmd.Add),
            [typeof(IEnumerable<CardModel>), typeof(CardPile), typeof(CardPilePosition), typeof(AbstractModel), typeof(bool), typeof(bool)])
            ?? throw new MissingMethodException("CardPileCmd.Add(public history)"), postfix: Hook(nameof(AfterAdd)));
        Patcher.Patch(AccessTools.Method(typeof(CardPileCmd), nameof(CardPileCmd.Shuffle),
            [typeof(PlayerChoiceContext), typeof(Player)]), prefix: Hook(nameof(BeforeShuffle)));
        Patcher.Patch(AccessTools.Method(typeof(CardPile), nameof(CardPile.RandomizeOrderInternal)), prefix: Hook(nameof(BeforeRandomize)));
        Patcher.Patch(AccessTools.Method(typeof(CardPile), nameof(CardPile.RemoveInternal)), prefix: Hook(nameof(BeforeRemove)));
        _installed = true;
    }

    private static HarmonyMethod Hook(string name) => new(typeof(NativePublicHistory)
        .GetMethod(name, BindingFlags.Static | BindingFlags.NonPublic)!);

    private static void BeforeShuffle(Player player)
    {
        if (player.PlayerCombatState is { } combat) Known.GetOrCreateValue(combat.DrawPile).Cards.Clear();
    }

    private static void BeforeRandomize(CardPile __instance) => Known.GetOrCreateValue(__instance).Cards.Clear();
    private static void BeforeRemove(CardPile __instance, CardModel card) => Known.GetOrCreateValue(__instance).Cards.Remove(card);

    private static void AfterAdd(CardPile newPile, CardPilePosition position,
        ref Task<IReadOnlyList<CardPileAddResult>> __result)
    {
        if (newPile.Type != PileType.Draw || position == CardPilePosition.Bottom) return;
        if (position == CardPilePosition.Random)
        {
            // Random insertion may precede any remembered card. Forgetting the
            // prefix is sound; inspecting the chosen insertion index is not.
            Known.GetOrCreateValue(newPile).Cards.Clear();
            return;
        }
        __result = RememberCompleted(__result, newPile);
    }

    private static async Task<IReadOnlyList<CardPileAddResult>> RememberCompleted(
        Task<IReadOnlyList<CardPileAddResult>> operation, CardPile pile)
    {
        var result = await operation;
        var memory = Known.GetOrCreateValue(pile).Cards;
        foreach (var moved in result)
        {
            // Initial deck setup, hidden draw reordering and unrevealed generation
            // do not establish public knowledge, even when their insertion is Top.
            if (moved.oldPile?.Type is not (PileType.Hand or PileType.Discard or PileType.Exhaust or PileType.Play))
            {
                memory.Clear();
                continue;
            }
            if (!ReferenceEquals(moved.cardAdded.Pile, pile)) continue;
            memory.Remove(moved.cardAdded);
            memory.Insert(0, moved.cardAdded);
        }
        return result;
    }

    internal static IReadOnlyList<CardModel> KnownTop(CardPile pile) => Known.GetOrCreateValue(pile).Cards.ToArray();
}
