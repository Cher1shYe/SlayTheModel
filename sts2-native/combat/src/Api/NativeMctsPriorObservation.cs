using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Cards;

namespace CombatSolver.Api;

public sealed partial class NativeMctsSimulationSession
{
    // Experimental, deliberately narrow adapter. Unknown mechanics never become zero features.
    public object ExportStarterPriorObservation(int initialHp, bool collectionV2 = false)
    {
        ThrowIfDisposed();
        if (currentDescription.PendingChoice || currentDescription.Terminal)
            throw new InvalidOperationException("Starter prior requires a completed play decision.");
        var simulator = (CombatPredictionSimulator)current.Simulator;
        var combat = (SimulatedCombatState)simulator.State.CombatState;
        var player = capturedRoot.PlayerIdentity;
        var pcs = simulator.State.GetPlayerCombatState(player);
        var hp = simulator.State.GetCreature(player.Creature);
        if (combat.RelicsOf(player).Any() || player.PotionSlots.Any(p => p != null)
            || combat.EffectivePowers().Any(p => p.Owner == player.Creature && p.Amount != 0)
            || pcs.Stars != 0 || pcs.ExhaustPile.Cards.Count != 0)
            throw new NotSupportedException("Starter prior forbids relics, potions, player powers, stars and exhaust.");
        object[] Cards(IReadOnlyList<CombatSolver.Engine.Common.PredictedCard> cards) => cards.Select(card =>
        {
            var c = card.Preview;
            bool admitted = c.Id.Entry is "STRIKE_IRONCLAD" or "DEFEND_IRONCLAD" or "BASH"
                || (collectionV2 && c.Id.Entry is ("IRON_WAVE" or "POMMEL_STRIKE" or "TWIN_STRIKE"));
            if (!admitted
                || c.CurrentUpgradeLevel != 0 || c.Enchantment != null || c.Affliction != null
                || c.EnergyCost.GetWithModifiers(CostModifiers.Local) != (c.Id.Entry == "BASH" ? 2 : 1))
                throw new NotSupportedException("Starter prior requires unmodified starter cards.");
            if (collectionV2)
                return (object)new { id = c.Id.Entry, stateKey = CardChoiceSupport.ChoiceCardKey(card),
                    cost = c.EnergyCost.GetWithModifiers(CostModifiers.Local),
                    baseValues = c.DynamicVars.ToDictionary(v => v.Key, v => v.Value.BaseValue) };
            return (object)new { id = c.Id.Entry, stateKey = CardChoiceSupport.ChoiceCardKey(card) };
        }).ToArray();
        var counters = simulator.History.GetCounters(player);
        var moves = combat.CurrentMonsterMoves();
        return new
        {
            version = collectionV2 ? "native-collection-observation-v2" : "native-starter-prior-v1", turn = current.Turn, initialHp,
            hp = hp.CurrentHp, maxHp = hp.MaxHp, block = hp.Block, energy = pcs.Energy,
            decisions = counters.FinishedPlays + current.Turn - 1,
            played = combat.GetCardsPlayedThisTurn(player.Creature),
            attacks = combat.GetAttacksPlayedThisTurn(player.Creature),
            unblockedHits = counters.UnblockedHitsReceived,
            hand = Cards(pcs.Hand.Cards), draw = Cards(pcs.DrawPile.Cards), discard = Cards(pcs.DiscardPile.Cards),
            enemies = combat.Enemies.Select(enemy =>
            {
                var state = simulator.State.GetCreature(enemy);
                var move = moves.SingleOrDefault(m => m.Owner == enemy);
                return new
                {
                    id = enemy.Monster!.Id.Entry, combatId = enemy.CombatId,
                    hp = state.CurrentHp, maxHp = state.MaxHp, block = state.Block,
                    move = move?.Move.Id, hits = move?.AttackHits.Select(h => h.BaseDamage).ToArray() ?? [],
                    powers = combat.EffectivePowers().Where(p => p.Owner == enemy && p.Amount != 0)
                        .Select(p => new { id = p.Id.Entry, amount = p.Amount }).ToArray()
                };
            }).ToArray(),
            actions = currentDescription.LegalActions
        };
    }
}
