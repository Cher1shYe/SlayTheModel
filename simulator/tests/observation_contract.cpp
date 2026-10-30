#include <iostream>
#include <utility>

#include "sts2/observe.h"

using namespace sts2;

namespace {
int checks = 0;
int failures = 0;

void check(bool ok, const char *name) {
    ++checks;
    if (!ok) {
        ++failures;
        std::cout << "FAIL " << name << '\n';
    }
}

BattleContext combat() {
    Card deck[10];
    for (int i = 0; i < 10; ++i)
        deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    BattleContext b;
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 123u, deck, 10, 0, 80, 80);
    return b;
}

#define CHECK_BATTLE(field, value) do { \
    BattleContext a = combat(), b = a; \
    b.field = (value); \
    check(public_combat_observation(a) != public_combat_observation(b), #field); \
} while (false)

#define CHECK_RUN(field, value) do { \
    RunContext a; a.init(123u, 0); RunContext b = a; \
    b.field = (value); \
    check(public_observation(a) != public_observation(b), #field); \
} while (false)
}  // namespace

int main() {
    CHECK_BATTLE(player.toricToughnessBlock, 5);
    CHECK_BATTLE(player.surroundedFacingRight, false);
    CHECK_BATTLE(player.tookUnblockedDamageThisTurn, true);
    CHECK_BATTLE(player.tookUnblockedAttackDamageThisCombat, true);
    CHECK_BATTLE(exhaustedThisTurn, 2);
    CHECK_BATTLE(hpLostThisTurn, 4);
    CHECK_BATTLE(nextTurnEnergy, 2);
    CHECK_BATTLE(nextTurnDraw, 2);
    CHECK_BATTLE(attackSkillPlaysThisTurn, 2);
    CHECK_BATTLE(blockCardPlaysThisTurn, 2);
    CHECK_BATTLE(skillsLocked, true);
    CHECK_BATTLE(recoveredStolenGold, 20);
    CHECK_BATTLE(monsters[0].offBalance, true);
    CHECK_BATTLE(monsters[0].stunned, true);
    CHECK_BATTLE(monsters[0].slowCardsThisTurn, 3);
    CHECK_BATTLE(monsters[0].tempStrengthLoss, 4);
    CHECK_BATTLE(monsters[0].nemesisIntangible, true);
    CHECK_BATTLE(monsters[0].combatEndBlocker, true);
    CHECK_BATTLE(monsters[0].skittishTriggeredThisTurn, true);
    CHECK_BATTLE(monsters[0].stolenGold, 20);
    CHECK_BATTLE(monsters[0].steamEruptionDamage, 7);
    {
        BattleContext a = combat(), b = a;
        a.monsters[0].grappleCount = b.monsters[0].grappleCount = 1;
        b.monsters[0].grappleAmounts[0] = 7;
        check(public_combat_observation(a) != public_combat_observation(b), "grapple instance amount");
    }
    CHECK_BATTLE(hand[0].bonusDamage, 7);
    CHECK_BATTLE(hand[0].etherealThisCombat, true);
    CHECK_BATTLE(hand[0].retainThisCombat, true);
    CHECK_BATTLE(hand[0].combatCostCap, 1);
    CHECK_BATTLE(hand[0].guiltyCombatsSeen, 3);
    {
        BattleContext a = combat(), b = a;
        a.theftCount = b.theftCount = 1;
        a.theftCards[0] = b.theftCards[0] = a.hand[0];
        b.theftCards[0].enchantment = EnchantmentId::SOWN;
        b.theftCards[0].enchantmentAmount = 1;
        check(public_combat_observation(a) != public_combat_observation(b), "stolen card enchantment");
        a.theftCards[0] = b.theftCards[0];
        b.theftOwners[0] = -1;
        check(public_combat_observation(a) != public_combat_observation(b), "stolen card thief");
        a.theftOwners[0] = -1;
        b.theftReturned[0] = true;
        check(public_combat_observation(a) != public_combat_observation(b), "stolen card returned");
    }
    CHECK_BATTLE(hand[0].enchantment, EnchantmentId::SOWN);
    CHECK_BATTLE(hand[0].enchantmentAmount, 8);
    CHECK_BATTLE(hand[0].enchantmentDisabled, true);
    CHECK_BATTLE(draw[0].enchantment, EnchantmentId::SOWN);
    {
        BattleContext a = combat(), b = a;
        a.activePlay.active = b.activePlay.active = true;
        a.activePlay.playCount = b.activePlay.playCount = 3;
        b.activePlay.nextPlay = 2;
        check(public_combat_observation(a) != public_combat_observation(b), "active replay progress");
        a.activePlay.nextPlay = b.activePlay.nextPlay;
        a.activePlay.swiftAwaitingDraw = true;
        check(public_combat_observation(a) != public_combat_observation(b), "swift suspended draw");
    }
    {
        BattleContext a = combat(), b = a;
        a.toricCount = b.toricCount = 1;
        b.toricBlock[0] = 5;
        check(public_combat_observation(a) != public_combat_observation(b), "toric instance block");
        a.toricBlock[0] = b.toricBlock[0];
        b.toricTurns[0] = 1;
        check(public_combat_observation(a) != public_combat_observation(b), "toric instance turns");
    }
    {
        BattleContext a = combat(), b = a;
        a.automationCount = b.automationCount = 9;
        a.automationLeft[8] = 10;
        b.automationLeft[8] = 1;
        check(public_combat_observation(a) != public_combat_observation(b), "ninth automation instance");
    }
    {
        BattleContext a = combat(), b = a;
        a.rollingCount = b.rollingCount = 1;
        b.rollingDamage[0] = 8;
        check(public_combat_observation(a) != public_combat_observation(b), "rolling damage");
        a.panacheCount = b.panacheCount = 1;
        a.rollingDamage[0] = b.rollingDamage[0];
        b.panacheDamage[0] = 10;
        check(public_combat_observation(a) != public_combat_observation(b), "panache damage");
        a.panacheDamage[0] = b.panacheDamage[0];
        b.panacheLeft[0] = 2;
        check(public_combat_observation(a) != public_combat_observation(b), "panache remaining");
        a.panacheLeft[0] = b.panacheLeft[0];
        b.panachePrimed[0] = true;
        check(public_combat_observation(a) != public_combat_observation(b), "panache primed");
    }
    {
        BattleContext a = combat(), b = a;
        a.pending.count = b.pending.count = 2;
        a.pending.cards[0] = b.pending.cards[0] = make_card(CardId::RAMPAGE, false, 100);
        a.pending.cards[1] = b.pending.cards[1] = make_card(CardId::RAMPAGE, false, 101);
        b.pending.cards[1].bonusDamage = 5;
        check(public_combat_observation(a) != public_combat_observation(b), "offered instance damage");
        Action first; first.type = ActionType::CHOOSE; first.uid = 100;
        Action second = first; second.uid = 101;
        check(combat_action_features(a, first) == combat_action_features(a, second), "equivalent choices");
        check(combat_action_features(b, first) != combat_action_features(b, second), "choice instance attributes");
        a.pending.cards[1].bonusDamage = 5;
        std::swap(b.pending.cards[0], b.pending.cards[1]);
        check(public_combat_observation(a) == public_combat_observation(b), "hidden choice pile order");
    }
    {
        BattleContext a = combat(), b = a;
        a.drawCount = b.drawCount = 18;
        for (int i = 0; i < 18; ++i)
            a.draw[i] = b.draw[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        a.draw[1] = b.draw[1] = make_card(CardId::DEFEND_IRONCLAD, false, 40);
        std::swap(b.draw[0], b.draw[1]);
        a.knownTopCount = b.knownTopCount = 0;
        check(public_combat_observation(a) == public_combat_observation(b), "hidden draw order");
        a.knownTopCount = b.knownTopCount = 18;
        check(public_combat_observation(a) != public_combat_observation(b), "known top beyond 16");
        a.discardCount = b.discardCount = 2;
        a.discard[0] = b.discard[0] = make_card(CardId::STRIKE_IRONCLAD, false, 41);
        a.discard[1] = b.discard[1] = make_card(CardId::DEFEND_IRONCLAD, false, 42);
        std::swap(b.discard[0], b.discard[1]);
        b.draw[0] = a.draw[0]; b.draw[1] = a.draw[1];
        check(public_combat_observation(a) == public_combat_observation(b), "hidden discard order");
    }
    {
        BattleContext a = combat(), b = a;
        b.pending.op = ChoiceOp::DISCARD_ANY;
        Action action; action.type = ActionType::CHOOSE;
        check(combat_action_features(a, action) != combat_action_features(b, action), "discard-any action encoding");
    }
    CHECK_RUN(rewardIsBoss, true);
    CHECK_RUN(potionSlots, 4);
    CHECK_RUN(teaSetPending, true);
    CHECK_RUN(cardsAdded, 5);
    CHECK_RUN(nextCombatEnergy, 2);
    CHECK_RUN(nextCombatUpgradeHand, true);
    CHECK_RUN(nextCombatDazed, 2);
    CHECK_RUN(emberTeaCombats, 2);
    CHECK_RUN(furCoatCombats, 2);
    CHECK_RUN(toyBoxCombats, 2);
    CHECK_RUN(wongoCombats, 2);
    CHECK_RUN(swordOfStoneWins, 2);
    CHECK_RUN(paelsWingSkips, 2);
    CHECK_RUN(silverCrucibleUses, 2);
    CHECK_RUN(mawBankPurchased, true);
    CHECK_RUN(treasureSkipped, true);
    CHECK_RUN(truncated, true);
    CHECK_RUN(eventCardSelection, 2);
    CHECK_RUN(deck[0].guiltyCombatsSeen, 3);
    CHECK_RUN(deck[0].enchantment, EnchantmentId::SOWN);
    CHECK_RUN(deck[0].enchantmentAmount, 1);
    CHECK_RUN(bossEncounter, static_cast<int>(Encounter::SETUP_THE_KIN_BOSS));
    CHECK_RUN(secondBossEncounter, static_cast<int>(Encounter::SETUP_VANTOM_BOSS));
    {
        RunContext a; a.init(123u, 0); RunContext b = a;
        a.potionCount = b.potionCount = 2;
        a.potions[0] = b.potions[1] = static_cast<int>(PotionId::BLOOD_POTION);
        a.potions[1] = b.potions[0] = static_cast<int>(PotionId::FIRE_POTION);
        check(public_observation(a) != public_observation(b), "potion slot order");
    }
    {
        RunContext a; a.init(123u, 0); RunContext b = a;
        a.deck[0].upgraded = true;
        b.deck[1].upgraded = true;
        check(public_observation(a) != public_observation(b), "deck upgrade slot");
    }
    {
        RunContext a; a.init(123u, 0); RunContext b = a;
        a.screen = b.screen = RunScreen::COMBAT;
        a.inBattle = b.inBattle = true;
        a.battle.gold = 99; b.battle.gold = 0;
        check(public_observation(a) != public_observation(b), "live battle gold");
    }
    {
        RunContext a; a.init(123u, 0); RunContext b = a;
        a.screen = b.screen = RunScreen::REWARDS;
        a.pendingCardReward = b.pendingCardReward = true;
        a.offeredCount = b.offeredCount = 1;
        a.offered[0] = make_card(CardId::STRIKE_IRONCLAD, false, 200);
        b.offered[0] = make_card(CardId::DEFEND_IRONCLAD, false, 201);
        check(public_observation(a) == public_observation(b), "unopened card reward hidden");
        a.screen = b.screen = RunScreen::CARD_REWARD;
        a.rewardReturnToRewards = b.rewardReturnToRewards = true;
        check(public_observation(a) != public_observation(b), "opened card reward visible");
        a.screen = b.screen = RunScreen::REWARDS;
        b.pendingGoldReward = 20;
        check(public_observation(a) != public_observation(b), "gold reward visible");
        a.pendingGoldReward = b.pendingGoldReward;
        b.pendingRecoveredGold = 20;
        check(public_observation(a) != public_observation(b), "recovered gold reward visible");
        a.pendingRecoveredGold = b.pendingRecoveredGold;
        b.pendingPotionReward = static_cast<int>(PotionId::FIRE_POTION);
        check(public_observation(a) != public_observation(b), "potion reward visible");
        a.pendingPotionReward = b.pendingPotionReward;
        a.pendingRelicCount = b.pendingRelicCount = 1;
        a.pendingRelics[0] = b.pendingRelics[0] = static_cast<int>(RelicId::ANCHOR);
        b.pendingRelicClaimed[0] = true;
        check(public_observation(a) != public_observation(b), "relic reward claimed state visible");
        a.pendingRelicClaimed[0] = true;
        b.pendingReturnToEvent = true;
        check(public_observation(a) != public_observation(b), "reward event return visible");
        a.pendingReturnToEvent = b.pendingReturnToEvent;
        a.pendingPotionCount = b.pendingPotionCount = 2;
        a.pendingPotions[1] = static_cast<int>(PotionId::FIRE_POTION);
        b.pendingPotions[1] = static_cast<int>(PotionId::BLOOD_POTION);
        check(public_observation(a) != public_observation(b), "second potion reward visible");
        a.pendingPotions[1] = b.pendingPotions[1];
        b.rewardCardPending[1] = true;
        check(public_observation(a) != public_observation(b), "second card reward visible");
        a.rewardCardPending[1] = b.rewardCardPending[1];
        a.stolenSyncCount = b.stolenSyncCount = 1;
        a.stolenOriginalPresent[0] = b.stolenOriginalPresent[0] = true;
        a.stolenOriginals[0] = b.stolenOriginals[0] = a.deck[0];
        b.stolenOriginals[0].enchantment = EnchantmentId::SOWN;
        check(public_observation(a) != public_observation(b), "stolen reward original visible");
        a.stolenOriginals[0] = b.stolenOriginals[0];
        b.stolenRewardPending[0] = true;
        check(public_observation(a) != public_observation(b), "stolen reward pending visible");
    }
    std::cout << "checks=" << checks << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
