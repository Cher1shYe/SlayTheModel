using CombatSolver.Engine.InCombat.Simulation;
using CombatSolver.Engine.Common;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using HarmonyLib;

namespace CombatSolver.Api;

/// <summary>Stable base features; calculated variables' display caches can be stale after downgrade.</summary>
public static class NativeGenericCardFeatures
{
    private static readonly Func<CalculatedVar,DynamicVar> BaseVariable =
        AccessTools.Method(typeof(CalculatedVar),"GetBaseVar").CreateDelegate<Func<CalculatedVar,DynamicVar>>();

    public static Dictionary<string,decimal> Variables(CardModel card) => card.DynamicVars.ToDictionary(
        v=>v.Key, v=>v.Value is CalculatedVar calculated ? BaseVariable(calculated).BaseValue : v.Value.BaseValue);
}

public sealed partial class NativeMctsSimulationSession
{
    // Pure branch projection. No collector/live combat reads are permitted here.
    // DTO fields follow native serialization; all mutable values come from this branch.
    public object ExportGenericValueObservation(int initialHp, int decisions)
    {
        ThrowIfDisposed();
        if (currentDescription.PendingChoice || currentDescription.Terminal)
            throw new InvalidOperationException("Value projection requires a completed nonterminal branch");
        var simulator = (CombatPredictionSimulator)current.Simulator;
        var combat = (SimulatedCombatState)simulator.State.CombatState;
        var player = capturedRoot.PlayerIdentity;
        var pcs = simulator.State.GetPlayerCombatState(player);
        if (combat.GetOsty(player) != null || pcs.OrbQueue.Orbs.Count != 0)
            throw new NotSupportedException("Generic value projection does not yet cover companions/orbs");
        object Card(PredictedCard predicted) {
            var c=predicted.Preview;
            return new {
            model = c.Id.Entry, upgrade = c.CurrentUpgradeLevel,
            cost = c.EnergyCost.GetWithModifiers(CostModifiers.Local), type = c.Type.ToString(), target = simulator.GetTargetType(predicted).ToString(),
            keywords = predicted.GetKeywords(simulator.State).Select(k => k.ToString()).Order().ToArray(),
            enchantment = c.Enchantment?.Id.Entry, affliction = c.Affliction?.Id.Entry,
            variables = NativeGenericCardFeatures.Variables(c)
            };
        }
        var all = pcs.AllPiles.SelectMany(p => p.Cards).ToArray();
        var indices = all.Select((c,i) => (c,i)).ToDictionary(x => x.c, x => x.i);
        object Creature(Creature c) {
            var state = simulator.State.GetCreature(c);
            return new { CombatId=c.CombatId, PlayerId=c==player.Creature ? (ulong?)1 : null,
                MonsterId=c.Monster?.Id.ToString(), CurrentHp=state.CurrentHp, MaxHp=state.MaxHp, Block=state.Block,
                Powers=combat.EffectivePowers().Where(p => p.Owner==c && p.Amount!=0)
                    .Select(p => new { ModelId=p.Id.ToString(), Amount=p.Amount }).ToArray() };
        }
        var moves = combat.CurrentMonsterMoves();
        var intents = combat.Enemies.Select(e => {
            var move = moves.Single(m => m.Owner==e);
            // Intent type identity is immutable; mutable damage comes only from the
            // branch forecast and mirrored modifiers, never AttackIntent delegates.
            if (move.Move.Intents.Count(i => i is AttackIntent)>1)
                throw new NotSupportedException("Multiple attack intent groups require explicit hit partitioning");
            int damage=move.AttackHits.Sum(h => CorePowerSupport.AdjustForecastAttack(simulator,combat,e,
                player.Creature,combat.AdjustMonsterMoveDamage(e,move.Move.Id,h.BaseDamage)));
            return new { target=e.CombatId, intents=move.Move.Intents.Select(i => new {
                kind=i.GetType().Name, damage=i is AttackIntent ? damage : 0 }).ToArray() };
        }).ToArray();
        int? SerializedEnergyCost(PredictedCard card) {
            int cost=card.GetEnergyCostValueWithModifiers(simulator);
            return cost==card.Preview.EnergyCost.Canonical ? null : cost;
        }
        var piles=pcs.AllPiles.Select(p => new { PileType=p.Type.ToString(), Cards=p.Cards.Select(c => new {
            CombatCardIndex=indices[c], ModelId=c.Preview.Id.ToString(), EnergyCost=SerializedEnergyCost(c),
            AfflictionId=c.Preview.Affliction?.Id.ToString(), AfflictionCount=c.Preview.Affliction?.Amount ?? 0,
            Keywords=c.GetKeywords(simulator.State).Select(k=>k.ToString()).Order().ToArray(), UpgradeLevel=(int?)null,
            EnchantmentId=(string?)null, EnchantmentAmount=(int?)null, Display=(object?)null }).ToArray() }).ToArray();
        return new {
            version="native-generic-observation-v1",initialHp,decisions,
            observation=new { SchemaVersion=5, RoundNumber=current.Turn, CurrentSide=0,
                Players=new[] { new { PlayerId=1UL, CharacterId=player.Character.Id.ToString(), Energy=pcs.Energy,
                    Stars=pcs.Stars, TurnNumber=current.Turn, Phase="Play", Piles=piles,
                    Relics=combat.RelicsOf(player).Select(r=>new { ModelId=r.Id.ToString() }).ToArray(),
                    Potions=Enumerable.Range(0,genericPotionSlots).Select(i=>(i,p:combat.GetPotionAtSlot(player,i)))
                        .Where(x=>x.p!=null).Select(x=>new { SlotIndex=x.i, ModelId=x.p!.Id.ToString() }).ToArray(),
                    Orbs=Array.Empty<object>(), Gold=combat.GetPlayerGold(player), OrbCapacity=(int?)null } },
                Creatures=new[]{player.Creature}.Concat(combat.Enemies).OrderBy(c=>c.CombatId).Select(Creature).ToArray(),
                EnemyIntents=Array.Empty<object>(),Companions=Array.Empty<object>(),ActiveChoice=(object?)null,PendingManualActions=Array.Empty<object>() },
            cards=all.Select(c=>new {index=indices[c],data=Card(c)}).ToArray(),intents,
            choice=(object?)null,actions=Array.Empty<object>()
        };
    }
}
