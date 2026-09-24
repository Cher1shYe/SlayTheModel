using CombatSolver.Engine.Common;
using CombatSolver.Api;
using CombatSolver.Engine.InCombat.Simulation;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Cards;
using SlayTheModel.Sts2.Protocol;
using ProtocolSide = SlayTheModel.Sts2.Protocol.CombatSide;

namespace CombatSolver;

internal sealed partial class CombatBeamSolver
{
    internal NativeMctsChoiceFrame NativeMctsCaptureChoiceFrame(
        SimulationSnapshot preSelection, string triggerCardId, CardChoiceSpec spec)
    {
        if (spec.MinCount < 0 || spec.MaxCount < spec.MinCount)
            throw new PredictionUnsupportedException("Invalid predicted choice cardinality.");
        if (spec.Effect == PlanChoiceEffect.MoveToDrawTop && spec.MaxCount > 1)
            throw new PredictionUnsupportedException(
                "Ordered multi-card draw-top choice is not represented by the current subset enumerator.");
        var occurrences = new Dictionary<string, int>(StringComparer.Ordinal);
        var candidates = spec.Options.Select(card =>
        {
            string stateKey = CardChoiceSupport.ChoiceCardKey(card);
            int occurrence = occurrences.GetValueOrDefault(stateKey);
            occurrences[stateKey] = occurrence + 1;
            return new NativeMctsChoiceCandidate(
                NetCombatCard.FromModel(card.Original).CombatCardIndex,
                card.Preview.Id.ToString(), card.Preview.CurrentUpgradeLevel,
                stateKey, occurrence);
        }).ToArray();
        if (candidates.Select(candidate => candidate.CombatCardIndex).Distinct().Count() != candidates.Length)
            throw new PredictionUnsupportedException("Choice candidate instance IDs are ambiguous.");
        return new NativeMctsChoiceFrame(NativeMctsObserve(preSelection), triggerCardId,
            spec.Effect.ToString(), spec.SourcePile.ToString(),
            Math.Min(spec.MinCount, candidates.Length), Math.Min(spec.MaxCount, candidates.Length),
            spec.Effect == PlanChoiceEffect.MoveToDrawTop, candidates, []);
    }

    // Read only the simulator owned by this snapshot. Never inspect the live combat
    // state, the continuation stamp, branch forecasts or replay fingerprints here.
    internal CombatObservation NativeMctsObserve(SimulationSnapshot snapshot)
    {
        CombatPredictionSimulator simulator = (CombatPredictionSimulator)snapshot.Simulator;
        CombatPredictionState state = simulator.State;
        SimulatedCombatState combat = (SimulatedCombatState)state.CombatState;
        var players = state.Players.OrderBy(player => player.NetId).Select(player =>
        {
            SimPlayerCombatState predicted = state.GetPlayerCombatState(player);
            var piles = predicted.AllPiles.Select(pile => new CombatPileObservation(
                pile.Type.ToString(),
                pile.Type == PileType.Draw ? Array.Empty<CombatCardObservation>() :
                pile.Cards.Select(card =>
                {
                    var preview = card.Preview;
                    return new CombatCardObservation(
                        NetCombatCard.FromModel(card.Original).CombatCardIndex,
                        preview.Id.ToString(),
                        preview.EnergyCost.CostsX ? null : preview.EnergyCost.GetWithModifiers(CostModifiers.Local),
                        preview.Affliction?.Id.ToString(), preview.Affliction?.Amount ?? 0,
                        preview.GetKeywordsWithSources(KeywordSources.Local)
                            .Select(keyword => keyword.ToString()).Order(StringComparer.Ordinal).ToArray());
                }).ToArray())).ToArray();
            var potions = Enumerable.Range(0, combat.CapturedPotionSlotCount(player))
                .Select(slot => combat.GetPotionAtSlot(player, slot))
                .Where(potion => potion != null)
                .Select((potion, slot) => new PotionObservation(slot, potion!.Id.ToString())).ToArray();
            return new CombatPlayerObservation(player.NetId, player.Character.Id.ToString(),
                predicted.Energy, predicted.Stars, combat.GetPlayerTurnNumber(player),
                predicted.Phase.ToString(), piles,
                combat.RelicsOf(player).Select(relic => new RelicObservation(relic.Id.ToString())).ToArray(),
                potions,
                predicted.OrbQueue.Orbs.Select(orb => new OrbSnapshot(orb.Id.ToString(),
                    checked((int)orb.PassiveVal), checked((int)orb.EvokeVal))).ToArray());
        }).ToArray();
        var creatures = state.Creatures.OrderBy(creature => creature.CombatId).Select(creature =>
        {
            SimCreatureState predicted = state.GetCreature(creature);
            ulong? owner = state.Players.SingleOrDefault(player => ReferenceEquals(player.Creature, creature))?.NetId;
            return new CombatCreatureObservation(creature.CombatId
                    ?? throw new InvalidDataException("Predicted creature has no combat ID."),
                owner, owner.HasValue ? null : creature.Monster?.Id.ToString(),
                predicted.CurrentHp, predicted.MaxHp, predicted.Block,
                combat.EffectivePowers().Where(power => ReferenceEquals(power.Owner, creature))
                    .Select(power => new ModelAmountSnapshot(power.Id.ToString(), power.Amount)).ToArray(),
                owner is null && predicted.CurrentHp > 0 ? combat.GetPredictedMoveId(creature) : null);
        }).ToArray();
        ProtocolSide side = combat.CurrentSide switch
        {
            MegaCrit.Sts2.Core.Combat.CombatSide.Player => ProtocolSide.Player,
            MegaCrit.Sts2.Core.Combat.CombatSide.Enemy => ProtocolSide.Enemy,
            _ => ProtocolSide.Unknown,
        };
        var observation = new CombatObservation(CombatObservation.CurrentSchemaVersion,
            combat.RoundNumber, side, players, creatures);
        observation.Validate();
        return observation;
    }
}
