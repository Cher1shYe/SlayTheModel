using Godot;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.HoverTips;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes.Combat;
using MegaCrit.Sts2.Core.Runs;

namespace SlayTheModel.Headless;

public sealed partial class NativeGameBridge
{
    private static object[] Powers(Creature creature) => creature.Powers.Where(power => power.IsVisible).Select(power => (object)new
    {
        name = NativeView.Text(power.Title), enName = NativeView.English(power),
        amount = power.DisplayAmount, description = string.Join("；", power.HoverTips.OfType<HoverTip>()
            .Select(tip => NativeView.Text(tip.Description))),
    }).ToArray();

    private void CapturePlayer(HeadlessState frame)
    {
        var run = RunManager.Instance.DebugOnlyGetState();
        var player = run?.Players.FirstOrDefault();
        if (run is null || player is null) return;
        var combat = player.PlayerCombatState;
        frame.Player = new
        {
            name = NativeView.ModelName(player.Character), enName = NativeView.English(player.Character),
            hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp, block = player.Creature.Block,
            energy = combat?.Energy ?? 0, maxEnergy = combat?.MaxEnergy ?? 0, stars = combat?.Stars ?? 0,
            gold = player.Gold, ascension = run.AscensionLevel, act = run.CurrentActIndex + 1,
            orbCapacity = combat?.OrbQueue.Capacity ?? 0,
            floor = run.ActFloor, statuses = Powers(player.Creature),
        };
        if (combat is not null)
        {
            foreach (var pile in combat.AllPiles)
            {
                // Hidden draw order is deliberately erased even in this manual testing interface.
                frame.Entities.AddRange(PublicCardSet(pile.Cards, pile.Type.ToString().ToLowerInvariant()));
            }
        }
        frame.Entities.AddRange(PublicCardSet(player.Deck.Cards, "deck"));
        foreach (var relic in player.Relics)
            frame.Entities.Add(new HeadlessEntity
            {
                Id = Identity(relic), Kind = "relic", Name = NativeView.ModelName(relic), EnName = NativeView.English(relic),
                ModelId = relic.Id.ToString(), Description = NativeView.Text(relic.DynamicDescription),
                Count = relic.ShowCounter ? relic.DisplayAmount : null,
            });
        foreach (var potion in player.PotionSlots.Where(potion => potion is not null).Cast<PotionModel>())
            frame.Entities.Add(new HeadlessEntity
            {
                Id = Identity(potion), Kind = "potion", Name = NativeView.ModelName(potion), EnName = NativeView.English(potion),
                ModelId = potion.Id.ToString(), Description = NativeView.Text(potion.DynamicDescription),
            });
        if (combat is not null)
        {
            foreach (var node in NativeView.Nodes(_host.GetTree().Root).OfType<NCreature>().Where(NativeView.Visible))
            {
                var creature = node.Entity;
                if (ReferenceEquals(creature, player.Creature)) continue;
                string intent = "";
                if (NativeView.Visible(node.IntentContainer) && node.IntentContainer.Modulate.A > 0.99f)
                {
                    var descriptions = new List<string>();
                    foreach (var intentNode in NativeView.Nodes(node.IntentContainer).OfType<NIntent>().Where(NativeView.Visible))
                    {
                        if (NativeView.Get(intentNode, "_intent") is not AbstractIntent visibleIntent) continue;
                        var tip = visibleIntent.GetHoverTip(run.Players.Select(p => p.Creature), creature);
                        descriptions.Add(NativeView.Text(tip.Title) + " " + NativeView.Text(tip.Description));
                    }
                    intent = string.Join("；", descriptions);
                }
                frame.Entities.Add(new HeadlessEntity
                {
                    Id = Identity(creature), Kind = creature.IsEnemy ? "enemy" : "companion",
                    Name = NativeView.Text(creature.Name), EnName = creature.Monster is { } monster ? NativeView.English(monster) : "",
                    ModelId = creature.ModelId.ToString(), Hp = creature.CurrentHp, MaxHp = creature.MaxHp,
                    Block = creature.Block, Intent = intent, Statuses = Powers(creature),
                });
            }
            foreach (var orb in NativeView.Items(NativeView.Get(combat.OrbQueue, "Orbs")))
            {
                if (orb is not AbstractModel model) continue;
                frame.Entities.Add(new HeadlessEntity { Id = Identity(orb), Kind = "orb", Name = NativeView.ModelName(model),
                    EnName = NativeView.English(model), ModelId = model.Id.ToString(),
                    Description = string.Join("；", ((OrbModel)orb).HoverTips.OfType<HoverTip>()
                        .Select(tip => NativeView.Text(tip.Description))) });
            }
        }
    }

    private IEnumerable<HeadlessEntity> PublicCardSet(IEnumerable<CardModel> cards, string pile) => cards
        .Select(card => DescribeCard(card, pile))
        .OrderBy(card => card.ModelId, StringComparer.Ordinal)
        .ThenBy(card => card.Name, StringComparer.Ordinal)
        .ThenBy(card => card.Description, StringComparer.Ordinal)
        .ThenBy(card => card.Cost)
        .ThenBy(card => card.StarCost)
        .ThenBy(card => card.Id, StringComparer.Ordinal);
}
