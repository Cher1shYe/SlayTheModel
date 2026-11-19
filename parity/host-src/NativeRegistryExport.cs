using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;

namespace SlayTheModel.Headless;

// Offline audit only: never included in the policy observation or action API.
internal static class NativeRegistryExport
{
    private static string Id(AbstractModel model) => model.Id.Entry;
    private static object[] Vars(DynamicVarSet vars) => vars.OrderBy(pair => pair.Key, StringComparer.Ordinal)
        .Select(pair => (object)new { name = pair.Key, value = pair.Value.BaseValue }).ToArray();
    private static object? Read(Func<object?> read)
    {
        try { return read(); }
        catch (Exception error) { return new { error = error.GetType().Name, message = error.Message }; }
    }
    internal static async Task WriteAsync(string path)
    {
        var relicPools = ModelDb.AllRelicPools.ToArray();
        var potionPools = ModelDb.AllPotionPools.ToArray();
        var cardPools = ModelDb.AllCardPools.ToArray();
        var cards = ModelDb.AllCards.ToArray();
        var relics = ModelDb.AllRelics.ToArray();
        var potions = ModelDb.AllPotions.ToArray();
        var events = ModelDb.AllEvents.ToArray();
        var ancients = ModelDb.AllAncients.ToArray();
        var monsters = ModelDb.Monsters.ToArray();
        var encounters = ModelDb.AllEncounters.ToArray();
        var hpA0 = monsters.ToDictionary(Id, monster => Read(() => new[] {monster.MinInitialHp, monster.MaxInitialHp}));
        // Ordinary native initialization supplies the target A10 context; no
        // reflection writes, forced ascension return values or replaced rules.
        await NativeBootstrap.StartNewRunAsync("IRONCLAD", 10, "REGISTRY0001", "eng");
        var result = new
        {
            schema = "sts2.registry/1", gameVersion = NativeBootstrap.GameVersion,
            gameCommit = NativeBootstrap.GameCommit, gameDllSha256 = NativeBootstrap.GameDllSha256,
            context = new { hpA0 = "before run (native HasAscension=false)", hpA10 = "ordinary Ironclad A10 run", unlocks = "all epochs revealed; unfiltered ModelDb lists" },
            cards = cards.Select(card => new
            {
                id = Id(card), className = card.GetType().Name, namespaceName = card.GetType().Namespace,
                poolIds = cardPools.Where(pool => pool.AllCards.Contains(card)).Select(Id).ToArray(),
                type = card.Type.ToString(), rarity = card.Rarity.ToString(), target = card.TargetType.ToString(),
                multiplayerConstraint = card.MultiplayerConstraint.ToString(), maxUpgrade = card.MaxUpgradeLevel,
                canBeGeneratedInCombat = card.CanBeGeneratedInCombat, tags = card.Tags.Select(tag => tag.ToString()).ToArray(),
                variants = new[] {CardVariant(card, false), CardVariant(card, true)},
            }).ToArray(),
            relics = relics.Select(relic => new
            {
                id = Id(relic), className = relic.GetType().Name, namespaceName = relic.GetType().Namespace,
                rarity = (int)relic.Rarity, rarityName = relic.Rarity.ToString(),
                poolIds = relicPools.Where(pool => pool.AllRelics.Contains(relic)).Select(Id).ToArray(),
                vars = Read(() => Vars(relic.DynamicVars)),
            }).ToArray(),
            potions = potions.Select(potion => new
            {
                id = Id(potion), className = potion.GetType().Name, namespaceName = potion.GetType().Namespace,
                rarity = (int)potion.Rarity, rarityName = potion.Rarity.ToString(),
                usage = (int)potion.Usage, usageName = potion.Usage.ToString(),
                target = (int)potion.TargetType, targetName = potion.TargetType.ToString(),
                canBeGeneratedInCombat = potion.CanBeGeneratedInCombat,
                poolIds = potionPools.Where(pool => pool.AllPotions.Contains(potion)).Select(Id).ToArray(),
                vars = Read(() => Vars(potion.DynamicVars)),
            }).ToArray(),
            events = events.Select(Event).ToArray(),
            ancients = ancients.Select(ancient => new { id = Id(ancient), className = ancient.GetType().Name,
                isShared = ancient.IsShared, isAncient = true, vars = Read(() => Vars(ancient.DynamicVars)),
                possibleRelics = Read(() => ancient.AllPossibleOptions.Select(option => option.Relic?.Id.Entry).ToArray()) }).ToArray(),
            monsters = monsters.Select(monster => new { id = Id(monster), className = monster.GetType().Name,
                hpA0 = hpA0[Id(monster)], hpA10 = Read(() => new[] {monster.MinInitialHp, monster.MaxInitialHp}) }).ToArray(),
            encounters = encounters.Select(encounter => new { id = Id(encounter), className = encounter.GetType().Name,
                roomType = encounter.RoomType.ToString(), isWeak = encounter.IsWeak, shouldGiveRewards = encounter.ShouldGiveRewards,
                slots = encounter.Slots.ToArray(), monsters = encounter.AllPossibleMonsters.Select(Id).ToArray(),
                tags = encounter.Tags.Select(tag => tag.ToString()).ToArray() }).ToArray(),
            acts = ModelDb.Acts.Select(act => new { id = Id(act), events = act.AllEvents.Select(Id).ToArray(),
                ancients = act.AllAncients.Select(Id).ToArray(), weak = act.AllWeakEncounters.Select(Id).ToArray(),
                normal = act.AllRegularEncounters.Select(Id).ToArray(), elite = act.AllEliteEncounters.Select(Id).ToArray(),
                boss = act.AllBossEncounters.Select(Id).ToArray() }).ToArray(),
            sharedEvents = ModelDb.AllSharedEvents.Select(Id).ToArray(),
            sharedAncients = ModelDb.AllSharedAncients.Select(Id).ToArray(),
            cardPools = cardPools.Select(pool => new { id = Id(pool), entries = pool.AllCards.Select(Id).ToArray() }).ToArray(),
            relicPools = relicPools.Select(pool => new { id = Id(pool), entries = pool.AllRelics.Select(Id).ToArray() }).ToArray(),
            potionPools = potionPools.Select(pool => new { id = Id(pool), entries = pool.AllPotions.Select(Id).ToArray() }).ToArray(),
            registered = ModelDb.All.OrderBy(model => model.Id.ToString(), StringComparer.Ordinal).Select(model => new
                { id = model.Id.ToString(), className = model.GetType().Name, namespaceName = model.GetType().Namespace }).ToArray(),
        };
        var options = new JsonSerializerOptions { WriteIndented = true };
        File.WriteAllText(path, JsonSerializer.Serialize(result, options) + "\n");
        Godot.GD.Print("SLAY_HEADLESS_REGISTRY " + path);
    }
    private static object Event(EventModel evt) => new { id = Id(evt), className = evt.GetType().Name,
        isShared = evt.IsShared, isAncient = evt is AncientEventModel, vars = Read(() => Vars(evt.DynamicVars)) };
    private static object CardVariant(CardModel original, bool upgrade) => Read(() =>
    {
        var card = original.ToMutable();
        if (upgrade && card.MaxUpgradeLevel != 0) { card.UpgradeInternal(); card.FinalizeUpgradeInternal(); }
        return new { upgrade = card.CurrentUpgradeLevel, cost = card.EnergyCost.GetWithModifiers(CostModifiers.None),
            xCost = card.EnergyCost.CostsX, starCost = card.GetStarCostWithModifiers(), starXCost = card.HasStarCostX,
            keywords = card.Keywords.Select(keyword => keyword.ToString()).Order().ToArray(), vars = Vars(card.DynamicVars) };
    })!;
}
