using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Combat.History.Entries;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Nodes.Potions;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rooms;

namespace SlayTheModel.Headless;

// Only explicit, player-visible members belong here. In particular do not serialize
// model objects, saved run objects, RNGs, NextMove, or the order of non-hand piles.
public sealed partial class NativeGameBridge
{
    private static object[] PublicVars(DynamicVarSet variables) => variables
        .OrderBy(pair => pair.Key, StringComparer.Ordinal)
        .Select(pair => (object)new { name = pair.Key, value = pair.Value.BaseValue,
            enchantedValue = pair.Value.EnchantedValue }).ToArray();

    internal object DescribePublicCard(CardModel card, string pile, int? position = null)
    {
        var costs = NativeView.Items(NativeView.Get(card.EnergyCost, "_localModifiers")
            ?? throw new MissingMemberException("CardEnergyCost._localModifiers"))
            .Cast<LocalCostModifier>().Select(mod => new
            {
                amount = mod.Amount, absolute = mod.Type == LocalCostType.Absolute,
                expiration = (int)mod.Expiration, reduceOnly = mod.IsReduceOnly,
            }).ToArray();
        // Progress is printed on these cards and reconstructible from public history.
        int progress = card switch { Guilty guilty => guilty.CombatsSeen,
            Dowsing dowsing => dowsing.RoomsEntered, _ => 0 };
        return new
        {
            transportId = Identity(card), modelId = card.Id.ToString(), pile, position,
            upgrade = card.CurrentUpgradeLevel, maxUpgrade = card.MaxUpgradeLevel,
            type = card.Type.ToString(), rarity = card.Rarity.ToString(), target = card.TargetType.ToString(),
            costX = card.EnergyCost.CostsX, cost = card.EnergyCost.CostsX ? -1 : card.EnergyCost.GetWithModifiers(CostModifiers.All),
            baseCost = card.EnergyCost.GetWithModifiers(CostModifiers.None),
            localCost = card.EnergyCost.GetWithModifiers(CostModifiers.Local), costModifiers = costs,
            starCostX = card.HasStarCostX, starCost = card.GetStarCostWithModifiers(),
            keywords = card.Keywords.Select(value => value.ToString()).OrderBy(value => value, StringComparer.Ordinal).ToArray(),
            localKeywords = card.GetKeywordsWithSources(KeywordSources.Local).Select(value => value.ToString())
                .OrderBy(value => value, StringComparer.Ordinal).ToArray(),
            tags = card.Tags.Select(value => value.ToString()).OrderBy(value => value, StringComparer.Ordinal).ToArray(),
            replay = card.BaseReplayCount, enchantedReplay = card.GetEnchantedReplayCount(),
            retain = card.ShouldRetainThisTurn, exhaustOnNextPlay = card.ExhaustOnNextPlay,
            retainThisTurn = (bool)(NativeView.Get(card, "HasSingleTurnRetain") ?? throw new MissingMemberException("Card.HasSingleTurnRetain")),
            slyThisTurn = (bool)(NativeView.Get(card, "HasSingleTurnSly") ?? throw new MissingMemberException("Card.HasSingleTurnSly")),
            dampened = IsPubliclyDampened(card),
            progress, dynamicVars = PublicVars(card.DynamicVars),
            tinkerRider = card is MadScience science ? (int)science.TinkerTimeRider : 0,
            enchantment = card.Enchantment is { } enchantment ? new
            {
                modelId = enchantment.Id.ToString(), amount = enchantment.Amount,
                disabled = enchantment.Status.ToString() == "Disabled", dynamicVars = PublicVars(enchantment.DynamicVars),
                // This is a public sum of completed plays, not hidden engine state.
                extraDamage = enchantment.Id.Entry == "MOMENTUM"
                    ? Convert.ToInt32(NativeView.Get(enchantment, "ExtraDamage") ?? throw new MissingMemberException("Momentum.ExtraDamage")) : 0,
            } : null,
            affliction = card.Affliction is { } affliction ? new
                { modelId = affliction.Id.ToString(), amount = affliction.Amount } : null,
        };
    }

    private static bool IsPubliclyDampened(CardModel card)
    {
        if (card.CombatState is null) return false;
        // These cards were visibly downgraded when Dampen was applied. This
        // dictionary remembers that public event; it contains no draw order.
        foreach (var power in card.Owner.Creature.Powers.Where(power => power.Id.Entry == "DAMPEN_POWER"))
        {
            var data = NativeView.Get(power, "_internalData");
            if (NativeView.Get(data, "downgradedCardsToOldUpgradeLevels") is System.Collections.IDictionary downgraded
                && downgraded.Contains(card)) return true;
        }
        return false;
    }

    private object CapturePublicObservation()
    {
        var run = RunManager.Instance.DebugOnlyGetState()
            ?? throw new InvalidOperationException("Public observation requires an active run");
        var player = run.Players.First();
        // PlayerCombatState survives into rewards; its old energy/turn are no
        // longer a combat decision or a visible combat HUD at that point.
        var combat = CombatManager.Instance.IsInProgress ? player.PlayerCombatState : null;
        var state = combat is null ? null : CombatManager.Instance.DebugOnlyGetState();
        var cards = new List<object>();
        cards.AddRange(player.Deck.Cards.Select(card => DescribePublicCard(card, "deck")));
        if (combat is not null)
            foreach (var pile in combat.AllPiles)
            {
                string name = pile.Type.ToString().ToLowerInvariant();
                cards.AddRange(pile.Cards.Select((card, index) => DescribePublicCard(card, name,
                    name == "hand" ? index : null)));
            }
        var enemies = new List<object>();
        if (state is not null)
        {
            var visible = NativeView.Nodes(_host.GetTree().Root).OfType<NCreature>()
                .Where(NativeView.Visible).ToDictionary(node => node.Entity);
            foreach (var (enemy, index) in state.Enemies.Select((enemy, index) => (enemy, index)))
            {
                var intents = new List<object>();
                bool intentsVisible = visible.TryGetValue(enemy, out var node)
                    && NativeView.Visible(node.IntentContainer) && node.IntentContainer.Modulate.A > 0.99f;
                if (intentsVisible)
                    foreach (var icon in NativeView.Nodes(node!.IntentContainer).OfType<NIntent>().Where(NativeView.Visible))
                    {
                        if (NativeView.Get(icon, "_intent") is not AbstractIntent intent) continue;
                        var targets = run.Players.Select(p => p.Creature);
                        intents.Add(new { type = intent.IntentType.ToString(),
                            damage = intent is AttackIntent attack ? attack.GetSingleDamage(targets, enemy) : 0,
                            hits = intent is AttackIntent repeated ? repeated.Repeats : 0 });
                    }
                enemies.Add(new { transportId = Identity(enemy), modelId = enemy.ModelId.ToString(),
                    order = index, slotName = enemy.SlotName, hp = enemy.CurrentHp, maxHp = enemy.MaxHp,
                    block = enemy.Block, powers = PublicPowers(enemy), intentsVisible, intents,
                    alive = enemy.IsAlive, hittable = enemy.IsHittable,
                    reviving = enemy.IsDead && enemy.Powers.Any(power => power.Id.Entry == "ADAPTABLE_POWER") });
            }
        }
        var points = run.Map.GetAllMapPoints().Concat([run.Map.StartingMapPoint, run.Map.BossMapPoint])
            .Concat(run.Map.SecondBossMapPoint is { } second ? [second] : []).Distinct().ToList();
        var history = state is null ? null : CombatManager.Instance.History;
        var plays = history?.CardPlaysStarted.Where(entry => ReferenceEquals(entry.Actor, player.Creature)).ToArray() ?? [];
        var damage = history?.Entries.OfType<DamageReceivedEntry>()
            .Where(entry => ReferenceEquals(entry.Receiver, player.Creature)).ToArray() ?? [];
        var enteredRooms = run.MapPointHistory.SelectMany(act => act).Select(entry => entry.Rooms.FirstOrDefault()).ToArray();
        return new
        {
            version = 1,
            player = new { hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp, block = player.Creature.Block,
                gold = player.Gold, energy = combat?.Energy ?? 0, maxEnergy = combat?.MaxEnergy ?? 0,
                stars = combat?.Stars ?? 0, potionSlots = player.PotionSlots.Count,
                powers = PublicPowers(player.Creature) },
            run = new { act = run.CurrentActIndex, floor = run.TotalFloor, actFloor = run.ActFloor,
                ascension = run.AscensionLevel, currentAct = run.Act.Id.ToString(),
                boss = run.Act.BossEncounter.Id.ToString(), secondBoss = run.Act.SecondBossEncounter?.Id.ToString(),
                combatsFought = enteredRooms.Count(room => room?.RoomType is RoomType.Monster or RoomType.Elite or RoomType.Boss),
                elitesFought = enteredRooms.Count(room => room?.RoomType == RoomType.Elite),
                bossesFought = enteredRooms.Count(room => room?.RoomType == RoomType.Boss),
                cardShopRemovalsUsed = player.ExtraFields.CardShopRemovalsUsed,
                unknownMapPointsVisited = run.MapPointHistory.SelectMany(act => act).Count(entry => entry.MapPointType.ToString() == "Unknown") },
            combat = state is null ? null : new
            {
                turn = combat!.TurnNumber, round = state.RoundNumber,
                cardsPlayedTurn = plays.Count(entry => entry.HappenedThisTurn(state)),
                attacksPlayedTurn = plays.Count(entry => entry.HappenedThisTurn(state) && entry.CardPlay.Card.Type == CardType.Attack),
                skillsPlayedTurn = plays.Count(entry => entry.HappenedThisTurn(state) && entry.CardPlay.Card.Type == CardType.Skill),
                cardsPlayedCombat = plays.Length,
                cardsFinishedCombat = history!.CardPlaysFinished.Count(entry => ReferenceEquals(entry.Actor, player.Creature)),
                manualCardsPlayedTurn = history!.CardPlaysFinished.Count(entry => ReferenceEquals(entry.Actor, player.Creature)
                    && entry.HappenedThisTurn(state) && !entry.CardPlay.IsAutoPlay),
                cardsExhaustedTurn = history.Entries.OfType<CardExhaustedEntry>().Count(entry => entry.HappenedThisTurn(state) && ReferenceEquals(entry.Actor, player.Creature)),
                unblockedHitsCombat = damage.Count(entry => entry.Result.UnblockedDamage > 0),
                hpLostTurn = damage.Where(entry => entry.HappenedThisTurn(state)).Sum(entry => entry.Result.UnblockedDamage),
            },
            cards, enemies,
            knownTop = combat is null ? [] : NativePublicHistory.KnownTop(combat.DrawPile)
                .Select((card, index) => DescribePublicCard(card, "knownTop", index)).ToArray(),
            relics = player.Relics.Select((relic, index) => new
            {
                modelId = relic.Id.ToString(), position = index, wax = relic.IsWax, melted = relic.IsMelted,
                counterVisible = relic.ShowCounter, counter = relic.ShowCounter ? relic.DisplayAmount : 0,
                status = relic.Status.ToString(), dynamicVars = PublicVars(relic.DynamicVars),
            }).ToArray(),
            potions = player.PotionSlots.Select((potion, slot) => new
                { slot, modelId = potion?.Id.ToString(), queued = potion?.IsQueued ?? false,
                    disabledUntilRemoved = potion is not null && NativeView.Nodes(_host.GetTree().Root).OfType<NPotionHolder>()
                        .Any(holder => ReferenceEquals(holder.Potion?.Model, potion) && NativeView.Get(holder, "_disabledUntilPotionRemoved") is true) }).ToArray(),
            map = points.Select(point => new
            {
                row = point.coord.row, col = point.coord.col, type = point.PointType.ToString(),
                visited = run.VisitedMapCoords.Contains(point.coord), current = run.CurrentMapCoord == point.coord,
                children = point.Children.OrderBy(child => child.coord).Select(child => new { row = child.coord.row, col = child.coord.col }).ToArray(),
                quests = point.Quests.Select(quest => quest.Id.ToString()).OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            }).ToArray(),
        };
    }

    private static object[] PublicPowers(Creature creature) => creature.Powers.Where(power => power.IsVisible)
        .OrderBy(power => power.Id.ToString(), StringComparer.Ordinal).Select(power => (object)new
        { modelId = power.Id.ToString(), amount = power.Amount, displayAmount = power.DisplayAmount,
            dynamicVars = PublicVars(power.DynamicVars) }).ToArray();
}
