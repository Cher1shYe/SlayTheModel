using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Monsters;
using MegaCrit.Sts2.Core.Models.Orbs;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.ValueProps;
using CombatSolver.Engine.Common;
using CombatSolver.Engine.InCombat.Mirrors.Hooks.Card;
using CombatSolver.Engine.InCombat.Mirrors.Hooks.Resources;
using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver;

internal static class PersistentPowerSupport
{
    public static int ConsumeModifiedHandDraw(
        SimulatedCombatState combat,
        Player player,
        int baseDraw)
    {
        DrawCardsNextTurnPower? delayedDraw = combat.GetPower<DrawCardsNextTurnPower>(player.Creature);
        int drawNotYetSnapshotted = delayedDraw is { Amount: > 0, AmountOnTurnStart: 0 }
            ? delayedDraw.Amount
            : 0;
        int result = GetModifiedHandDraw(
            combat,
            player,
            baseDraw + combat.ConsumeDrawNextTurn(player) + drawNotYetSnapshotted);
        combat.CompleteRelicHandDraw(player);
        return result;
    }

    public static int GetModifiedHandDraw(
        SimulatedCombatState combat,
        Player player,
        int baseDraw)
    {
        decimal result = Hook.ModifyHandDraw(combat, player, baseDraw, out _);
        result = AdjustTurnBasedRelicHandDraw(combat, player, result);
        return Math.Max(0, (int)result);
    }

    public static int GetModifiedMaxEnergy(SimulatedCombatState combat, Player player)
    {
        decimal result = Hook.ModifyMaxEnergy(combat, player, player.MaxEnergy);
        result = AdjustTurnBasedRelicMaxEnergy(combat, player, result);
        return Math.Max(0, (int)result);
    }

    private static decimal AdjustTurnBasedRelicHandDraw(
        SimulatedCombatState combat,
        Player player,
        decimal result)
    {
        int rootTurn = combat.GetRootPlayerTurnNumber(player);
        int simulatedTurn = combat.GetPlayerTurnNumber(player);
        foreach (RelicModel relic in combat.RelicsOf(player).Where(static relic => !relic.IsMelted))
        {
            result -= GetTurnBasedHandDrawContribution(relic, combat, rootTurn);
            result -= SimulatedCombatState.GetLiveStatefulRelicHandDrawContribution(
                relic,
                player,
                rootTurn);
            result += GetTurnBasedHandDrawContribution(relic, combat, simulatedTurn);
            result += combat.GetStatefulRelicHandDrawContribution(relic, player, simulatedTurn);
        }
        return result;
    }

    private static decimal GetTurnBasedHandDrawContribution(
        RelicModel relic,
        SimulatedCombatState combat,
        int turn)
        => relic switch
        {
            BagOfPreparation when turn <= 1 => relic.DynamicVars.Cards.BaseValue,
            BigMushroom when turn == 1 => -relic.DynamicVars.Cards.BaseValue,
            BoomingConch when turn <= 1
                && combat.CurrentRoomType == RoomType.Elite
                => relic.DynamicVars.Cards.BaseValue,
            RingOfTheDrake when turn <= relic.DynamicVars["Turns"].IntValue
                => relic.DynamicVars.Cards.BaseValue,
            RingOfTheSnake when turn <= 1 => relic.DynamicVars.Cards.BaseValue,
            _ => 0m,
        };

    private static decimal AdjustTurnBasedRelicMaxEnergy(
        SimulatedCombatState combat,
        Player player,
        decimal result)
    {
        int rootTurn = combat.GetRootPlayerTurnNumber(player);
        int simulatedTurn = combat.GetPlayerTurnNumber(player);
        if (rootTurn == simulatedTurn)
            return result;

        foreach (RelicModel relic in combat.RelicsOf(player).Where(static relic => !relic.IsMelted))
        {
            result -= GetTurnBasedMaxEnergyContribution(relic, rootTurn);
            result += GetTurnBasedMaxEnergyContribution(relic, simulatedTurn);
        }
        return result;
    }

    private static decimal GetTurnBasedMaxEnergyContribution(RelicModel relic, int turn)
        => relic switch
        {
            Bread when turn != 1 => relic.DynamicVars["GainEnergy"].BaseValue,
            PaelsFlesh when turn >= 3 => relic.DynamicVars.Energy.BaseValue,
            _ => 0m,
        };

    public static bool TriggerAfterEnergyReset(
        CombatPredictionSimulator simulator,
        SimulatedCombatState combat,
        Player player)
    {
        Creature owner = player.Creature;
        var context = new AfterEnergyResetMirrorContext { Simulator = simulator, Player = player };

        // Channel order affects the queue and the effects evoked when it is full.
        foreach (PowerModel power in combat.EffectivePowers())
        {
            // 层数为零的能力在原版里每一个重写都是空转：加零点星、抽零张、扣零点能量。
            // 这道门保持原来的判据，顺带让没登记的第三方能力不会为了一次空转记风险。
            if (power.Owner != owner || power.Amount <= 0)
                continue;
            AfterEnergyResetMirrors.Invoke(power, context);
            if (simulator.HasPendingChoice)
                return false;
        }
        return !simulator.HasPendingChoice;
    }

    public static bool TriggerAfterSideTurnStart(
        CombatPredictionSimulator simulator,
        SimulatedCombatState combat,
        CombatSide side,
        IReadOnlyList<Creature> participants,
        bool isExtraTurn = false)
    {
        foreach (Creature owner in participants)
        {
            if (!TriggerOwnerAfterSideTurnStart(simulator, combat, owner))
                return false;
        }

        if (side == CombatSide.Player && !isExtraTurn)
            return TriggerRampart(simulator, combat);
        return !simulator.HasPendingChoice;
    }

    public static void TriggerRitual(SimulatedCombatState combat, Creature owner)
    {
        int amount = combat.GetAmount<RitualPower>(owner);
        if (amount <= 0 || combat.ConsumeRitualApplicationDelay(owner))
            return;
        combat.Apply<StrengthPower>(owner, amount, owner);
    }

    private static bool TriggerOwnerAfterSideTurnStart(
        CombatPredictionSimulator simulator,
        SimulatedCombatState combat,
        Creature owner)
    {
        // Native Hook dispatch follows the captured power insertion order. Snapshot
        // listeners before applying effects: newly added powers must not join this pass.
        foreach (PowerModel power in combat.EffectivePowers().Where(p => p.Owner == owner).ToArray())
        {
            int biasedCognition = power is BiasedCognitionPower ? power.Amount : 0;
            if (biasedCognition > 0)
                combat.Apply<FocusPower>(owner, -biasedCognition, owner);

            int coolant = power is CoolantPower ? power.Amount : 0;
            if (coolant > 0 && owner.Player is { } coolantPlayer)
            {
                int distinctOrbs = simulator.State.GetPlayerCombatState(coolantPlayer).OrbQueue.Orbs
                    .Select(static orb => orb.Id)
                    .Distinct()
                    .Count();
                simulator.GainBlock(owner, distinctOrbs * coolant, ValueProp.Unpowered);
                if (simulator.HasPendingChoice)
                    return false;
            }

            int demonForm = power is DemonFormPower ? power.Amount : 0;
            if (demonForm > 0)
                combat.Apply<StrengthPower>(owner, demonForm, owner);

            FeralPower? feral = power as FeralPower;
            if (feral is { Amount: > 0 })
                simulator.StateStore.Get(feral, () => new FeralPredictionState(feral)).ZeroCostAttacksPlayed = 0;

            int furnace = power is FurnacePower ? power.Amount : 0;
            if (furnace > 0 && owner.Player is { } furnacePlayer)
            {
                Forge(simulator, furnacePlayer, furnace);
                if (simulator.HasPendingChoice)
                    return false;
            }

            int neurosurge = power is NeurosurgePower ? power.Amount : 0;
            if (neurosurge > 0)
                combat.Apply<DoomPower>(owner, neurosurge, owner);

            int noxiousFumes = power is NoxiousFumesPower ? power.Amount : 0;
            if (noxiousFumes > 0)
            {
                foreach (Creature opponent in combat.GetOpponentsOf(owner))
                {
                    if (simulator.State.IsHittable(opponent))
                        combat.Apply<PoisonPower>(opponent, noxiousFumes, owner);
                }
            }

            int prepTime = power is PrepTimePower ? power.Amount : 0;
            if (prepTime > 0)
                combat.Apply<VigorPower>(owner, prepTime, owner);

            int reflect = power is ReflectPower ? power.Amount : 0;
            if (reflect > 0)
                combat.SetAmount<ReflectPower>(owner, reflect - 1);

            int shadowStep = power is ShadowStepPower ? power.Amount : 0;
            if (shadowStep > 0)
            {
                combat.Apply<DoubleDamagePower>(owner, shadowStep, owner);
                combat.SetAmount<ShadowStepPower>(owner, 0);
            }

            int wraithForm = power is WraithFormPower ? power.Amount : 0;
            if (wraithForm > 0)
                combat.Apply<DexterityPower>(owner, -wraithForm, owner);

            int clarity = power is ClarityPower ? power.Amount : 0;
            if (clarity > 0)
                combat.SetAmount<ClarityPower>(owner, clarity - 1);
        }
        return !simulator.HasPendingChoice;
    }

    private static bool TriggerRampart(
        CombatPredictionSimulator simulator,
        SimulatedCombatState combat)
    {
        foreach (RampartPower rampart in combat.EffectivePowers().OfType<RampartPower>().ToArray())
        {
            // A start-turn attack can remove the shield before this hook phase.
            // Deferred power cleanup must not keep its dead owner's aura active.
            if (rampart.Amount <= 0 || !combat.ContainsCreature(rampart.Owner)
                || !simulator.State.GetCreature(rampart.Owner).IsAlive)
                continue;
            foreach (Creature enemy in combat.Enemies)
            {
                if (enemy.Monster is TurretOperator && simulator.State.GetCreature(enemy).IsAlive)
                {
                    simulator.GainBlock(enemy, rampart.Amount, ValueProp.Unpowered);
                    if (simulator.HasPendingChoice)
                        return false;
                }
            }
        }
        return true;
    }

    public static void Forge(
        CombatPredictionSimulator simulator,
        Player player,
        int amount)
    {
        if (simulator.HasPendingChoice)
            return;

        SimPlayerCombatState state = simulator.State.GetPlayerCombatState(player);
        bool hasUnexhaustedBlade = state.AllCards.Any(card =>
            card.Preview is SovereignBlade
            && !card.Preview.IsDupe
            && !state.ExhaustPile.Cards.Contains(card));
        if (!hasUnexhaustedBlade)
        {
            PredictedCard created = PredictedCard.Create(CanonicalModels.Card<SovereignBlade>(), player);
            ((SovereignBlade)created.MutablePreview).CreatedThroughForge = true;
            simulator.AddGeneratedCardToCombat(
                created,
                PileType.Hand,
                player,
                CardPilePosition.Bottom,
                CardGenerationResultKind.Fixed);
            if (simulator.HasPendingChoice)
                return;
        }
        foreach (PredictedCard card in state.AllCards)
        {
            if (card.Preview is not SovereignBlade preview || preview.IsDupe)
                continue;
            ((SovereignBlade)card.MutablePreview).AddDamage(amount);
        }
    }
}
