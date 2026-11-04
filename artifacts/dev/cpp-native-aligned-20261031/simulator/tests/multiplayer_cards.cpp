// Multiplayer-only cards (Blaze, Midnight, Outrage, The Ball).
//
// The simulator has no multiplayer runtime: there are no teammate creatures and
// no per-player piles. These tests exercise the single-player-degenerate
// semantics of each card. Ally-only and teammate-side effects are documented in
// the coverage table as a runtime boundary, not fully verified multiplayer
// behaviour.
#include "sts2/battle.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
BattleContext battle() {
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 100 + i);
    BattleContext b;
    b.init(Encounter::SETUP_CULTISTS_NORMAL, 13, deck, 10, 0, 400, 400);
    b.monsters[0].hp = 400;
    b.player.energy = 30;
    return b;
}
bool play(BattleContext &b, int hand, int target) {
    Action a{};
    a.type = ActionType::PLAY_CARD;
    a.hand = static_cast<std::uint8_t>(hand);
    a.target = static_cast<std::int8_t>(target);
    return b.step(a);
}
}

int main() {
    {
        // Every multiplayer-only card is flagged and therefore absent from
        // every single-player generation and reward pool.
        const CardId ids[] = {
            CardId::BLAZE, CardId::MIDNIGHT, CardId::OUTRAGE, CardId::THE_BALL,
            CardId::DEMONIC_SHIELD, CardId::TANK_CARD, CardId::IMITATION_LEARNING,
            CardId::BEACON_OF_HOPE, CardId::GANG_UP, CardId::HUDDLE_UP,
            CardId::INTERCEPT_CARD, CardId::KNOCKDOWN, CardId::LIFT, CardId::MIMIC,
            CardId::RALLY, CardId::TAG_TEAM};
        for (CardId id : ids)
            check(card_def(id).flags & CF_MULTIPLAYER_ONLY,
                  "multiplayer card carries CF_MULTIPLAYER_ONLY");
    }
    {
        // Blaze: TargetType.AnyAlly. With no teammates the only legal ally is
        // the owner, so Strength lands on the player.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::BLAZE, false, 900);
        check(play(b, b.handCount - 1, -1), "Blaze plays");
        check(b.player_power(PowerId::STRENGTH) == 5, "Blaze grants five Strength");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::BLAZE, true, 901);
        check(play(b, b.handCount - 1, -1), "upgraded Blaze plays");
        check(b.player_power(PowerId::STRENGTH) == 7, "upgraded Blaze grants seven");
    }
    {
        // Midnight: plain attack; the multiplayer-only constraint does not
        // change the play. Cost is 12.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::MIDNIGHT, false, 902);
        check(card_cost(b.hand[b.handCount - 1]) == 12, "Midnight costs twelve");
        check(play(b, b.handCount - 1, 0), "Midnight plays");
        check(b.monsters[0].hp == hp - 60, "Midnight deals sixty");
    }
    {
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::MIDNIGHT, true, 903);
        check(play(b, b.handCount - 1, 0), "upgraded Midnight plays");
        check(b.monsters[0].hp == hp - 72, "upgraded Midnight deals seventy-two");
    }
    {
        // Midnight.AfterCardExhausted: each exhausted card reduces the cost of
        // every Midnight by one for the rest of the combat.
        auto b = battle();
        const int m0 = b.handCount;
        b.hand[b.handCount++] = make_card(CardId::MIDNIGHT, false, 904);
        const int m1 = b.handCount;
        b.hand[b.handCount++] = make_card(CardId::MIDNIGHT, false, 905);
        check(card_cost(b.hand[m0]) == 12 && card_cost(b.hand[m1]) == 12,
              "both Midnights start at twelve");
        b.move_to_exhaust(make_card(CardId::STRIKE_IRONCLAD, false, 906));
        check(card_cost(b.hand[m0]) == 11 && card_cost(b.hand[m1]) == 11,
              "one exhaust reduces every Midnight to eleven");
        b.move_to_exhaust(make_card(CardId::STRIKE_IRONCLAD, false, 907));
        b.move_to_exhaust(make_card(CardId::STRIKE_IRONCLAD, false, 908));
        check(card_cost(b.hand[m0]) == 9, "three exhausts reduce Midnight to nine");
        const Card exhaustedMidnight = b.hand[m0];
        check(b.detach_card(904), "a Midnight is removed from the hand");
        b.move_to_exhaust(exhaustedMidnight);
        check(card_cost(b.hand[m0]) == 8,
              "exhausting a Midnight itself also reduces the other copy");
    }
    {
        // Outrage: damage in single player; no teammate clones exist.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::OUTRAGE, false, 909);
        check(play(b, b.handCount - 1, 0), "Outrage plays");
        check(b.monsters[0].hp == hp - 9, "Outrage deals nine");
        int copies = 0;
        for (int i = 0; i < b.handCount; ++i)
            copies += b.hand[i].id == CardId::OUTRAGE ? 1 : 0;
        for (int i = 0; i < b.drawCount; ++i)
            copies += b.draw[i].id == CardId::OUTRAGE ? 1 : 0;
        for (int i = 0; i < b.discardCount; ++i)
            copies += b.discard[i].id == CardId::OUTRAGE ? 1 : 0;
        for (int i = 0; i < b.exhaustCount; ++i)
            copies += b.exhaust[i].id == CardId::OUTRAGE ? 1 : 0;
        check(copies == 1 && b.discard[b.discardCount - 1].id == CardId::OUTRAGE,
              "single player receives no teammate clone");
    }
    {
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::OUTRAGE, true, 910);
        check(play(b, b.handCount - 1, 0), "upgraded Outrage plays");
        check(b.monsters[0].hp == hp - 13, "upgraded Outrage deals thirteen");
    }
    {
        // The Ball: deals its current damage, then grows by Increase (10).
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::THE_BALL, false, 911);
        check(play(b, b.handCount - 1, 0), "The Ball plays");
        check(b.monsters[0].hp == hp - 10, "The Ball deals ten");
        Card *inDiscard = b.find_in_discard(911);
        check(inDiscard != nullptr && inDiscard->bonusDamage == 10,
              "The Ball grows by ten after its first play");
        check(inDiscard != nullptr && card_damage(*inDiscard) == 20,
              "the discarded instance now hits for twenty");
        const Card grown = inDiscard ? *inDiscard : Card{};
        check(b.detach_card(911), "The Ball can be replayed from the discard");
        b.add_card_to_hand(grown);
        const int hp2 = b.monsters[0].hp;
        check(play(b, b.handCount - 1, 0), "The Ball plays a second time");
        check(b.monsters[0].hp == hp2 - 20, "the second play deals twenty");
    }
    {
        // Upgraded The Ball keeps its 10 damage but grows by 15 per play.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::THE_BALL, true, 912);
        check(play(b, b.handCount - 1, 0), "upgraded The Ball plays");
        check(b.monsters[0].hp == hp - 10, "upgraded The Ball still deals ten");
        Card *inDiscard = b.find_in_discard(912);
        check(inDiscard != nullptr && inDiscard->bonusDamage == 15,
              "upgraded The Ball grows by fifteen");
        check(inDiscard != nullptr && card_damage(*inDiscard) == 25,
              "the discarded upgraded instance now hits for twenty-five");
    }
    // ---- single-player-degenerate ally cards ----
    {
        // Gang Up: CalculationBaseVar(5) plus ExtraDamageVar per this-turn
        // powered hit by a teammate. Single player has no teammates.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::GANG_UP, false, 920);
        check(play(b, b.handCount - 1, 0), "Gang Up plays");
        check(b.monsters[0].hp == hp - 5, "Gang Up deals its base five");
    }
    {
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::GANG_UP, true, 921);
        check(play(b, b.handCount - 1, 0), "upgraded Gang Up plays");
        check(b.monsters[0].hp == hp - 5,
              "upgraded Gang Up's extra term needs a teammate; base five");
    }
    {
        // Huddle Up: each ally draws CardsVar; the owner is the only ally.
        auto b = battle();
        const int draw = b.drawCount;
        b.hand[b.handCount++] = make_card(CardId::HUDDLE_UP, false, 922);
        check(play(b, b.handCount - 1, -1), "Huddle Up plays");
        check(b.drawCount == draw - 2, "Huddle Up draws two for the owner");
    }
    {
        auto b = battle();
        const int draw = b.drawCount;
        b.hand[b.handCount++] = make_card(CardId::HUDDLE_UP, true, 923);
        check(play(b, b.handCount - 1, -1), "upgraded Huddle Up plays");
        check(b.drawCount == draw - 3, "upgraded Huddle Up draws three");
    }
    {
        // Intercept: owner gains BlockVar(9) and the target (owner in single
        // player) gains CoveredPower, which nullifies powered attack damage.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::INTERCEPT_CARD, false, 924);
        check(play(b, b.handCount - 1, -1), "Intercept plays");
        check(b.player.block == 9, "Intercept gains nine block for the owner");
        check(b.player_power(PowerId::COVERED) == 1, "Intercept covers the owner");
        const int hp = b.player.hp;
        check(b.damage_player(20, false, true) == 0,
              "covered player ignores powered attack damage");
        check(b.player.hp == hp && b.player.block == 9,
              "ignored powered damage consumes neither HP nor block");
        check(b.damage_player(20, false, false) > 0,
              "unpowered damage is not covered");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::INTERCEPT_CARD, true, 925);
        check(play(b, b.handCount - 1, -1), "upgraded Intercept plays");
        check(b.player.block == 13, "upgraded Intercept gains thirteen");
    }
    {
        // CoveredPower.AfterSideTurnEnd(Enemy): expires with the enemy turn.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::INTERCEPT_CARD, false, 926);
        play(b, b.handCount - 1, -1);
        Action end{};
        end.type = ActionType::END_TURN;
        b.step(end);
        check(b.player_power(PowerId::COVERED) == 0,
              "Covered expires at the end of the enemy turn");
    }
    {
        // Lift: AnyAlly BlockVar(11/16); the owner is the only ally.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::LIFT, false, 927);
        check(play(b, b.handCount - 1, -1), "Lift plays");
        check(b.player.block == 11, "Lift gains eleven block");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::LIFT, true, 928);
        check(play(b, b.handCount - 1, -1), "upgraded Lift plays");
        check(b.player.block == 16, "upgraded Lift gains sixteen");
    }
    {
        // Mimic: block equal to the target's current block; target == owner.
        auto b = battle();
        b.player.block = 6;
        b.hand[b.handCount++] = make_card(CardId::MIMIC, false, 929);
        check(play(b, b.handCount - 1, -1), "Mimic plays");
        check(b.player.block == 12, "Mimic copies the owner's six block");
    }
    {
        // Rally: AllAllies BlockVar(12/17), once for the owner in single player.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::RALLY, false, 930);
        check(play(b, b.handCount - 1, -1), "Rally plays");
        check(b.player.block == 12, "Rally gains twelve block");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::RALLY, true, 931);
        check(play(b, b.handCount - 1, -1), "upgraded Rally plays");
        check(b.player.block == 17, "upgraded Rally gains seventeen");
    }
    {
        // Tag Team: attack + TagTeamPower 1. The power only raises a teammate's
        // attack play count, so it is inert in single player but still applied.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::TAG_TEAM, false, 932);
        check(play(b, b.handCount - 1, 0), "Tag Team plays");
        check(b.monsters[0].hp == hp - 11, "Tag Team deals eleven");
        check(b.monsters[0].power[static_cast<int>(PowerId::TAG_TEAM)] == 1,
              "Tag Team applies its debuff");
    }
    {
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::TAG_TEAM, true, 933);
        check(play(b, b.handCount - 1, 0), "upgraded Tag Team plays");
        check(b.monsters[0].hp == hp - 15, "upgraded Tag Team deals fifteen");
    }
    {
        // Knockdown: attack + KnockdownPower(2/3). Its damage multiplier only
        // applies to a dealer other than the applier, so single player sees the
        // attack and the (expiring) debuff.
        auto b = battle();
        const int hp = b.monsters[0].hp;
        b.hand[b.handCount++] = make_card(CardId::KNOCKDOWN, false, 934);
        check(play(b, b.handCount - 1, 0), "Knockdown plays");
        check(b.monsters[0].hp == hp - 10, "Knockdown deals ten");
        check(b.monsters[0].power[static_cast<int>(PowerId::KNOCKDOWN)] == 2,
              "Knockdown applies two stacks");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::KNOCKDOWN, true, 935);
        const int hp = b.monsters[0].hp;
        check(play(b, b.handCount - 1, 0), "upgraded Knockdown plays");
        check(b.monsters[0].hp == hp - 14, "upgraded Knockdown deals fourteen");
        check(b.monsters[0].power[static_cast<int>(PowerId::KNOCKDOWN)] == 3,
              "upgraded Knockdown applies three stacks");
    }
    {
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::KNOCKDOWN, false, 936);
        play(b, b.handCount - 1, 0);
        Action end{};
        end.type = ActionType::END_TURN;
        b.step(end);
        check(b.monsters[0].power[static_cast<int>(PowerId::KNOCKDOWN)] == 0,
              "Knockdown expires when the owner's side turn ends");
    }
    {
        // Demonic Shield: owner loses 1 HP (unblockable/unpowered), then the
        // target gains block equal to the owner's current block.
        auto b = battle();
        b.player.block = 7;
        const int hp = b.player.hp;
        b.hand[b.handCount++] = make_card(CardId::DEMONIC_SHIELD, false, 937);
        check(play(b, b.handCount - 1, -1), "Demonic Shield plays");
        check(b.player.hp == hp - 1, "Demonic Shield costs one HP");
        check(b.player.block == 14, "Demonic Shield doubles seven block to fourteen");
    }
    {
        // Tank: TankPower makes the owner take 1.5x powered attack damage.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::TANK_CARD, false, 938);
        check(play(b, b.handCount - 1, -1), "Tank plays");
        check(b.player_power(PowerId::TANK) == 1, "Tank applies its power");
        const int hp = b.player.hp;
        b.damage_player(10, false, true);
        check(b.player.hp == hp - 15, "Tank scales powered damage by 1.5");
        b.damage_player(10, false, false);
        check(b.player.hp == hp - 25, "Tank does not scale unpowered damage");
    }
    {
        // Beacon of Hope: the power gives half of a block gain to *other*
        // players; single player has none, but the power is still applied.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::BEACON_OF_HOPE, false, 939);
        check(play(b, b.handCount - 1, -1), "Beacon of Hope plays");
        check(b.player_power(PowerId::BEACON_OF_HOPE) == 1,
              "Beacon of Hope applies its power");
        b.gain_block(10, true);
        check(b.player.block == 10,
              "no teammate receives half the block in single player");
    }
    {
        // Imitation Learning: every Power card the tracked player plays is
        // cloned and auto-played, spending one charge. The auto-played clone is
        // itself a Power card, so with two charges a Demon Form is played three
        // times (original + two chained clones), matching the native
        // BeforeCardPlayed/AfterCardPlayed pair.
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::IMITATION_LEARNING, false, 940);
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 941);
        check(play(b, b.handCount - 2, -1), "Imitation Learning plays");
        check(b.player_power(PowerId::IMITATION_LEARNING) == 2,
              "Imitation Learning applies two charges");
        check(play(b, b.handCount - 1, -1), "Demon Form plays under Imitation Learning");
        check(b.player_power(PowerId::IMITATION_LEARNING) == 0,
              "both charges are consumed");
        check(b.player_power(PowerId::DEMON_FORM) == 9,
              "Demon Form resolves three times (three Strength each)");
        int copies = 0;
        for (int i = 0; i < b.discardCount; ++i)
            copies += b.discard[i].id == CardId::DEMON_FORM_CARD ? 1 : 0;
        check(copies == 0, "power clones are not added to the discard pile");
    }
    {
        // Upgraded Imitation Learning: three charges => four plays of a Power
        // card (original plus three chained clones).
        auto b = battle();
        b.hand[b.handCount++] = make_card(CardId::IMITATION_LEARNING, true, 942);
        b.hand[b.handCount++] = make_card(CardId::DEMON_FORM_CARD, false, 943);
        check(play(b, b.handCount - 2, -1), "upgraded Imitation Learning plays");
        check(b.player_power(PowerId::IMITATION_LEARNING) == 3,
              "upgraded Imitation Learning applies three charges");
        check(play(b, b.handCount - 1, -1), "Demon Form plays");
        check(b.player_power(PowerId::DEMON_FORM) == 12,
              "Demon Form resolves four times");
    }
    std::cout << "multiplayer cards: " << checks << " checks, " << failures
              << " failures\n";
    return failures ? 1 : 0;
}
