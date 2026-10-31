// Native rule regressions for the 2026-10-28 deep audit (D01-D24).
//
// Every check isolates one rule and states the C# evidence in a comment next to
// it.  Built by CMake as `rules_test`; tests/test_native_rules.py runs it so a
// rule regression fails the normal pytest suite.  No check here claims client
// differential validation: the evidence level is "C# reference reading".
#include <cstring>
#include <iostream>
#include <set>
#include <type_traits>

#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/relics.h"
#include "sts2/run.h"

using namespace sts2;

namespace {

int checks = 0;
int failures = 0;

void check(const char *name, int actual, int expected) {
    ++checks;
    const bool ok = actual == expected;
    failures += ok ? 0 : 1;
    std::cout << name << " expected=" << expected << " actual=" << actual << " "
              << (ok ? "PASS" : "FAIL") << "\n";
}

// Ceremonial Beast with a clean hand/piles and plenty of energy, so each check
// controls exactly the state it exercises.
BattleContext base() {
    BattleContext b;
    Card deck[20];
    for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 20, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.player.energy = 20;
    return b;
}

void hand(BattleContext &b, CardId id, bool up = false) {
    b.hand[b.handCount++] = make_card(id, up, b.nextUid++);
}

void play(BattleContext &b, int idx = 0) {
    Action a;
    a.type = ActionType::PLAY_CARD;
    a.hand = idx;
    a.target = 0;
    b.step(a);
}

int card_id(const char *name) {
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        if (std::strcmp(card_name(static_cast<CardId>(i)), name) == 0) {
            return i;
        }
    }
    return -1;
}

int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) {
        const EventInfo *info = event_info(i);
        if (info != nullptr && std::strcmp(info->name, name) == 0) return i;
    }
    return -1;
}

// Stores `value` in the relic's [SavedProperty] counter, ends the combat and
// reports the counter the next combat starts with.
int counter_after_combat(RelicId id, int value) {
    RunContext r;
    r.init(1, 0);
    r.add_relic(id);
    r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    int ix = 0;
    while (ix < r.battle.relicCount && r.battle.relics[ix] != static_cast<int>(id)) ++ix;
    if (ix >= r.battle.relicCount) return -1;
    r.battle.relicAux[ix] = value;
    r.battle.outcome = Outcome::PLAYER_VICTORY;
    r.finish_combat();
    r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    ix = 0;
    while (ix < r.battle.relicCount && r.battle.relics[ix] != static_cast<int>(id)) ++ix;
    return ix < r.battle.relicCount ? r.battle.relicAux[ix] : -1;
}

// ------------------------------------------------------ round 4 / 5 audit
// Controlled battle used by the round-4 and round-5 audit probes: huge enemy HP,
// no starting piles, plenty of energy, so each check isolates one rule.

BattleContext audit_base() {
    BattleContext b;
    Card deck[20];
    for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 20, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.knownTopCount = 0;
    b.cardsDrawnThisTurn = 0;
    b.player.energy = 50;
    b.monsters[0].hp = b.monsters[0].maxHp = 10000;
    b.monsters[0].block = 0;
    return b;
}

Card audit_card(BattleContext &b, CardId id) { return make_card(id, false, b.nextUid++); }

void audit_hand(BattleContext &b, CardId id) { b.hand[b.handCount++] = audit_card(b, id); }

void audit_play(BattleContext &b) {
    Action a;
    a.type = ActionType::PLAY_CARD;
    a.hand = 0;
    a.target = 0;
    b.step(a);
}

void audit_choose(BattleContext &b) {
    Action a;
    a.type = ActionType::CHOOSE;
    a.uid = b.pending.cards[0].uid;
    b.step(a);
}

int audit_copies(const BattleContext &b, int uid) {
    int n = 0;
    for (int i = 0; i < b.handCount; ++i) n += b.hand[i].uid == uid;
    for (int i = 0; i < b.drawCount; ++i) n += b.draw[i].uid == uid;
    for (int i = 0; i < b.discardCount; ++i) n += b.discard[i].uid == uid;
    for (int i = 0; i < b.exhaustCount; ++i) n += b.exhaust[i].uid == uid;
    for (int i = 0; i < b.returnNextTurnCount; ++i) n += b.returnNextTurn[i].uid == uid;
    return n;
}

int audit_find(const BattleContext &b, MonsterId id) {
    for (int i = 0; i < b.monsterCount; ++i) {
        if (b.monsters[i].id == id) return i;
    }
    return -1;
}

int audit_alive_count(const BattleContext &b, MonsterId id) {
    int n = 0;
    for (int i = 0; i < b.monsterCount; ++i) {
        if (b.monsters[i].id == id && b.monsters[i].alive) ++n;
    }
    return n;
}

int audit_count_card(const Card *cards, int count, CardId id) {
    int n = 0;
    for (int i = 0; i < count; ++i) n += cards[i].id == id;
    return n;
}

void audit_round4_round5() {
    // R4-01/02 Fiend Fire: snapshot hand, one HitCount(cardCount) command.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::DARK_EMBRACE, 1);
        audit_hand(b, CardId::FIEND_FIRE);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        check("r4_01_fiend_fire_exhausts_initial_only", b.exhaustCount, 3);
        check("r4_01_fiend_fire_keeps_drawn", b.handCount, 3);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::VIGOR, 5);
        audit_hand(b, CardId::FIEND_FIRE);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        const int hp = b.monsters[0].hp;
        audit_play(b);
        check("r4_02_fiend_fire_vigor_all_hits", hp - b.monsters[0].hp, 24);
    }
    // R4-03 Nostalgia: result pile decided once at play start, only Discard
    // results are redirected, and Amount bounds the number per turn.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::NOSTALGIA, 1);
        audit_hand(b, CardId::IMPERVIOUS);
        audit_play(b);
        check("r4_03_nostalgia_keeps_exhaust", b.exhaustCount, 1);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::NOSTALGIA, 2);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        audit_play(b);
        check("r4_03_nostalgia_two_stacks", b.drawCount, 2);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::NOSTALGIA, 1);
        audit_hand(b, CardId::HAVOC);
        b.draw[b.drawCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        check("r4_03_nostalgia_havoc_child_exhausts", b.exhaustCount, 1);
        check("r4_03_nostalgia_outer_returns",
              b.drawCount ? int(b.draw[b.drawCount - 1].id) : 0, int(CardId::HAVOC));
    }
    // R4-04 Thrumming Hatchet: normal discard pile, recalled next round with
    // the temporary cost already restored.
    {
        auto b = audit_base();
        audit_hand(b, CardId::THRUMMING_HATCHET);
        audit_play(b);
        check("r4_04_hatchet_in_discard", b.discardCount, 1);
    }
    {
        auto b = audit_base();
        audit_hand(b, CardId::THRUMMING_HATCHET);
        const int uid = b.hand[0].uid;
        card_set_turn_cost(b.hand[0], 0);
        audit_play(b);
        b.end_player_turn();
        int cost = -99;
        for (int i = 0; i < b.handCount; ++i) if (b.hand[i].uid == uid) cost = card_cost(b.hand[i]);
        check("r4_04_hatchet_cost_restored", cost, 1);
    }
    // R4-05 Hidden Gem's replay is permanent for the combat.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::RUNIC_PYRAMID);
        audit_hand(b, CardId::HIDDEN_GEM);
        Card s = audit_card(b, CardId::STRIKE_IRONCLAD);
        const int uid = s.uid;
        b.draw[b.drawCount++] = s;
        audit_play(b);
        b.draw_cards(1);
        b.end_player_turn();
        int replay = -1;
        for (int i = 0; i < b.handCount; ++i) if (b.hand[i].uid == uid) replay = b.hand[i].replay;
        check("r4_05_hidden_gem_replay_persists", replay, 2);
    }
    // R4-06 Block modifier order: additive (Dexterity) then multiplicative
    // (Unmovable/Vambrace); Vambrace doubles the whole triggering card.
    {
        auto b = audit_base();
        b.player.dexterity = 3;
        b.add_player_power(PowerId::UNMOVABLE, 1);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_play(b);
        check("r4_06_unmovable_doubles_dexterity", b.player.block, 16);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::UNMOVABLE, 2);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_play(b);
        audit_play(b);
        check("r4_06_unmovable_two_stacks", b.player.block, 20);
    }
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::VAMBRACE);
        audit_hand(b, CardId::SECOND_WIND);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_play(b);
        check("r4_06_vambrace_whole_card", b.player.block, 20);
    }
    // R4-07 Flex Potion -> TemporaryStrengthPower -> StrengthPower -> Helmet.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::RUINED_HELMET);
        b.apply_potion(PotionId::FLEX_POTION, 0);
        check("r4_07_flex_triggers_helmet", b.player.strength, 10);
        b.end_player_turn();
        check("r4_07_flex_helmet_extra_persists", b.player.strength, 5);
    }
    // R4-08 Chemical X's ModifyXValue also applies to auto-plays.
    {
        auto b = audit_base();
        b.player.energy = 3;
        b.relics[b.relicCount++] = static_cast<int>(RelicId::CHEMICAL_X);
        const int hp = b.monsters[0].hp;
        b.auto_play_random(audit_card(b, CardId::WHIRLWIND), false);
        check("r4_08_chemical_x_auto", hp - b.monsters[0].hp, 25);
    }
    // R4-09 Hand of Greed is a FromCard attack: Pen Nib doubles it.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::PEN_NIB);
        relic_aux_set(b, RelicId::PEN_NIB, 9);
        audit_hand(b, CardId::HAND_OF_GREED);
        const int hp = b.monsters[0].hp;
        const int damage = card_damage(b.hand[0]);
        audit_play(b);
        check("r4_09_pen_nib_hand_of_greed", hp - b.monsters[0].hp, damage * 2);
    }
    // R4-10 The Gambit: only powered, unblocked attack damage; kill is immediate.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::THE_GAMBIT, 1);
        audit_hand(b, CardId::BLOODLETTING);
        audit_play(b);
        b.player.block = 1000;
        b.end_player_turn();
        check("r4_10_gambit_ignores_self_damage", b.player.hp > 0, 1);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::THE_GAMBIT, 1);
        b.monster_attack_player(0, 1);
        check("r4_10_gambit_kills_now", static_cast<int>(b.outcome),
              static_cast<int>(Outcome::PLAYER_LOSS));
    }
    // R4-11 Ninth Bomb / 10th known card are observable.
    {
        auto a = audit_base();
        a.bombCount = 9;
        for (int i = 0; i < 9; ++i) { a.bombTurns[i] = 3; a.bombDamage[i] = 40; }
        auto b = a;
        b.bombTurns[8] = 1;
        check("r4_11_ninth_bomb_observable",
              public_combat_observation(a) != public_combat_observation(b), 1);
        a.end_player_turn();
        b.end_player_turn();
        check("r4_11_ninth_bomb_changes_transition", a.monsters[0].hp - b.monsters[0].hp, 40);
    }
    {
        auto a = audit_base();
        for (int i = 0; i < 10; ++i) a.add_card_to_draw_top(audit_card(a, CardId::STRIKE_IRONCLAD));
        a.draw[0].id = CardId::BASH;
        auto b = a;
        std::swap(b.draw[0], b.draw[1]);
        check("r4_11_known_top_order_observable",
              public_combat_observation(a) != public_combat_observation(b), 1);
    }
    // R4-12 Velvet Choker's ShouldPlay applies to AutoPlay.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::VELVET_CHOKER);
        b.cardsPlayedThisTurn = 6;
        const int hp = b.monsters[0].hp;
        b.auto_play_random(audit_card(b, CardId::STRIKE_IRONCLAD), false);
        check("r4_12_auto_choker_limit", hp - b.monsters[0].hp, 0);
    }
    // R4-13 Strike Dummy's additive bonus is scaled by Weak.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::STRIKE_DUMMY);
        b.player.weak = 1;
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        const int hp = b.monsters[0].hp;
        audit_play(b);
        check("r4_13_strike_dummy_before_weak", hp - b.monsters[0].hp, 6);
    }

    // R5-01 transform pools over every card, no fixed 128 entry array.
    {
        RunContext r;
        r.init(125, 0);
        r.add_relic(RelicId::ASTROLABE);
        check("r5_01_astrolabe_completes", r.screen != RunScreen::RUN_OVER, 1);
    }
    // R5-02 Sozu blocks every potion path; Entropic Brew terminates.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::SOZU);
        b.apply_potion(PotionId::ENTROPIC_BREW, 0);
        check("r5_02_sozu_blocks_brew", b.potionCount, 0);
    }
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::SOZU);
        audit_hand(b, CardId::ALCHEMIZE);
        audit_play(b);
        check("r5_02_sozu_blocks_alchemize", b.potionCount, 0);
    }
    // R5-03 Permanent upgrades change the energy cost too.
    {
        RunContext r;
        r.init(123, 0);
        r.deckCount = 1;
        r.deck[0] = make_card(CardId::CORRUPTION_CARD, false, 1);
        r.screen = RunScreen::REST;
        check("r5_03_rest_upgrade_accepted", r.step({RunActionType::REST_UPGRADE, 0}), 1);
        check("r5_03_rest_upgrade_cost", card_cost(r.deck[0]), 2);
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        check("r5_03_rest_cost_in_battle", card_cost(r.battle.hand[0]), 2);
    }
    {
        RunContext r;
        r.init(124, 0);
        r.relics[r.relicCount++] = static_cast<int>(RelicId::TOXIC_EGG);
        r.screen = RunScreen::CARD_REWARD;
        r.offeredCount = 1;
        r.offered[0] = make_card(CardId::HAVOC, false, 900);
        r.step({RunActionType::TAKE_CARD, 0});
        check("r5_03_egg_upgrade_cost", card_cost(r.deck[r.deckCount - 1]), 0);
    }
    // R5-04 Grapple: triggered by block gain, no attack bonus, expires, and
    // is a visible Debuff for Artifact.
    {
        auto b = audit_base();
        audit_hand(b, CardId::GRAPPLE);
        const int amount = card_var(b.hand[0], VarId::GRAPPLE_POWER);
        audit_play(b);
        int hp = b.monsters[0].hp;
        b.gain_block(5, true);
        check("r5_04_grapple_on_block", hp - b.monsters[0].hp, amount);
        hp = b.monsters[0].hp;
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        check("r5_04_grapple_no_attack_bonus", hp - b.monsters[0].hp, 6);
        b.end_player_turn();
        check("r5_04_grapple_expires", b.monster_power(0, PowerId::GRAPPLE), 0);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)] = 1;
        audit_hand(b, CardId::GRAPPLE);
        audit_play(b);
        check("r5_04_artifact_blocks_grapple", b.monster_power(0, PowerId::GRAPPLE), 0);
        check("r5_04_artifact_consumed", b.monster_power(0, PowerId::ARTIFACT), 0);
    }
    // R5-05 Colossus checks the dealer's Vulnerable and ticks per enemy turn.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::COLOSSUS, 1);
        b.monsters[0].vulnerable = 1;
        const int hp = b.player.hp;
        b.monster_attack_player(0, 10);
        check("r5_05_colossus_dealer_vulnerable", hp - b.player.hp, 5);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::COLOSSUS, 1);
        b.player.vulnerable = 1;
        const int hp = b.player.hp;
        b.monster_attack_player(0, 10);
        check("r5_05_colossus_ignores_player_vulnerable", hp - b.player.hp, 15);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::COLOSSUS, 2);
        b.end_player_turn();
        check("r5_05_colossus_two_stacks", b.player_power(PowerId::COLOSSUS), 1);
    }
    // R5-06 Gigantification triples one AttackCommand and only loses a stack
    // when an attack is actually played.
    {
        auto b = audit_base();
        b.apply_potion(PotionId::GIGANTIFICATION_POTION, 0);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        int hp = b.monsters[0].hp;
        audit_play(b);
        check("r5_06_gigantification_triples", hp - b.monsters[0].hp, 18);
        hp = b.monsters[0].hp;
        audit_play(b);
        check("r5_06_gigantification_consumed", hp - b.monsters[0].hp, 6);
    }
    {
        auto b = audit_base();
        b.apply_potion(PotionId::GIGANTIFICATION_POTION, 0);
        b.end_player_turn();
        check("r5_06_gigantification_unused_survives", b.player_power(PowerId::GIGANTIFICATION), 1);
    }
    // R5-07 FreeAttack survives the turn and never changes X-cost spending.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::FREE_ATTACK, 1);
        b.end_player_turn();
        check("r5_07_free_attack_survives", b.player_power(PowerId::FREE_ATTACK), 1);
    }
    {
        auto b = audit_base();
        b.player.energy = 3;
        b.add_player_power(PowerId::FREE_ATTACK, 1);
        audit_hand(b, CardId::WHIRLWIND);
        const int hp = b.monsters[0].hp;
        audit_play(b);
        check("r5_07_free_x_damage", hp - b.monsters[0].hp, 15);
        check("r5_07_free_x_spends_energy", b.player.energy, 0);
    }
    // R5-08 Cruelty adds to the Vulnerable multiplier.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::CRUELTY, 50);
        b.monsters[0].vulnerable = 1;
        check("r5_08_cruelty_additive", b.calc_player_damage(10, 0), 20);
    }
    // R5-09 Howl From Beyond fires for every exhausted copy before the draw.
    {
        auto b = audit_base();
        b.exhaust[b.exhaustCount++] = audit_card(b, CardId::HOWL_FROM_BEYOND);
        b.exhaust[b.exhaustCount++] = audit_card(b, CardId::HOWL_FROM_BEYOND);
        const int hp = b.monsters[0].hp;
        b.start_player_turn();
        check("r5_09_howl_all_copies", hp - b.monsters[0].hp, 32);
    }
    // R5-10 Drum of Battle exhausts the top cards before drawing.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::DRUM_OF_BATTLE, 1);
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::DEFEND_IRONCLAD);
        b.start_player_turn();
        check("r5_10_drum_exhausts", b.exhaustCount, 1);
    }
    // R5-11 Aggression takes Amount cards from the discard before the draw.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::AGGRESSION, 2);
        b.player.drawPerTurn = 0;
        b.discard[b.discardCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.discard[b.discardCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.start_player_turn();
        check("r5_11_aggression_two_stacks", b.handCount, 2);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::AGGRESSION, 1);
        b.discard[b.discardCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.start_player_turn();
        check("r5_11_aggression_before_shuffle",
              b.handCount ? int(b.hand[0].upgraded) : 0, 1);
    }
    // R5-12 Automation counts ten drawn cards per instance, across turns.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::AUTOMATION, 1);
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::DEFEND_IRONCLAD);
        b.draw_cards(7);
        b.handCount = 0;
        b.player.drawPerTurn = 0;
        b.start_player_turn();
        const int energy = b.player.energy;
        b.draw_cards(3);
        check("r5_12_automation_across_turns", b.player.energy - energy, 1);
    }
    {
        auto b = audit_base();
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::DEFEND_IRONCLAD);
        b.draw_cards(7);
        b.add_player_power(PowerId::AUTOMATION, 1);
        const int energy = b.player.energy;
        b.draw_cards(3);
        check("r5_12_automation_ignores_prior_draws", b.player.energy - energy, 0);
    }
    // R5-13 Stratagem opens a manual multi-card selection after a shuffle.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::STRATAGEM, 2);
        for (int i = 0; i < 4; ++i) b.discard[b.discardCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.shuffle_discard_into_draw();
        check("r5_13_stratagem_choice", b.pending.op != ChoiceOp::NONE, 1);
        for (int g = 0; g < 5 && b.pending.op != ChoiceOp::NONE; ++g) audit_choose(b);
        check("r5_13_stratagem_count", b.handCount, 2);
    }
    // R5-14 Brightest Flame loses max HP without wounding current HP.
    {
        auto b = audit_base();
        b.player.hp = 100;
        audit_hand(b, CardId::BRIGHTEST_FLAME);
        audit_play(b);
        check("r5_14_brightest_hp_unchanged", b.player.hp, 100);
        check("r5_14_brightest_maxhp", b.player.maxHp, 499);
    }
    {
        auto b = audit_base();
        b.player.hp = 1;
        audit_hand(b, CardId::BRIGHTEST_FLAME);
        audit_play(b);
        check("r5_14_brightest_one_hp_maxhp", b.player.maxHp, 499);
    }
    // R5-15 Snecko Oil leaves X costs alone.
    {
        auto b = audit_base();
        audit_hand(b, CardId::WHIRLWIND);
        b.apply_potion(PotionId::SNECKO_OIL, 0);
        check("r5_15_snecko_keeps_x", card_cost(b.hand[0]), -1);
    }
    // A1 Snecko Eye randomizes on draw with SetThisCombat semantics.
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::SNECKO_EYE);
        for (int i = 0; i < 8; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::BASH);
        b.draw_cards(8);
        relics_hand_drawn(b);
        check("a1_snecko_cost_not_turn_temporary", b.handCount ? b.hand[0].costThisTurn : 1, 0);
    }
    // R5-16 Mummified Hand never wastes its trigger on a 0-cost card.
    {
        int missed = 0;
        for (int k = 0; k < 100; ++k) {
            auto b = audit_base();
            b.rng = Rng(k + 1);
            b.relics[b.relicCount++] = static_cast<int>(RelicId::MUMMIFIED_HAND);
            audit_hand(b, CardId::INFLAME);
            audit_hand(b, CardId::ANGER);
            audit_hand(b, CardId::BASH);
            audit_play(b);
            for (int i = 0; i < b.handCount; ++i) {
                if (b.hand[i].id == CardId::BASH) missed += card_cost(b.hand[i]) != 0;
            }
        }
        check("r5_16_mummified_never_zero_cost", missed, 0);
    }
    // R5-17/18 Intimidating Helmet uses actual energy; Hand Drill exact break.
    {
        auto b = audit_base();
        b.player.energy = 3;
        b.relics[b.relicCount++] = static_cast<int>(RelicId::INTIMIDATING_HELMET);
        audit_hand(b, CardId::WHIRLWIND);
        audit_play(b);
        check("r5_17_helmet_x_spend", b.player.block, 4);
    }
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::INTIMIDATING_HELMET);
        b.add_player_power(PowerId::FREE_ATTACK, 1);
        audit_hand(b, CardId::BASH);
        audit_play(b);
        check("r5_17_helmet_free_attack_no_block", b.player.block, 0);
    }
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::HAND_DRILL);
        b.monsters[0].block = 6;
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        check("r5_18_hand_drill_exact_break", b.monsters[0].vulnerable, 2);
    }
    // R5-19/20 Fisticuffs and Omnislice use the actual DamageResult.
    {
        auto b = audit_base();
        b.add_player_power(PowerId::VIGOR, 5);
        audit_hand(b, CardId::FISTICUFFS);
        audit_play(b);
        check("r5_19_fisticuffs_vigor", b.player.block, 12);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::INTANGIBLE)] = 1;
        audit_hand(b, CardId::FISTICUFFS);
        audit_play(b);
        check("r5_19_fisticuffs_intangible", b.player.block, 1);
    }
    {
        auto b = audit_base();
        b.monsterCount = 2;
        b.monsters[1] = b.monsters[0];
        b.monsters[1].slot = 1;
        b.monsters[0].power[static_cast<int>(PowerId::INTANGIBLE)] = 1;
        audit_hand(b, CardId::OMNISLICE);
        const int hp = b.monsters[1].hp;
        audit_play(b);
        check("r5_20_omnislice_intangible", hp - b.monsters[1].hp, 1);
    }
    {
        auto b = audit_base();
        b.monsterCount = 2;
        b.monsters[1] = b.monsters[0];
        b.monsters[1].slot = 1;
        b.add_player_power(PowerId::VIGOR, 5);
        audit_hand(b, CardId::OMNISLICE);
        const int hp = b.monsters[1].hp;
        audit_play(b);
        check("r5_20_omnislice_vigor", hp - b.monsters[1].hp, 13);
    }
    // R5-21..25 Monster powers are real hooks, not stored numbers.
    {
        auto b = audit_base();
        b.monsterCount = 0;
        spawn_monster(b, MonsterId::SKULKING_COLONY);
        const int hp = b.monsters[0].hp;
        b.damage_monster(0, 15);
        b.damage_monster(0, 15);
        check("r5_21_hardened_shell_cap", hp - b.monsters[0].hp, 20);
    }
    {
        auto b = audit_base();
        b.monsterCount = 0;
        spawn_monster(b, MonsterId::TEST_SUBJECT);
        const int strength = b.monsters[0].strength;
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_play(b);
        check("r5_22_enrage_on_skill", b.monsters[0].strength - strength, 2);
    }
    {
        auto b = audit_base();
        b.monsterCount = 0;
        spawn_monster(b, MonsterId::BYGONE_EFFIGY);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::DEFEND_IRONCLAD);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_play(b);
        audit_play(b);
        const int hp = b.monsters[0].hp;
        audit_play(b);
        check("r5_23_slow_scaling", hp - b.monsters[0].hp, 7);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::PAINFUL_STABS)] = 1;
        b.monster_attack_player(0, 1);
        int wounds = 0;
        for (int i = 0; i < b.discardCount; ++i) wounds += b.discard[i].id == CardId::WOUND;
        check("r5_24_painful_stabs_wound", wounds, 1);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::NEMESIS)] = 1;
        b.monster_turn();
        check("r5_25_nemesis_intangible", b.monster_power(0, PowerId::INTANGIBLE), 1);
    }
    // R5-26 Entropic Brew uses the combat potion RNG and the out-of-combat pool.
    {
        auto b = audit_base();
        const auto before = b.potionRng.counter;
        b.apply_potion(PotionId::ENTROPIC_BREW, 0);
        check("r5_26_brew_uses_potion_rng", b.potionRng.counter > before, 1);
    }
    // R5-27 Public observation distinguishes decision-relevant hidden states.
    {
        auto a = audit_base();
        a.player.strength = 5;
        auto b = a;
        b.player.tempStrength = 5;
        check("r5_27_obs_temp_strength",
              public_combat_observation(a) != public_combat_observation(b), 1);
        a.end_player_turn();
        b.end_player_turn();
        check("r5_27_control_temp_strength_transition", a.player.strength - b.player.strength, 5);
    }
    {
        auto a = audit_base();
        audit_hand(a, CardId::DEFEND_IRONCLAD);
        card_set_turn_cost(a.hand[0], 0);
        auto b = a;
        b.hand[0].freeCombat = true;
        check("r5_27_obs_permanent_vs_temp_free",
              public_combat_observation(a) != public_combat_observation(b), 1);
        Action ac;
        ac.type = ActionType::PLAY_CARD;
        check("r5_27_action_permanent_vs_temp_free",
              combat_action_features(a, ac) != combat_action_features(b, ac), 1);
    }
    {
        auto a = audit_base();
        a.draw[a.drawCount++] = audit_card(a, CardId::BASH);
        auto b = a;
        b.upgrade_card(b.draw[0]);
        check("r5_27_obs_draw_upgrade_identity",
              public_combat_observation(a) != public_combat_observation(b), 1);
    }
    // E1 Hatchet terminal UID uniqueness after a Panache kill.
    {
        auto b = audit_base();
        b.monsters[0].hp = 12;
        b.add_player_power(PowerId::PANACHE, 5);
        b.cardsPlayedThisTurn = 4;
        b.panachePrimed[0] = true;
        b.panacheLeft[0] = 1;
        audit_hand(b, CardId::THRUMMING_HATCHET);
        const int uid = b.hand[0].uid;
        audit_play(b);
        check("e1_hatchet_terminal_uid", audit_copies(b, uid), 1);
        check("e1_hatchet_panache_wins", static_cast<int>(b.outcome),
              static_cast<int>(Outcome::PLAYER_VICTORY));
    }
}

}  // namespace

int main() {
    audit_round4_round5();

    // ---------------------------------------------------------------- D01
    // Beat Down collects every playable attack in the (whole) discard pile.
    // cards_colorless.cpp used a MAX_HAND-sized index array, which overflowed
    // for piles > 10 (the audit captured index=10 past int[10]).
    {
        auto b = base();
        hand(b, CardId::BEAT_DOWN);
        for (int i = 0; i < 20; ++i) {
            b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        play(b);
        int strikes = 0;
        for (int i = 0; i < b.discardCount; ++i) {
            strikes += b.discard[i].id == CardId::STRIKE_IRONCLAD ? 1 : 0;
        }
        check("beat_down_large_discard_keeps_strikes", strikes, 20);
        check("beat_down_large_discard_no_overflow", b.discardCount, 21);
        std::set<int> uids;
        for (int i = 0; i < b.discardCount; ++i) uids.insert(b.discard[i].uid);
        check("beat_down_large_discard_unique_uids", static_cast<int>(uids.size()),
              b.discardCount);
    }
    {
        auto b = base();
        hand(b, CardId::BEAT_DOWN);
        for (int i = 0; i < 3; ++i) {
            b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        play(b);
        int attacks = 0;
        for (int i = 0; i < b.discardCount; ++i) {
            attacks += b.discard[i].id == CardId::STRIKE_IRONCLAD ? 1 : 0;
        }
        check("beat_down_preserves_three_attacks", attacks, 3);
    }

    // ---------------------------------------------------------------- D02
    // FlexPotion/SpeedPotion: +5 is temporary, it must not be added twice to
    // the damage/block formula.
    {
        auto b = base();
        b.apply_potion(PotionId::FLEX_POTION, 0);
        hand(b, CardId::STRIKE_IRONCLAD);
        const int hp = b.monsters[0].hp;
        play(b);
        check("flex_strike_damage", hp - b.monsters[0].hp, 11);
    }
    {
        auto b = base();
        b.apply_potion(PotionId::SPEED_POTION, 0);
        hand(b, CardId::DEFEND_IRONCLAD);
        play(b);
        check("speed_defend_block", b.player.block, 10);
    }
    {
        // SetupStrike adds temporary strength and the end-of-turn removal must
        // not subtract it twice.
        auto b = base();
        hand(b, CardId::SETUP_STRIKE_CARD);
        play(b);
        b.end_player_turn();
        check("setup_strike_strength_next_turn", b.player.strength, 0);
    }

    // ---------------------------------------------------------------- D03
    // CardModel.PileType: powers go to PileType.None, never the exhaust pile.
    {
        auto b = base();
        hand(b, CardId::FEEL_NO_PAIN_CARD);
        play(b);
        check("power_should_not_exhaust", b.exhaustCount, 0);
        check("feel_no_pain_should_not_trigger_on_self", b.player.block, 0);
    }

    // ---------------------------------------------------------------- D04
    // FeelNoPainPower (and other power sources) use ValueProp.Unpowered.
    {
        auto b = base();
        b.player.dexterity = 5;
        b.add_player_power(PowerId::FEEL_NO_PAIN, 3);
        b.move_to_exhaust(make_card(CardId::STRIKE_IRONCLAD, false, 90));
        check("unpowered_feel_no_pain_ignores_dex", b.player.block, 3);
    }

    // ---------------------------------------------------------------- D05
    // TheBombPower.IsInstanced: each copy keeps its own timer and damage.
    {
        auto b = base();
        hand(b, CardId::THE_BOMB_CARD);
        hand(b, CardId::THE_BOMB_CARD);
        play(b);
        play(b);
        const int hp = b.monsters[0].hp;
        for (int i = 0; i < 3; ++i) b.end_player_turn();
        check("two_bombs_explode_independently_at_turn3", hp - b.monsters[0].hp, 80);
    }
    {
        auto b = base();
        b.player.strength = 10;
        b.monsters[0].vulnerable = 10;
        hand(b, CardId::THE_BOMB_CARD);
        play(b);
        const int hp = b.monsters[0].hp;
        for (int i = 0; i < 3; ++i) b.end_player_turn();
        check("bomb_unpowered_ignores_strength_vulnerable", hp - b.monsters[0].hp, 40);
    }
    {
        // ExplosiveAmpoule also uses ValueProp.Unpowered.
        auto b = base();
        b.monsters[0].vulnerable = 1;
        const int hp = b.monsters[0].hp;
        b.apply_potion(PotionId::EXPLOSIVE_AMPOULE, 0);
        check("explosive_ampoule_ignores_vulnerable", hp - b.monsters[0].hp, 10);
    }
    // Remaining ValueProp.Unpowered sources in the Ironclad card pool.
    {
        auto b = base();
        b.player.block = 7;
        b.player.dexterity = 5;
        hand(b, CardId::ENTRENCH);
        play(b);
        check("entrench_unpowered_block", b.player.block, 14);
    }
    {
        auto b = base();
        b.player.dexterity = 5;
        b.add_player_power(PowerId::RAGE, 3);
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("rage_block_unpowered", b.player.block, 3);
    }
    {
        auto b = base();
        b.player.dexterity = 5;
        b.add_player_power(PowerId::BLOCK_NEXT_TURN, 10);
        b.start_player_turn();
        check("block_next_turn_unpowered", b.player.block, 10);
    }
    {
        auto b = base();
        b.player.strength = 10;
        b.add_player_power(PowerId::ROLLING_BOULDER, 10);
        const int hp = b.monsters[0].hp;
        b.start_player_turn();
        check("rolling_boulder_unpowered", hp - b.monsters[0].hp, 10);
    }
    {
        auto b = base();
        b.player.strength = 10;
        b.add_player_power(PowerId::PANACHE, 5);
        b.cardsPlayedThisTurn = 4;
        b.panachePrimed[0] = true;
        b.panacheLeft[0] = 1;
        const int hp = b.monsters[0].hp;
        hand(b, CardId::DEFEND_IRONCLAD);
        play(b);
        check("panache_unpowered", hp - b.monsters[0].hp, 5);
    }
    {
        auto b = base();
        b.player.strength = 10;
        b.add_player_power(PowerId::INFERNO, 5);
        const int hp = b.monsters[0].hp;
        b.lose_hp(1);
        check("inferno_unpowered", hp - b.monsters[0].hp, 5);
    }
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::KUSARIGAMA);
        b.player.strength = 10;
        b.attacksPlayedThisTurn = 3;
        const int hp = b.monsters[0].hp;
        relics_card_played(b, make_card(CardId::STRIKE_IRONCLAD, false, 77));
        check("kusarigama_unpowered", hp - b.monsters[0].hp, 6);
    }
    {
        // Unpowered block still runs the block-gained hooks.
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::ORICHALCUM);
        b.add_player_power(PowerId::JUGGERNAUT, 5);
        const int hp = b.monsters[0].hp;
        relics_turn_end(b);
        check("orichalcum_block_unpowered_value", b.player.block, 6);
        check("orichalcum_block_triggers_juggernaut", hp - b.monsters[0].hp, 5);
    }
    {
        // Fortifier.cs gains Block * 2 (Unpowered), i.e. triples the block.
        auto b = base();
        b.potions[0] = static_cast<int>(PotionId::FORTIFIER);
        b.potionCount = 1;
        b.player.block = 4;
        b.use_potion(0, 0);
        check("fortifier_gains_twice_current_block", b.player.block, 12);
    }
    {
        // FoulPotion damages every creature, blockable and Unpowered.
        auto b = base();
        b.potions[0] = static_cast<int>(PotionId::FOUL_POTION);
        b.potionCount = 1;
        b.player.hp = 100;
        b.player.block = 20;
        b.use_potion(0, 0);
        check("foul_potion_self_damage_blockable", b.player.hp, 100);
        check("foul_potion_self_block_spent", b.player.block, 8);
    }

    // ---------------------------------------------------------------- D06
    // RupturePower only triggers on the owner's side.
    {
        auto b = base();
        b.add_player_power(PowerId::RUPTURE, 1);
        b.inMonsterTurn = true;
        b.monster_attack_player(0, 10);
        check("rupture_enemy_turn_no_strength", b.player.strength, 0);
    }

    // ---------------------------------------------------------------- D07
    // CardPileCmd.Draw stops when the hand is full; drawn cards must not be
    // pushed to the discard pile.
    {
        auto b = base();
        for (int i = 0; i < 10; ++i) hand(b, CardId::STRIKE_IRONCLAD);
        for (int i = 0; i < 3; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 100 + i);
        }
        b.draw_cards(3);
        check("full_hand_preserves_draw_pile", b.drawCount, 3);
        check("full_hand_no_extra_discard", b.discardCount, 0);
    }

    // ---------------------------------------------------------------- D08
    // CombatManager moves innate cards to the top and draws
    // max(normal draw, innate count), capped at MAX_HAND.
    {
        Card deck[20];
        deck[0] = make_card(CardId::DRAMATIC_ENTRANCE, false, 1);
        deck[1] = make_card(CardId::DRAMATIC_ENTRANCE, false, 2);
        for (int i = 2; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 20, 0, 500, 500);
        int innateInHand = 0;
        for (int i = 0; i < b.handCount; ++i) {
            innateInHand += card_has(b.hand[i], CF_INNATE) ? 1 : 0;
        }
        check("two_innate_initial_hand_size", b.handCount, 5);
        check("two_innate_cards_in_opening_hand", innateInHand, 2);
    }

    // ---------------------------------------------------------------- D09
    // OnUpgrade keyword changes (SecretTechnique loses Exhaust; others gain
    // Innate/Retain) must come from the generated variant data.
    {
        auto b = base();
        hand(b, CardId::SECRET_TECHNIQUE, true);
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 90);
        play(b);
        if (b.pending.count) b.resolve_choice(b.pending.cards[0].uid);
        check("upgraded_secret_technique_no_exhaust", b.exhaustCount, 0);
        Card up = make_card(CardId::AGGRESSION_CARD, true, 7);
        check("upgraded_aggression_gains_innate", card_has(up, CF_INNATE), 1);
    }

    // ---------------------------------------------------------------- D10
    // CombatManager resolves Ethereal before Runic Pyramid retention.
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::RUNIC_PYRAMID);
        hand(b, CardId::DAZED);
        b.discard_hand();
        check("ethereal_before_pyramid_retention", b.exhaustCount, 1);
    }

    // ---------------------------------------------------------------- D11
    // CardEnergyCost: temporary costs expire at end of turn in any pile.
    {
        auto b = base();
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, 90);
        card_set_turn_cost(c, 0);
        b.discard[b.discardCount++] = c;
        b.end_player_turn();
        bool found = false;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].uid == 90) {
                check("temporary_free_card_cost_resets_in_discard", card_cost(b.hand[i]), 1);
                found = true;
            }
        }
        check("temporary_free_card_redrawn", found ? 1 : 0, 1);
    }

    // ---------------------------------------------------------------- D12
    // PenNib.AttacksPlayed is [SavedProperty]: it survives combat.
    {
        RunContext r;
        r.init(1, 0);
        r.add_relic(RelicId::PEN_NIB);
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        int ix = 0;
        while (r.battle.relics[ix] != static_cast<int>(RelicId::PEN_NIB)) ++ix;
        r.battle.relicAux[ix] = 9;
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        check("pen_nib_counter_survives_combat", r.battle.relicAux[ix], 9);
    }
    // Nunchaku.cs / IronClub.cs / JossPaper.cs / TuningFork.cs /
    // PollinousCore.cs keep their counters in [SavedProperty] as well.
    check("nunchaku_counter_survives_combat",
          counter_after_combat(RelicId::NUNCHAKU, 9), 9);
    check("iron_club_counter_survives_combat",
          counter_after_combat(RelicId::IRON_CLUB, 3), 3);
    check("joss_paper_counter_survives_combat",
          counter_after_combat(RelicId::JOSS_PAPER, 4), 4);
    check("tuning_fork_counter_survives_combat",
          counter_after_combat(RelicId::TUNING_FORK, 7), 7);
    // Stored 2; the next combat's first player turn increments it before any
    // draw modification, so the new combat starts from 3.
    check("pollinous_core_counter_survives_combat",
          counter_after_combat(RelicId::POLLINOUS_CORE, 2), 3);
    {
        auto b = base();
        b.relics[b.relicCount] = static_cast<int>(RelicId::NUNCHAKU);
        b.relicAux[b.relicCount] = 8;
        ++b.relicCount;
        b.player.energy = 3;
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("nunchaku_counter_increments", b.relicAux[0], 9);
        check("nunchaku_ninth_attack_no_energy", b.player.energy, 2);
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("nunchaku_tenth_attack_grants_energy", b.player.energy, 2);
        check("nunchaku_tenth_counter", b.relicAux[0], 10);
    }
    {
        auto b = base();
        b.relics[b.relicCount] = static_cast<int>(RelicId::IRON_CLUB);
        b.relicAux[b.relicCount] = 3;
        ++b.relicCount;
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 90);
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("iron_club_counter_increments", b.relicAux[0], 4);
        check("iron_club_fourth_card_draws", b.handCount, 1);
    }
    {
        auto b = base();
        b.relics[b.relicCount] = static_cast<int>(RelicId::TUNING_FORK);
        b.relicAux[b.relicCount] = 9;
        ++b.relicCount;
        hand(b, CardId::DEFEND_IRONCLAD);
        const int before = b.player.block;
        play(b);
        check("tuning_fork_tenth_skill_blocks", b.player.block - before, 12);
        check("tuning_fork_counter_reduced_by_threshold", b.relicAux[0], 0);
    }
    {
        auto b = base();
        b.relics[b.relicCount] = static_cast<int>(RelicId::POLLINOUS_CORE);
        b.relicAux[b.relicCount] = 3;
        ++b.relicCount;
        for (int i = 0; i < 20; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        b.start_player_turn();
        check("pollinous_core_fourth_turn_extra_draw", b.handCount, 7);
        check("pollinous_core_counter_reset", b.relicAux[0], 0);
    }
    // DarkEmbracePower.cs / JossPaper.cs treat ethereal exhausts separately:
    // they are counted during the hand flush and settled at AfterTurnEnd.
    // Stoke snapshots its hand, then generates one Ironclad card per original
    // card. Dark Embrace draws must remain in hand, not be recursively exhausted.
    {
        auto b = base();
        b.add_player_power(PowerId::DARK_EMBRACE, 1);
        for (int i = 0; i < 8; ++i)
            b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 90 + i);
        hand(b, CardId::STOKE, true);
        hand(b, CardId::BASH);
        hand(b, CardId::ANGER);
        play(b);
        check("stoke_exhausts_only_original_hand_and_source", b.exhaustCount, 3);
        check("stoke_preserves_exhaust_draws_and_generates_two", b.handCount, 5);
        check("stoke_does_not_draw_for_generation", b.drawCount, 5);
        int generated = 0, upgraded = 0, ironclad = 0;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].uid >= 90 && b.hand[i].uid < 98) continue;
            ++generated;
            upgraded += b.hand[i].upgraded;
            ironclad += card_def(b.hand[i].id).pool == CardPool::IRONCLAD;
        }
        check("stoke_generates_two_cards", generated, 2);
        check("stoke_upgraded_generates_upgraded_cards", upgraded, 2);
        check("stoke_generates_character_cards", ironclad, 2);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::DARK_EMBRACE, 1);
        for (int i = 0; i < 10; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        Card normal = make_card(CardId::BASH, false, 80);
        Card ethereal = make_card(CardId::DAZED, false, 81);
        b.move_to_exhaust(normal, false);
        check("dark_embrace_normal_exhaust_draws_now", b.handCount, 1);
        b.move_to_exhaust(ethereal, true);
        check("dark_embrace_ethereal_exhaust_deferred", b.handCount, 1);
        b.flush_ethereal_exhaust_hooks();
        check("dark_embrace_ethereal_settles_at_turn_end", b.handCount, 2);
    }
    {
        auto b = base();
        b.relics[b.relicCount] = static_cast<int>(RelicId::JOSS_PAPER);
        ++b.relicCount;
        for (int i = 0; i < 20; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        Card c = make_card(CardId::BASH, false, 80);
        for (int i = 0; i < 4; ++i) b.move_to_exhaust(c, true);
        check("joss_paper_ethereal_no_immediate_count", b.relicAux[0], 0);
        check("joss_paper_ethereal_no_immediate_draw", b.handCount, 0);
        b.flush_ethereal_exhaust_hooks();
        check("joss_paper_ethereal_settles_at_turn_end", b.relicAux[0], 4);
        check("joss_paper_below_threshold_no_draw", b.handCount, 0);
        b.move_to_exhaust(c, false);
        check("joss_paper_fifth_exhaust_draws", b.handCount, 1);
        check("joss_paper_threshold_wraps_to_zero", b.relicAux[0], 0);
        b.relicAux[0] = 6;
        b.move_to_exhaust(c, false);
        check("joss_paper_overflow_draws_floor", b.handCount, 2);
        check("joss_paper_overflow_remainder", b.relicAux[0], 2);
    }
    {
        // End-to-end ordering: an ethereal card is exhausted during discard_hand
        // and only then does Dark Embrace draw (before the next hand is dealt).
        auto b = base();
        b.add_player_power(PowerId::DARK_EMBRACE, 1);
        for (int i = 0; i < 12; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        hand(b, CardId::DAZED);
        b.end_player_turn();
        check("dark_embrace_ethereal_end_turn_hand_size", b.handCount, 6);
    }

    // ---------------------------------------------------------------- D13
    // PenNib's damage multiplier applies to AoE attacks too.
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::PEN_NIB);
        b.relicAux[0] = 9;
        hand(b, CardId::THUNDERCLAP);
        const int hp = b.monsters[0].hp;
        play(b);
        check("pen_nib_thunderclap_damage", hp - b.monsters[0].hp,
              2 * card_damage(make_card(CardId::THUNDERCLAP, false, 1)));
    }

    // ---------------------------------------------------------------- D14
    // CardCmd.AutoPlay enters the normal play lifecycle (counters + hooks).
    {
        auto b = base();
        b.add_player_power(PowerId::RAGE, 3);
        b.auto_play_random(make_card(CardId::STRIKE_IRONCLAD, false, 90), false);
        check("autoplay_counts_attack", b.attacksPlayedThisTurn, 1);
        check("autoplay_triggers_rage", b.player.block, 3);
    }

    // ---------------------------------------------------------------- D15
    // BlockPotion uses CreatureCmd.GainBlock, so block hooks still run.
    {
        auto b = base();
        b.add_player_power(PowerId::JUGGERNAUT, 5);
        const int hp = b.monsters[0].hp;
        b.apply_potion(PotionId::BLOCK_POTION, 0);
        check("block_potion_triggers_juggernaut", hp - b.monsters[0].hp, 5);
    }

    // ---------------------------------------------------------------- D16
    // ArtifactPower intercepts visible debuffs, including temporary strength
    // loss from Dark Shackles.
    {
        auto b = base();
        b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)] = 1;
        hand(b, CardId::DARK_SHACKLES);
        play(b);
        check("artifact_blocks_dark_shackles", b.monsters[0].strength, 0);
        check("artifact_consumed_by_dark_shackles",
              b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)], 0);
    }

    // ---------------------------------------------------------------- D17
    // A choice enumerates the complete legal candidate set, not just 10.
    {
        auto b = base();
        for (int i = 0; i < 15; ++i) {
            b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90 + i);
        }
        hand(b, CardId::HEADBUTT);
        play(b);
        check("headbutt_all_15_candidates", b.pending.count, 15);
    }
    {
        auto b = base();
        for (int i = 0; i < 15; ++i) {
            b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 90 + i);
        }
        hand(b, CardId::SECRET_TECHNIQUE);
        play(b);
        check("secret_technique_all_15_candidates", b.pending.count, 15);
    }

    // ---------------------------------------------------------------- D18
    // A rejected action reports failure and leaves the state untouched.
    {
        static_assert(std::is_trivially_copyable_v<BattleContext>);
        auto b = base();
        b.player.energy = 0;
        hand(b, CardId::STRIKE_IRONCLAD);
        BattleContext before = b;
        Action a;
        a.type = ActionType::PLAY_CARD;
        check("unaffordable_step_rejected", b.step(a), false);
        check("unaffordable_step_leaves_state",
              std::memcmp(&before, &b, sizeof(BattleContext)) == 0, 1);
    }
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::VELVET_CHOKER);
        b.cardsPlayedThisTurn = 6;
        hand(b, CardId::STRIKE_IRONCLAD);
        Action a;
        a.type = ActionType::PLAY_CARD;
        check("choker_seventh_step_rejected", b.step(a), false);
    }

    // ---------------------------------------------------------------- D19
    // Resampling only randomizes information the player does not have.
    {
        auto b = base();
        b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 90);
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 91);
        b.discard[b.discardCount++] = make_card(CardId::BASH, false, 92);
        hand(b, CardId::HEADBUTT);
        play(b);
        b.resolve_choice(92);
        check("headbutt_known_top_before",
              static_cast<int>(b.draw[b.drawCount - 1].id), static_cast<int>(CardId::BASH));
        int changed = 0;
        for (int seed = 1; seed <= 20; ++seed) {
            auto c = b;
            c.resample_hidden(seed);
            changed += c.draw[c.drawCount - 1].id != CardId::BASH ? 1 : 0;
        }
        check("resampling_preserves_known_top_20_seeds", changed, 0);
    }

    // ---------------------------------------------------------------- D20
    // Distinct decisions must not collapse to identical network inputs.
    {
        auto b = base();
        auto c = b;
        c.relics[c.relicCount++] = static_cast<int>(RelicId::ORICHALCUM);
        check("combat_obs_distinguishes_orichalcum",
              public_combat_observation(b) != public_combat_observation(c), 1);
    }
    {
        auto b = base();
        auto c = b;
        hand(b, CardId::STRIKE_IRONCLAD);
        hand(c, CardId::STRIKE_IRONCLAD);
        Card source = make_card(CardId::ARMAMENTS, false, 88);
        b.start_choice(ChoiceOp::UPGRADE, ChoicePile::HAND, 1, false, source, false);
        c.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, 1, false, source, false);
        check("combat_obs_distinguishes_choice_operation",
              public_combat_observation(b) != public_combat_observation(c), 1);
        Action a;
        a.type = ActionType::CHOOSE;
        a.uid = b.pending.cards[0].uid;
        check("action_feat_distinguishes_choice_operation",
              combat_action_features(b, a) != combat_action_features(c, a), 1);
    }

    // ---------------------------------------------------------------- D22
    // IntangiblePower caps both damage and HP loss, and expires after the
    // enemy turn it protected against.
    {
        auto b = base();
        b.add_player_power(PowerId::INTANGIBLE, 1);
        b.end_player_turn();
        check("intangible_expires", b.player_power(PowerId::INTANGIBLE), 0);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::INTANGIBLE, 1);
        const int hp = b.player.hp;
        b.lose_hp(6);
        check("intangible_caps_hp_loss", hp - b.player.hp, 1);
    }

    // ---------------------------------------------------------------- D24
    // Playability is data-driven: Slimed/Toxic are playable status cards while
    // flagged cards (Wound, Dazed) are not.
    {
        Card slime = make_card(CardId::SLIMED, false, 1);
        Card wound = make_card(CardId::WOUND, false, 2);
        Card dazed = make_card(CardId::DAZED, false, 3);
        check("slimed_is_playable", card_is_playable(slime), 1);
        check("wound_is_not_playable", card_is_playable(wound), 0);
        check("dazed_is_not_playable", card_is_playable(dazed), 0);
        auto b = base();
        hand(b, CardId::SLIMED);
        play(b);
        check("slimed_play_exhausts", b.exhaustCount, 1);
    }

    // ================= round-2 audit (R01-R14) and round-3 (T01-T16) ========
    // Each check names the C# source that fixes the rule.  States are isolated
    // (high HP/energy, cleared piles) so only the rule under test moves.
    auto copies = [](const BattleContext &b, std::uint16_t uid) {
        int n = 0;
        for (int i = 0; i < b.handCount; ++i) n += b.hand[i].uid == uid;
        for (int i = 0; i < b.drawCount; ++i) n += b.draw[i].uid == uid;
        for (int i = 0; i < b.discardCount; ++i) n += b.discard[i].uid == uid;
        for (int i = 0; i < b.exhaustCount; ++i) n += b.exhaust[i].uid == uid;
        for (int i = 0; i < b.returnNextTurnCount; ++i) n += b.returnNextTurn[i].uid == uid;
        return n;
    };
    auto choose_all = [](BattleContext &b) {
        int guard = 0;
        while (b.pending.op != ChoiceOp::NONE && guard++ < 16) {
            Action a;
            a.type = ActionType::CHOOSE;
            a.uid = b.pending.cards[0].uid;
            b.step(a);
        }
    };

    // ---------------------------------------------------------------- R01
    // CardCmd.AutoPlay -> OnPlayWrapper moves the one source entity to its
    // result pile after all plays.  An auto-played selector must not re-place
    // the source (the old auto_resolve_pending + finish double-moved it).
    {
        auto b = base();
        Card head = make_card(CardId::HEADBUTT, false, b.nextUid++);
        b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 700);
        b.auto_play_random(head, false);
        check("r01_autoplay_choice_source_once", copies(b, head.uid), 1);
    }
    {
        // BeatDown's captured cards leave the discard before AutoPlay; nested
        // Headbutt moving a later pick must not leave a second copy behind.
        auto b = base();
        Card head = make_card(CardId::HEADBUTT, false, b.nextUid++);
        b.discard[b.discardCount++] = head;
        b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 701);
        hand(b, CardId::BEAT_DOWN);
        play(b);
        check("r01_beatdown_headbutt_uid_once", copies(b, head.uid), 1);
    }

    // ---------------------------------------------------------------- R02
    // A selector closes inside OnPlayWrapper: AfterCardPlayed hooks (Letter
    // Opener) still run and EnergyCost.AfterCardPlayedCleanup restores cost.
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::LETTER_OPENER);
        hand(b, CardId::DEFEND_IRONCLAD);
        hand(b, CardId::DEFEND_IRONCLAD);
        hand(b, CardId::ARMAMENTS);
        play(b); play(b);
        const int hp = b.monsters[0].hp;
        play(b);           // Armaments opens the upgrade selector
        choose_all(b);
        check("r02_letter_opener_after_choice", hp - b.monsters[0].hp, 5);
    }
    {
        auto b = base();
        hand(b, CardId::ARMAMENTS);
        hand(b, CardId::STRIKE_IRONCLAD);
        card_set_turn_cost(b.hand[0], 0);
        play(b);
        choose_all(b);
        check("r02_choice_source_cost_restored",
              card_cost(b.discard[b.discardCount - 1]), 1);
    }

    // ---------------------------------------------------------------- R03
    // HellraiserPower / StampedePower call CardCmd.AutoPlay: counters and
    // AfterCardPlayed (Rage) must run.
    {
        auto b = base();
        b.add_player_power(PowerId::HELLRAISER, 1);
        b.add_player_power(PowerId::RAGE, 3);
        b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 702);
        b.draw_cards(1);
        check("r03_hellraiser_attack_count", b.attacksPlayedThisTurn, 1);
        check("r03_hellraiser_rage_block", b.player.block, 3);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::STAMPEDE, 1);
        hand(b, CardId::STRIKE_IRONCLAD);
        b.end_player_turn();
        check("r03_stampede_attack_count", b.attacksPlayedThisCombat, 1);
    }

    // ---------------------------------------------------------------- R04-R07
    // Replay/Duplication re-runs Before/AfterCardPlayed and history counters
    // per play; the selector of the second play must not overwrite the first;
    // auto-play honours Duplication; Duplication expires at turn end.
    {
        auto b = base();
        b.add_player_power(PowerId::DUPLICATION, 1);
        b.add_player_power(PowerId::RAGE, 3);
        hand(b, CardId::STRIKE_IRONCLAD);
        const int hp = b.monsters[0].hp;
        play(b);
        check("r04_duplication_damage", hp - b.monsters[0].hp, 12);
        check("r04_duplication_attack_count", b.attacksPlayedThisTurn, 2);
        check("r04_duplication_rage_block", b.player.block, 6);
    }
    {
        // Replay (enchantment) follows the same per-play loop as Duplication.
        auto b = base();
        hand(b, CardId::STRIKE_IRONCLAD);
        b.hand[0].replay = 1;
        const int hp = b.monsters[0].hp;
        play(b);
        check("r04_replay_damage", hp - b.monsters[0].hp, 12);
        check("r04_replay_play_count", b.cardsPlayedThisTurn, 2);
        check("r04_replay_source_once", b.discardCount, 1);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::DUPLICATION, 1);
        b.end_player_turn();
        check("r07_duplication_expires", b.player_power(PowerId::DUPLICATION), 0);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::DUPLICATION, 1);
        Card c = make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        const int hp = b.monsters[0].hp;
        b.auto_play_random(c, false);
        check("r06_autoplay_duplication_damage", hp - b.monsters[0].hp, 12);
        check("r06_autoplay_duplication_consumed", b.player_power(PowerId::DUPLICATION), 0);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::DUPLICATION, 1);
        b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 703);
        b.discard[b.discardCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 704);
        hand(b, CardId::HEADBUTT);
        play(b);
        choose_all(b);     // first play's selector
        choose_all(b);     // duplicated play's selector
        check("r05_duplicated_headbutt_two_returns", b.drawCount, 2);
    }

    // ---------------------------------------------------------------- R08
    // Bloodletting is Unblockable|Unpowered|Move damage: Rupture and Buffer
    // react, HP loss is 0 while Buffer holds.
    {
        auto b = base();
        b.add_player_power(PowerId::RUPTURE, 2);
        hand(b, CardId::BLOODLETTING);
        play(b);
        check("r08_bloodletting_rupture", b.player.strength, 2);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::BUFFER, 1);
        hand(b, CardId::BLOODLETTING);
        play(b);
        check("r08_bloodletting_buffer_hp", b.player.hp, 500);
        check("r08_bloodletting_buffer_consumed", b.player_power(PowerId::BUFFER), 0);
    }

    // ---------------------------------------------------------------- R09
    // ThornsPower.BeforeDamageReceived: powered attacks only, even fully
    // blocked; the reflect is Unpowered (blockable, no scaling).
    {
        auto b = base();
        b.monsters[0].power[static_cast<int>(PowerId::THORNS)] = 3;
        b.monsters[0].block = 20;
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("r09_thorns_fully_blocked", b.player.hp, 497);
    }
    {
        auto b = base();
        b.monsters[0].power[static_cast<int>(PowerId::THORNS)] = 3;
        b.player.block = 10;
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b);
        check("r09_thorns_hp", b.player.hp, 500);
        check("r09_thorns_blockable", b.player.block, 7);
    }
    {
        auto b = base();
        b.monsters[0].power[static_cast<int>(PowerId::THORNS)] = 3;
        b.apply_potion(PotionId::EXPLOSIVE_AMPOULE, 0);
        check("r09_thorns_ignores_unpowered", b.player.hp, 500);
    }

    // ---------------------------------------------------------------- R10/R11
    {
        auto b = base();
        b.player.energy = 3;
        b.add_player_power(PowerId::VIGOR, 5);
        hand(b, CardId::WHIRLWIND);
        const int hp = b.monsters[0].hp;
        play(b);
        check("r10_whirlwind_vigor_whole_command", hp - b.monsters[0].hp, 30);
    }
    {
        auto b = base();
        b.add_player_power(PowerId::NO_BLOCK, 1);
        hand(b, CardId::SECOND_WIND);
        hand(b, CardId::DEFEND_IRONCLAD);
        play(b);
        check("r11_second_wind_respects_no_block", b.player.block, 0);
    }

    // ---------------------------------------------------------------- R12
    {
        auto b = base();
        b.monsters[0].hp = b.monsters[0].maxHp = 10000;
        for (int i = 0; i < 9; ++i) hand(b, CardId::THE_BOMB_CARD);
        for (int i = 0; i < 9; ++i) play(b);
        check("r12_nine_bombs_registered", b.bombCount, 9);
        const int hp = b.monsters[0].hp;
        for (int i = 0; i < 3; ++i) b.end_player_turn();
        check("r12_nine_bombs_damage", hp - b.monsters[0].hp, 360);
    }

    // ---------------------------------------------------------------- R13/R14
    // Public observation must separate states that need different decisions,
    // and known-top bookkeeping must follow every draw-pile move.
    {
        auto a = base();
        auto c = a;
        c.bombCount = 1;
        c.bombTurns[0] = 1;
        c.bombDamage[0] = 40;
        check("r13_obs_bomb", public_combat_observation(a) != public_combat_observation(c), 1);
    }
    {
        auto a = base();
        a.add_card_to_draw_top(make_card(CardId::STRIKE_IRONCLAD, false, 710));
        a.add_card_to_draw_top(make_card(CardId::DEFEND_IRONCLAD, false, 711));
        auto c = a;
        std::swap(c.draw[0], c.draw[1]);
        check("r13_obs_known_top_order",
              public_combat_observation(a) != public_combat_observation(c), 1);
    }
    {
        auto a = base();
        hand(a, CardId::STRIKE_IRONCLAD);
        a.add_player_power(PowerId::PANACHE, 5);
        auto c = a;
        c.cardsPlayedThisTurn = 4;
        check("r13_obs_panache_counter",
              public_combat_observation(a) != public_combat_observation(c), 1);
    }
    {
        auto a = base();
        hand(a, CardId::STRIKE_IRONCLAD);
        auto c = a;
        c.hand[0].replay = 1;
        Action act;
        act.type = ActionType::PLAY_CARD;
        act.hand = 0;
        act.target = 0;
        const bool same = public_combat_observation(a) == public_combat_observation(c) &&
                          combat_action_features(a, act) == combat_action_features(c, act);
        check("r13_obs_replay_distinguishable", !same, 1);
    }
    {
        auto b = base();
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 712);
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 713);
        b.add_card_to_draw_top(make_card(CardId::STRIKE_IRONCLAD, false, 714));
        hand(b, CardId::SECRET_WEAPON);
        play(b);
        choose_all(b);
        check("r14_known_top_removed_by_tutor", b.knownTopCount, 0);
    }

    // ---------------------------------------------------------------- T01-T04
    {
        auto b = base();
        b.discard[b.discardCount++] = make_card(CardId::BASH, false, 720);
        b.apply_potion(PotionId::LIQUID_MEMORIES, 0);
        choose_all(b);
        check("t01_liquid_memories_free", card_cost(b.hand[0]), 0);
    }
    {
        auto b = base();
        for (int i = 0; i < 10; ++i) hand(b, CardId::DEFEND_IRONCLAD);
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 730 + i);
        b.apply_potion(PotionId::BOTTLED_POTENTIAL, 0);
        check("t02_bottled_potential_hand", b.handCount, 5);
        check("t02_bottled_potential_draw", b.drawCount, 15);
    }
    {
        auto b = base();
        for (int i = 0; i < 30; ++i) b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 740 + i);
        b.apply_potion(PotionId::CLARITY, 0);
        check("t03_clarity_immediate", b.handCount, 1);
        b.end_player_turn();
        check("t03_clarity_next_turn_draw", b.handCount, 6);
    }
    {
        auto b = base();
        b.player.energy = 3;
        b.apply_potion(PotionId::RADIANT_TINCTURE, 0);
        check("t04_radiance_immediate", b.player.energy, 4);
        b.end_player_turn();
        check("t04_radiance_next_turn", b.player.energy, 4);
    }

    // ---------------------------------------------------------------- T05-T08
    {
        auto b = base();
        b.apply_potion(PotionId::SHACKLING_POTION, 0);
        check("t05_shackling_negative", b.monsters[0].strength, -7);
        auto c = base();
        c.monsters[0].strength = 3;
        c.apply_potion(PotionId::SHACKLING_POTION, 0);
        check("t05_shackling_from_three", c.monsters[0].strength, -4);
        c.end_player_turn();
        check("t05_shackling_restored", c.monsters[0].strength, 3);
    }
    {
        auto b = base();
        b.apply_potion(PotionId::HEART_OF_IRON, 0);
        b.end_player_turn();
        check("t06_player_plating_decays", b.player_power(PowerId::PLATING), 6);
    }
    {
        // The typed potions offer only Ironclad-pool cards; Colorless offers
        // the whole colorless pool; both may be skipped.
        int nonColorless = 0;
        int nonSkills = 0;
        bool optional = false;
        for (int seed = 0; seed < 60; ++seed) {
            BattleContext b;
            Card deck[20];
            for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
            b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 80000 + seed, deck, 20, 0, 500, 500);
            b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
            b.apply_potion(PotionId::ATTACK_POTION, 0);
            optional = optional || b.pending.optional;
            for (int j = 0; j < b.pending.count; ++j) {
                nonColorless += static_cast<int>(b.pending.cards[j].id) > static_cast<int>(CardId::WHIRLWIND);
            }
            BattleContext c = b;  // rebuild for the colorless sample
            c = BattleContext();
            c.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 80000 + seed, deck, 20, 0, 500, 500);
            c.handCount = c.drawCount = c.discardCount = c.exhaustCount = 0;
            c.apply_potion(PotionId::COLORLESS_POTION, 0);
            for (int j = 0; j < c.pending.count; ++j) {
                nonSkills += card_is_skill(c.pending.cards[j]) ? 0 : 1;
            }
        }
        check("t07_attack_potion_ironclad_pool", nonColorless, 0);
        check("t07_colorless_pool_any_type", nonSkills > 0, 1);
        check("t08_potion_offer_can_skip", optional, 1);
    }

    // ---------------------------------------------------------------- T09-T12
    {
        auto b = base();
        for (int i = 0; i < 3; ++i) b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 750 + i);
        const int hp = b.monsters[0].hp;
        b.apply_potion(PotionId::DISTILLED_CHAOS, 0);
        check("t09_distilled_chaos_shuffles", hp - b.monsters[0].hp, 18);
    }
    {
        auto b = base();
        b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 753);
        hand(b, CardId::HAVOC);
        const int hp = b.monsters[0].hp;
        play(b);
        check("t09_havoc_shuffles", hp - b.monsters[0].hp, 6);
    }
    {
        auto b = base();
        b.monsters[0].power[static_cast<int>(PowerId::ARTIFACT)] = 1;
        b.apply_potion(PotionId::BEETLE_JUICE, 0);
        check("t10_beetle_artifact_blocks", b.monster_power(0, PowerId::SHRINK), 0);
        check("t10_beetle_consumes_artifact", b.monster_power(0, PowerId::ARTIFACT), 0);
        auto c = base();
        c.add_player_power(PowerId::ARTIFACT, 1);
        hand(c, CardId::DOUBT);
        c.discard_hand();
        check("t10_player_artifact_blocks_curse", c.player.weak, 0);
        check("t10_player_artifact_consumed", c.player_power(PowerId::ARTIFACT), 0);
    }
    {
        auto b = base();
        b.player.hp = 20;
        b.monsters[0].hp = 10;
        b.apply_potion(PotionId::FOUL_POTION, 0);
        check("t11_foul_potion_still_self_damages", b.player.hp, 8);
    }
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::SELF_FORMING_CLAY);
        b.damage_player(1);
        b.damage_player(1);
        b.start_player_turn();
        check("t12_self_forming_clay_stacks", b.player.block, 6);
    }

    // ---------------------------------------------------------------- T13-T16
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::RUINED_HELMET);
        b.apply_potion(PotionId::STRENGTH_POTION, 0);
        check("t13_strength_potion_ruined_helmet", b.player.strength, 4);
    }
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::THE_BOOT);
        b.monsters[0].block = 5;
        hand(b, CardId::STRIKE_IRONCLAD);
        const int hp = b.monsters[0].hp;
        play(b);
        check("a01_boot_after_block", hp - b.monsters[0].hp, 5);
    }
    {
        RunContext r;
        r.init(1, 0);
        r.add_relic(RelicId::PANTOGRAPH);
        r.hp = 30;
        r.combatIsBoss = true;
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        check("t14_pantograph_on_boss_entry", r.battle.player.hp, 55);
    }
    {
        RunContext r;
        r.init(1, 0);
        r.begin_combat(Encounter::SETUP_DENSE_VEGETATION);
        r.eventCombat = true;
        r.eventReturnPage = -1;
        r.battle.player.hp = 30;
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check("t15_event_victory_burning_blood", r.hp, 36);
    }
    {
        // A debuff applied to the player skips its first duration tick
        // (PowerCmd.Apply -> SkipNextDurationTick).
        auto b = base();
        b.add_player_power(PowerId::WEAK, 1);
        b.add_player_power(PowerId::FRAIL, 1);
        b.end_player_turn();
        check("t16_first_weak_survives", b.player.weak, 1);
        check("t16_first_frail_survives", b.player.frail, 1);
        b.end_player_turn();
        check("t16_weak_ticks_next_turn", b.player.weak, 0);
    }

    // ---------------------------------------------------------------- A02
    {
        auto b = base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::HISTORY_COURSE);
        hand(b, CardId::STRIKE_IRONCLAD);
        const std::uint16_t uid = b.hand[0].uid;
        play(b);
        b.end_player_turn();
        check("a02_history_course_new_uid", copies(b, uid), 1);
        const int hp = b.monsters[0].hp;
        b.end_player_turn();  // idle previous turn: nothing to replay
        check("a02_history_course_no_repeat", hp - b.monsters[0].hp, 0);
    }

    // ------------------------------------------------ round 6 audit fixes
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::MUMMIFIED_HAND);
        audit_hand(b, CardId::INFLAME);
        audit_hand(b, CardId::WHIRLWIND);
        audit_play(b);
        int cost = -999;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].id == CardId::WHIRLWIND) cost = card_cost(b.hand[i]);
        }
        check("r6_mummified_x_stays_x", cost, -1);
    }
    {
        auto b = audit_base();
        const Rng monsterBefore = b.monsterAiRng;
        const Rng selectionBefore = b.cardSelectionRng;
        b.relics[b.relicCount++] = static_cast<int>(RelicId::MUMMIFIED_HAND);
        audit_hand(b, CardId::INFLAME);
        audit_hand(b, CardId::BASH);
        audit_play(b);
        check("r6_rng_selection_advances",
              std::memcmp(&selectionBefore, &b.cardSelectionRng, sizeof(Rng)) != 0, 1);
        check("r6_rng_monster_ai_independent",
              std::memcmp(&monsterBefore, &b.monsterAiRng, sizeof(Rng)), 0);
    }
    {
        auto b = audit_base();
        b.relics[b.relicCount++] = static_cast<int>(RelicId::PEN_NIB);
        relic_aux_set(b, RelicId::PEN_NIB, 9);
        audit_hand(b, CardId::FLASH_OF_STEEL);
        const int hp = b.monsters[0].hp;
        audit_play(b);
        check("r6_colorless_attack_from_card", hp - b.monsters[0].hp, 10);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_EXOSKELETONS_WEAK, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::EXOSKELETON);
        b.monsters[m].hp = b.monsters[m].maxHp = 30;
        const DamageDealt d = b.damage_monster(m, 15, true, true);
        check("r6_hard_to_kill_hp", 30 - b.monsters[m].hp, 9);
        check("r6_hard_to_kill_result", d.unblocked, 9);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_INKLETS_NORMAL, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::INKLET);
        b.monsters[m].hp = b.monsters[m].maxHp = 20;
        b.damage_monster(m, 6, true, true);
        check("r6_slippery_cap", 20 - b.monsters[m].hp, 1);
        check("r6_slippery_decrement", b.monster_power(m, PowerId::SLIPPERY), 0);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_AXEBOTS_NORMAL, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::AXEBOT);
        b.damage_monster(m, 10000, true, true);
        check("r6_stock_respawns", b.monsters[m].alive, 1);
        check("r6_stock_decrements", b.monster_power(m, PowerId::STOCK), 1);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_PHROG_PARASITE_ELITE, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::PHROG_PARASITE);
        b.damage_monster(m, 10000, true, true);
        check("r6_infested_continues", static_cast<int>(b.outcome),
              static_cast<int>(Outcome::UNDECIDED));
        check("r6_infested_four_wrigglers",
              audit_alive_count(b, MonsterId::WRIGGLER), 4);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_SCROLLS_OF_BITING_WEAK, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::SCROLL_OF_BITING);
        b.player.block = 0;
        b.monster_attack_player(m, 1);
        check("r6_paper_cuts_max_hp", b.player.maxHp, 498);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_BYRDONIS_ELITE, 1234, deck, 20, 0, 500, 500);
        b.end_player_turn();
        const int m = audit_find(b, MonsterId::BYRDONIS);
        check("r6_territorial_strength", b.monsters[m].strength, 1);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_TURRET_OPERATOR_WEAK, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::TURRET_OPERATOR);
        b.monsters[m].block = 0;
        b.start_player_turn();
        check("r6_rampart_turret_block", b.monsters[m].block, 25);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_SLUMBERING_BEETLE_NORMAL, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::SLUMBERING_BEETLE);
        b.end_player_turn();
        check("r6_slumber_ticks", b.monster_power(m, PowerId::SLUMBER), 2);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_INFESTED_PRISMS_ELITE, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::INFESTED_PRISM);
        b.player.energy = 3;
        b.attack_monster(m, 5, 1, true);
        check("r6_vital_spark_energy", b.player.energy, 4);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_ENTOMANCER_ELITE, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::ENTOMANCER);
        b.attack_monster(m, 5, 1, true);
        check("r6_personal_hive_dazed",
              audit_count_card(b.draw, b.drawCount, CardId::DAZED), 1);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_BOWLBUGS_NORMAL, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::BOWLBUG_ROCK);
        b.player.block = 500;
        b.end_player_turn();
        check("r6_bowlbug_off_balance", b.monsters[m].move, 2);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_DECIMILLIPEDE_ELITE, 1234, deck, 20, 0, 500, 500);
        const int m = audit_find(b, MonsterId::DECIMILLIPEDE_SEGMENT);
        b.damage_monster(m, 10000, true, true);
        check("r6_decimillipede_revives", b.monsters[m].reviving, 1);
        b.end_player_turn();
        b.end_player_turn();
        check("r6_decimillipede_reattaches", b.monsters[m].reviving, 0);
        check("r6_decimillipede_heals", b.monsters[m].hp, 25);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_THIEVING_HOPPER_WEAK, 1234, deck, 20, 0, 5000, 5000);
        const int m = audit_find(b, MonsterId::THIEVING_HOPPER);
        for (int i = 0; i < 5 && b.outcome == Outcome::UNDECIDED; ++i) {
            b.end_player_turn();
        }
        check("r6_hopper_escape_removes", b.monsters[m].alive, 0);
        check("r6_hopper_escape_victory", static_cast<int>(b.outcome),
              static_cast<int>(Outcome::PLAYER_VICTORY));
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_DOORMAKER_BOSS, 1234, deck, 20, 0, 5000, 5000);
        const int door = audit_find(b, MonsterId::DOOR);
        b.damage_monster(door, 10000, true, true);
        check("r6_door_phase_not_victory", static_cast<int>(b.outcome),
              static_cast<int>(Outcome::UNDECIDED));
        check("r6_door_phase_doormaker",
              audit_alive_count(b, MonsterId::DOORMAKER), 1);
        const int maker = audit_find(b, MonsterId::DOORMAKER);
        check("r6_doormaker_initial_move", b.monsters[maker].move, 0);
        b.end_player_turn();
        check("r6_doormaker_after_intro", b.monsters[maker].move, 1);
        b.end_player_turn();
        check("r6_doormaker_after_beam", b.monsters[maker].move, 2);
        b.end_player_turn();
        check("r6_doormaker_returns_to_door", b.monsters[door].reviving, 0);
        check("r6_doormaker_departs",
              audit_alive_count(b, MonsterId::DOORMAKER), 0);
    }
    {
        auto a = audit_base();
        a.add_player_power(PowerId::AUTOMATION, 1);
        a.automationLeft[0] = 10;
        auto b = a;
        b.automationLeft[0] = 1;
        check("r6_observation_automation_progress",
              public_combat_observation(a) != public_combat_observation(b), 1);
        a.unblockedHitsThisCombat = 0;
        b = a;
        b.unblockedHitsThisCombat = 3;
        check("r6_observation_unblocked_hits",
              public_combat_observation(a) != public_combat_observation(b), 1);
        a.cardsPlayedThisCombat = 0;
        b = a;
        b.cardsPlayedThisCombat = 10;
        check("r6_observation_cards_played",
              public_combat_observation(a) != public_combat_observation(b), 1);
    }
    {
        RunContext plain;
        RunContext member;
        plain.init(610001, 0);
        member.init(610001, 0);
        member.add_relic(RelicId::MEMBERSHIP_CARD);
        plain.roll_shop();
        member.roll_shop();
        check("r6_membership_discount", member.shopPrices[0],
              plain.shopPrices[0] / 2);
    }
    {
        RunContext r;
        r.init(610005, 0);
        r.begin_combat(Encounter::SETUP_DENSE_VEGETATION);
        const Rng selectionBefore = r.runRng[RNG_COMBAT_CARD_SELECTION];
        const Rng monsterBefore = r.battle.monsterAiRng;
        (void) r.battle.cardSelectionRng.next_int(0, 10);
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check("r6_rng_selection_persists",
              std::memcmp(&selectionBefore, &r.runRng[RNG_COMBAT_CARD_SELECTION],
                          sizeof(Rng)) != 0, 1);
        check("r6_rng_ai_not_perturbed",
              std::memcmp(&monsterBefore, &r.runRng[RNG_MONSTER_AI], sizeof(Rng)), 0);
    }
    {
        RunContext plain;
        RunContext courier;
        plain.init(610002, 0);
        courier.init(610002, 0);
        courier.add_relic(RelicId::THE_COURIER);
        plain.roll_shop();
        courier.roll_shop();
        courier.screen = RunScreen::SHOP;
        check("r6_courier_discount", courier.shopPrices[0],
              plain.shopPrices[0] * 4 / 5);
        courier.gold = 9999;
        check("r6_courier_purchase", courier.step({RunActionType::BUY_CARD, 0}), 1);
        check("r6_courier_refill", courier.shopSold[0], 0);
    }
    {
        RunContext r;
        r.init(610006, 0);
        r.roll_shop();
        r.screen = RunScreen::SHOP;
        const int before = r.shopPrices[0];
        r.shopRelics[0] = static_cast<int>(RelicId::THE_COURIER);
        r.shopRelicPrices[0] = 100;
        r.shopRelicSold[0] = false;
        r.shopRelicCount = std::max(1, r.shopRelicCount);
        r.gold = 9999;
        check("r6_courier_purchase_from_shop",
              r.step({RunActionType::BUY_RELIC, 0}), 1);
        check("r6_courier_discount_applies_immediately", r.shopPrices[0],
              before * 4 / 5);
    }
    {
        RunContext r;
        r.init(610003, 0);
        r.add_relic(RelicId::LAVA_LAMP);
        r.begin_combat(Encounter::SETUP_DENSE_VEGETATION);
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        int unupgraded = 0;
        for (int i = 0; i < r.offeredCount; ++i) {
            unupgraded += card_upgradable(r.offered[i]) && !r.offered[i].upgraded;
        }
        check("r6_lava_lamp_reward_upgrades", unupgraded, 0);
    }
    {
        RunContext r;
        r.init(610004, 0);
        r.add_relic(RelicId::PLANISPHERE);
        r.hp = 50;
        r.map.nodes[r.map.startIdx].type = static_cast<int>(MapPointType::UNKNOWN);
        r.enter_map_point(r.map.startIdx);
        check("r6_planisphere_unknown_heal", r.hp, 54);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_GLOBE_HEAD_NORMAL, 1234, deck, 20, 0, 500, 500);
        b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
        b.knownTopCount = 0;
        b.add_card_to_hand(make_card(CardId::INFLAME, false, b.nextUid++));
        const int m = audit_find(b, MonsterId::GLOBE_HEAD);
        check("r6_galvanic_active",
              b.monster_power(m, PowerId::GALVANIC), 6);
        check("r6_galvanic_applied", b.hand[0].galvanized, 6);
        Action play_inflame;
        play_inflame.type = ActionType::PLAY_CARD;
        play_inflame.hand = 0;
        play_inflame.target = 0;
        check("r6_galvanized_power_playable", b.step(play_inflame), 1);
        check("r6_galvanized_power_damage", b.player.hp, 494);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_THE_LOST_AND_FORGOTTEN_NORMAL, 1234, deck, 20, 0, 500, 500);
        const int lost = audit_find(b, MonsterId::THE_LOST);
        const int forgotten = audit_find(b, MonsterId::THE_FORGOTTEN);
        monster_act(b, b.monsters[lost]);
        monster_act(b, b.monsters[forgotten]);
        check("r6_possess_steals_strength", b.player.strength, -2);
        check("r6_possess_steals_dexterity", b.player.dexterity, -2);
        b.damage_monster(lost, 10000, true, true);
        b.damage_monster(forgotten, 10000, true, true);
        check("r6_possess_restores_strength", b.player.strength, 0);
        check("r6_possess_restores_dexterity", b.player.dexterity, 0);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_KAISER_CRAB_BOSS, 1234, deck, 20, 0, 500, 500);
        const int rage = 0;
        const int victim = 1;
        b.damage_monster(victim, 10000, true, true);
        check("r6_crab_rage_strength", b.monsters[rage].strength, 5);
        check("r6_crab_rage_block", b.monsters[rage].block, 99);
        check("r6_crab_rage_consumed",
              b.monster_power(rage, PowerId::CRAB_RAGE), 0);
    }

    // --------------------------------------------------------- upgrade contract
    // CardModel.IsUpgradable is data-driven. Every canonical upgrade
    // transformation must make the card eligible, including cost and keyword
    // only upgrades.
    {
        const CardId upgrades[] = {
            CardId::AGGRESSION_CARD, CardId::BARRICADE_CARD, CardId::DARK_EMBRACE_CARD,
            CardId::HAVOC, CardId::HELLRAISER_CARD, CardId::INFERNAL_BLADE,
            CardId::JUGGLING_CARD, CardId::STOKE, CardId::TANK_CARD, CardId::UNMOVABLE,
            CardId::ALCHEMIZE, CardId::ANOINTED, CardId::BEACON_OF_HOPE,
            CardId::CALAMITY_CARD, CardId::DISCOVERY, CardId::MAYHEM_CARD,
            CardId::NOSTALGIA_CARD, CardId::PROLONG, CardId::SCRAWL,
            CardId::SECRET_TECHNIQUE, CardId::SECRET_WEAPON, CardId::STRATAGEM,
            CardId::APOTHEOSIS, CardId::DISTRACTION, CardId::ENTRENCH,
            CardId::HELLO_WORLD_CARD, CardId::WISH
        };
        int mismatches = 0;
        for (CardId id : upgrades) {
            if (!card_upgradable(make_card(id, false, 1))) ++mismatches;
            if (card_upgradable(make_card(id, true, 2))) ++mismatches;
        }
        check("r7_27_cost_or_keyword_upgrades_are_eligible", mismatches, 0);
        check("r7_cost_only_upgrade_is_eligible",
              card_upgradable(make_card(CardId::BARRICADE_CARD, false, 3)), 1);
        check("r7_keyword_only_upgrade_is_eligible",
              card_upgradable(make_card(CardId::AGGRESSION_CARD, false, 4)), 1);
    }

    // ---------------------------------------------------------------- card pools
    // CardFactory.FilterForCombat excludes Basic, Ancient and Event cards.
    // Random combat generation for Ironclad may use Ironclad plus Colorless
    // common/uncommon/rare cards only.
    {
        check("r7_card_pool_event_identity",
              card_def(CardId::BYRD_SWOOP).pool == CardPool::EVENT &&
                      card_def(CardId::BYRD_SWOOP).rarity == Rarity::EVENT,
              1);
        check("r7_card_pool_status_identity",
              card_def(CardId::BECKON).pool == CardPool::STATUS &&
                      card_def(CardId::BECKON).rarity == Rarity::STATUS,
              1);
        check("r7_card_pool_token_identity",
              card_def(CardId::GIANT_ROCK).pool == CardPool::TOKEN &&
                      card_def(CardId::GIANT_ROCK).rarity == Rarity::STATUS,
              1);
    }
    {
        int badSkills = 0;
        int badTransforms = 0;
        for (std::uint32_t seed = 0; seed < 1000; ++seed) {
            BattleContext b;
            b.cardGenerationRng = Rng(seed);
            const Card generated = b.random_card_of_type(CardType::SKILL, true);
            const CardDef &generatedDef = card_def(generated.id);
            const bool validPool = generatedDef.pool == CardPool::IRONCLAD ||
                                   generatedDef.pool == CardPool::COLORLESS;
            const bool validRarity =
                generatedDef.rarity == Rarity::COMMON ||
                generatedDef.rarity == Rarity::UNCOMMON ||
                generatedDef.rarity == Rarity::RARE;
            badSkills += validPool && validRarity ? 0 : 1;

            Card original = make_card(CardId::STRIKE_IRONCLAD, false, 1);
            b.transform_card(original);
            const CardDef &transformedDef = card_def(original.id);
            const bool sameSource = original.id == CardId::STRIKE_IRONCLAD;
            const bool transformedValid =
                !sameSource && transformedDef.pool == CardPool::IRONCLAD &&
                transformedDef.rarity != Rarity::BASIC &&
                transformedDef.rarity != Rarity::ANCIENT &&
                transformedDef.rarity != Rarity::EVENT;
            badTransforms += transformedValid ? 0 : 1;
        }
        check("r7_combat_card_generation_uses_filtered_pools", badSkills, 0);
        check("r7_combat_transform_stays_in_source_pool", badTransforms, 0);
    }
    {
        int invalidOffers = 0;
        for (std::uint32_t seed = 0; seed < 500; ++seed) {
            BattleContext b;
            b.cardGenerationRng = Rng(seed);
            b.apply_potion(PotionId::ATTACK_POTION, 0);
            for (int i = 0; i < b.pending.count; ++i) {
                const CardDef &d = card_def(b.pending.cards[i].id);
                if (d.pool != CardPool::IRONCLAD || d.type != CardType::ATTACK ||
                    d.rarity == Rarity::BASIC || d.rarity == Rarity::ANCIENT ||
                    d.rarity == Rarity::EVENT) {
                    ++invalidOffers;
                }
            }
        }
        check("r7_attack_potion_offer_uses_filtered_pool", invalidOffers, 0);
    }
    {
        int ancientAfterTransform = 0;
        for (std::uint32_t seed = 0; seed < 200; ++seed) {
            RunContext r;
            r.init(seed, 0);
            r.add_relic(RelicId::NEW_LEAF);
            for (int i = 0; i < r.deckCount; ++i) {
                const CardDef &d = card_def(r.deck[i].id);
                if (d.rarity == Rarity::ANCIENT || d.rarity == Rarity::EVENT ||
                    d.pool == CardPool::EVENT) {
                    ++ancientAfterTransform;
                }
            }
        }
        check("r7_run_transform_excludes_ancient_and_event", ancientAfterTransform, 0);
    }

    // ----------------------------------------------------------- reward odds
    {
        int rare = 0;
        int total = 0;
        for (std::uint32_t seed = 0; seed < 2000; ++seed) {
            RunContext r;
            r.playerRng[PRNG_REWARDS] = Rng(seed);
            r.combatIsElite = true;
            r.roll_card_reward(false);
            total += r.offeredCount;
            for (int i = 0; i < r.offeredCount; ++i) {
                rare += card_def(r.offered[i].id).rarity == Rarity::RARE ? 1 : 0;
            }
        }
        const int ratePerMille = total > 0 ? rare * 1000 / total : 0;
        check("r7_elite_reward_rare_rate_in_range",
              ratePerMille >= 45 && ratePerMille <= 75, 1);
        RunContext first;
        first.playerRng[PRNG_REWARDS] = Rng(14);
        first.combatIsElite = true;
        first.roll_card_reward(false);
        check("r7_elite_reward_uses_elite_rare_threshold",
              card_def(first.offered[0].id).rarity == Rarity::RARE, 1);
    }
    {
        RunContext r;
        r.cardRarityOdds = 0.2f;
        r.roll_card_reward(true);
        check("r7_boss_reward_resets_rarity_offset",
              static_cast<int>(r.cardRarityOdds * 1000.0f), -50);
    }
    {
        RunContext r;
        r.add_relic(RelicId::SILVER_CRUCIBLE);
        r.roll_card_reward(false);
        int upgraded = 0;
        for (int i = 0; i < r.offeredCount; ++i) upgraded += r.offered[i].upgraded ? 1 : 0;
        check("r7_silver_crucible_upgrades_offer", upgraded, 3);
        check("r7_silver_crucible_consumes_use", r.silverCrucibleUses, 2);
    }
    {
        RunContext low;
        low.playerRng[PRNG_SHOPS] = Rng(991);
        low.cardRarityOdds = -0.05f;
        RunContext high = low;
        high.cardRarityOdds = 0.4f;
        low.roll_shop();
        high.roll_shop();
        bool sameCards = low.shopCount == high.shopCount;
        for (int i = 0; i < low.shopCount && sameCards; ++i) {
            sameCards &= low.shopCards[i].id == high.shopCards[i].id;
        }
        check("shop_uses_current_reward_rarity_offset", sameCards, 0);
        check("shop_does_not_change_future_rarity_offset",
              low.cardRarityOdds == -0.05f && high.cardRarityOdds == 0.4f, 1);
    }

    // ------------------------------------------------------------ event fixes
    {
        RunContext r;
        r.init(930001, 0);
        r.gold = 500;
        event_begin(r, event_id("ROOM_FULL_OF_CHEESE"), false);
        event_choose(r, 0);
        int nonCommon = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            if (r.deck[i].id != CardId::STRIKE_IRONCLAD &&
                r.deck[i].id != CardId::DEFEND_IRONCLAD &&
                r.deck[i].id != CardId::BASH &&
                card_def(r.deck[i].id).rarity != Rarity::COMMON) {
                ++nonCommon;
            }
        }
        check("r7_common_card_event_only_adds_common", nonCommon, 0);
    }
    {
        RunContext r;
        r.init(930002, 0);
        r.hp = 20;
        r.maxHp = 100;
        event_begin(r, event_id("DENSE_VEGETATION"), false);
        event_choose(r, 1);
        check("r7_dense_vegetation_rest_heals_thirty_percent", r.hp, 50);
    }
    {
        RunContext r;
        r.init(930003, 0);
        event_begin(r, event_id("SPIRIT_GRAFTER"), false);
        event_choose(r, 0);
        int metamorphosis = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            metamorphosis += r.deck[i].id == CardId::METAMORPHOSIS ? 1 : 0;
        }
        check("r7_spirit_grafter_adds_metamorphosis", metamorphosis, 1);
    }
    {
        RunContext r;
        r.init(930004, 0);
        r.gold = 500;
        event_begin(r, event_id("WELCOME_TO_WONGOS"), false);
        event_choose(r, 0);
        int nonCommon = 0;
        for (int i = 0; i < r.relicCount; ++i) {
            const RelicId id = static_cast<RelicId>(r.relics[i]);
            if (id == RelicId::BURNING_BLOOD) continue;
            if (relic_def(id).rarity != Rarity::COMMON) ++nonCommon;
        }
        check("r7_wongo_bargain_relic_is_common", nonCommon, 0);
    }
    {
        RunContext r;
        r.init(930005, 0);
        r.potionCount = 0;
        event_begin(r, event_id("WELLSPRING"), false);
        const std::int64_t before = r.playerRng[PRNG_REWARDS].counter;
        event_choose(r, 0);
        check("r7_wellspring_uses_reward_rng",
              r.playerRng[PRNG_REWARDS].counter > before, 1);
    }
    {
        RunContext r;
        r.init(930006, 0);
        r.potionCount = 0;
        event_begin(r, event_id("POTION_COURIER"), false);
        const std::int64_t before = r.playerRng[PRNG_REWARDS].counter;
        event_choose(r, 1);
        check("r7_potion_courier_uses_reward_rng",
              r.playerRng[PRNG_REWARDS].counter > before, 1);
    }
    {
        RunContext r;
        r.init(930007, 0);
        r.add_relic(RelicId::JEWELRY_BOX);
        int apotheosis = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            apotheosis += r.deck[i].id == CardId::APOTHEOSIS ? 1 : 0;
        }
        check("r7_jewelry_box_adds_apotheosis", apotheosis, 1);
    }

    // ------------------------------------------------------------ event cards
    // EventCardPool cards use the same OnPlay lifecycle as reward cards; being
    // outside ordinary reward pools must not turn them into no-op cards.
    {
        auto b = audit_base();
        b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        Card apotheosis = make_card(CardId::APOTHEOSIS, false, b.nextUid++);
        b.play_card_effect(apotheosis, 0);
        check("r7_apotheosis_upgrades_all_piles",
              b.hand[0].upgraded && b.draw[0].upgraded, 1);
    }
    {
        auto b = audit_base();
        Card apparition = make_card(CardId::APPARITION, false, b.nextUid++);
        b.play_card_effect(apparition, 0);
        Card caltrops = make_card(CardId::CALTROPS, false, b.nextUid++);
        b.play_card_effect(caltrops, 0);
        check("r7_apparition_applies_intangible",
              b.player_power(PowerId::INTANGIBLE), 1);
        check("r7_caltrops_applies_thorns", b.player_power(PowerId::THORNS), 3);
    }
    {
        auto b = audit_base();
        b.hand[b.handCount++] = make_card(CardId::CLASH, false, b.nextUid++);
        b.hand[b.handCount++] =
            make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        Action playClash;
        playClash.type = ActionType::PLAY_CARD;
        playClash.hand = 0;
        playClash.target = 0;
        check("r7_clash_requires_all_attacks", b.step(playClash), 0);
    }
    {
        struct Case {
            CardId id;
            int expectedDamage;
            const char *name;
        };
        const Case cases[] = {
            {CardId::EXTERMINATE, 12, "r7_exterminate_hits_four_times"},
            {CardId::PECK, 6, "r7_peck_hits_three_times"},
            {CardId::MAUL, 10, "r7_maul_hits_twice"},
            {CardId::RIP_AND_TEAR, 14, "r7_rip_and_tear_hits_twice"},
        };
        for (const Case &item : cases) {
            auto b = audit_base();
            b.monsters[0].hp = b.monsters[0].maxHp = 100;
            Card eventAttack = make_card(item.id, false, b.nextUid++);
            b.play_card_effect(eventAttack, 0);
            check(item.name, 100 - b.monsters[0].hp, item.expectedDamage);
        }
    }
    {
        auto b = audit_base();
        Card frenzy = make_card(CardId::FEEDING_FRENZY_CARD, false, b.nextUid++);
        b.play_card_effect(frenzy, 0);
        check("r7_feeding_frenzy_is_temporary_strength",
              b.player_power(PowerId::STRENGTH), 5);
        b.end_player_turn();
        check("r7_feeding_frenzy_strength_expires", b.player.strength, 0);
    }
    {
        auto b = audit_base();
        b.discard[b.discardCount++] =
            make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        Card fury = make_card(CardId::NEOWS_FURY, false, b.nextUid++);
        b.play_card_effect(fury, 0);
        check("r7_neows_fury_returns_discard_card", b.handCount, 1);
    }
    {
        auto b = audit_base();
        for (int i = 0; i < 3; ++i) {
            b.discard[b.discardCount++] =
                make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        }
        Card stack = make_card(CardId::STACK, false, b.nextUid++);
        b.play_card_effect(stack, 0);
        check("r7_stack_scales_with_discard", b.player.block, 3);
    }
    {
        auto b = audit_base();
        b.hand[b.handCount++] = make_card(CardId::REBOUND, false, b.nextUid++);
        b.hand[b.handCount++] = make_card(CardId::ANGER, false, b.nextUid++);
        b.play_card(0, 0);
        b.play_card(0, 0);
        check("r7_rebound_moves_next_card_to_draw",
              b.drawCount > 0 && b.draw[b.drawCount - 1].id == CardId::ANGER, 1);
    }
    {
        auto b = audit_base();
        b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        Card wish = make_card(CardId::WISH, false, b.nextUid++);
        b.play_card_effect(wish, 0);
        check("r7_wish_starts_draw_pile_choice",
              b.pending.op == ChoiceOp::DRAW_TO_HAND, 1);
    }
    {
        auto b = audit_base();
        Card distraction = make_card(CardId::DISTRACTION, false, b.nextUid++);
        b.play_card_effect(distraction, 0);
        check("r7_distraction_adds_free_skill",
              b.handCount == 1 && card_is_skill(b.hand[0]) &&
                      card_cost(b.hand[0]) == 0,
              1);
    }
    {
        auto b = audit_base();
        hand(b, CardId::STRIKE_IRONCLAD);
        Card enlightenment = make_card(CardId::ENLIGHTENMENT, false, b.nextUid++);
        b.play_card_effect(enlightenment, 0);
        check("r7_enlightenment_caps_hand_cost", card_cost(b.hand[0]), 1);
    }
    {
        auto b = audit_base();
        b.handCount = b.drawCount = b.discardCount = 0;
        Card helloWorld = make_card(CardId::HELLO_WORLD_CARD, false, b.nextUid++);
        b.play_card_effect(helloWorld, 0);
        b.start_player_turn();
        const CardDef &d = card_def(b.hand[0].id);
        check("r7_hello_world_adds_ironclad_common",
              b.handCount == 1 && d.pool == CardPool::IRONCLAD &&
                      d.rarity == Rarity::COMMON,
              1);
    }
    {
        auto b = audit_base();
        b.handCount = b.drawCount = b.discardCount = 0;
        Card metamorphosis = make_card(CardId::METAMORPHOSIS, false, b.nextUid++);
        b.play_card_effect(metamorphosis, 0);
        check("r7_metamorphosis_adds_three_free_attacks",
              b.drawCount == 3 && card_is_attack(b.draw[0]) &&
                      b.draw[0].freeCombat,
              1);
    }
    {
        auto b = audit_base();
        b.monsters[0].hp = b.monsters[0].maxHp = 100;
        Card squash = make_card(CardId::SQUASH, false, b.nextUid++);
        b.play_card_effect(squash, 0);
        check("r7_squash_damages_and_vulnerables",
              b.monsters[0].hp == 90 && b.monsters[0].vulnerable == 2, 1);

        Card whistle = make_card(CardId::WHISTLE, false, b.nextUid++);
        b.play_card_effect(whistle, 0);
        check("r7_whistle_stuns", b.monsters[0].stunned, 1);
    }
    {
        BattleContext b;
        b.player.hp = b.player.maxHp = 500;
        spawn_monster(b, MonsterId::GAS_BOMB, 0);
        spawn_monster(b, MonsterId::EYE_WITH_TEETH, 1);
        b.monsterCount = 2;
        b.monsters[0].hp = 10;
        Card feed = make_card(CardId::FEED, false, b.nextUid++);
        b.play_card_effect(feed, 0);
        check("r7_feed_minion_does_not_gain_max_hp", b.player.maxHp, 500);
    }
    {
        BattleContext b;
        b.player.hp = b.player.maxHp = 500;
        spawn_monster(b, MonsterId::GAS_BOMB, 0);
        spawn_monster(b, MonsterId::EYE_WITH_TEETH, 1);
        b.monsterCount = 2;
        b.monsters[0].hp = 10;
        Card greed = make_card(CardId::HAND_OF_GREED, false, b.nextUid++);
        b.play_card_effect(greed, 0);
        check("r7_hand_of_greed_minion_does_not_gain_gold", b.combatGold, 0);
    }
    {
        BattleContext b;
        b.player.hp = b.player.maxHp = 500;
        spawn_monster(b, MonsterId::SHRINKER_BEETLE, 0);
        b.monsterCount = 1;
        b.monsters[0].hp = b.monsters[0].maxHp = 40;
        b.apply_potion(PotionId::POWDERED_DEMISE, 0);
        check("r7_powdered_demise_is_delayed", b.monsters[0].hp, 40);
        b.end_player_turn();
        check("r7_powdered_demise_ticks_after_enemy_turn", b.monsters[0].hp, 31);
    }

    // ------------------------------------------------- round-8 factory contracts
    {
        bool valid = true;
        for (std::uint32_t seed = 1; seed <= 500; ++seed) {
            Rng rng(seed);
            PotionId picks[3];
            const int n = random_potions_out_of_combat(rng, picks, 3);
            valid &= n == 3 && picks[0] != picks[1] && picks[0] != picks[2] &&
                     picks[1] != picks[2];
            for (int i = 0; i < n; ++i) {
                const Rarity rarity = potion_def(picks[i]).rarity;
                valid &= rarity == Rarity::COMMON || rarity == Rarity::UNCOMMON ||
                         rarity == Rarity::RARE;
                valid &= picks[i] != PotionId::DEPRECATED_POTION;
            }
        }
        check("r8_potion_batch_legal_and_distinct", valid, 1);
    }
    {
        bool legal = true;
        for (std::uint32_t seed = 1; seed <= 2000; ++seed) {
            auto b = audit_base();
            b.cardGenerationRng = Rng(seed);
            const CardId attack = b.random_card_of_type(CardType::ATTACK, true).id;
            const CardId skill = b.random_card_of_type(CardType::SKILL, true).id;
            legal &= attack != CardId::FEED && attack != CardId::HAND_OF_GREED;
            legal &= skill != CardId::ALCHEMIZE;
        }
        check("r8_combat_generation_honors_metadata", legal, 1);
    }
    {
        auto b = audit_base();
        b.cardGenerationRng = Rng(17);
        b.apply_potion(PotionId::OROBIC_ACID, 0);
        int badPool = 0;
        for (int i = 0; i < b.handCount; ++i) {
            badPool += card_def(b.hand[i].id).pool != CardPool::IRONCLAD;
        }
        check("r8_orobic_uses_character_pool", badPool, 0);
    }
    {
        bool startsOk = true;
        bool decimHpOk = true;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        for (std::uint32_t seed = 1; seed <= 200; ++seed) {
            BattleContext chompers;
            chompers.init(Encounter::SETUP_CHOMPERS_NORMAL, seed, deck, 20, 0, 500, 500);
            startsOk &= chompers.monsterCount == 2 &&
                        chompers.monsters[0].move == 0 &&
                        chompers.monsters[1].move == 1;

            BattleContext segments;
            segments.init(Encounter::SETUP_DECIMILLIPEDE_ELITE, seed, deck, 20, 0,
                          500, 500);
            std::set<int> moves;
            std::set<int> hps;
            for (int i = 0; i < segments.monsterCount; ++i) {
                moves.insert(segments.monsters[i].move);
                hps.insert(segments.monsters[i].maxHp);
                decimHpOk &= segments.monsters[i].maxHp % 2 == 0;
            }
            startsOk &= moves.size() == 3;
            decimHpOk &= hps.size() == 3;
        }
        check("r8_correlated_encounter_starts", startsOk, 1);
        check("r8_decimillipede_unique_even_hp", decimHpOk, 1);
    }
    {
        BattleContext b;
        Card deck[20];
        for (int i = 0; i < 20; ++i) {
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        }
        b.init(Encounter::SETUP_PUNCH_OFF, 73, deck, 20, 0, 500, 500);
        const bool punchOk =
            b.monsterCount == 2 && b.monsters[0].move == 1 &&
            b.monsters[1].move == 0 && b.monsters[0].maxHp == 55 &&
            b.monsters[1].maxHp == 55 && b.monsters[0].hp >= 45 &&
            b.monsters[0].hp <= 53 && b.monsters[1].hp >= 45 &&
            b.monsters[1].hp <= 53;
        check("r8_punch_off_initial_contract", punchOk, 1);
        b.init(Encounter::SETUP_CUBEX_CONSTRUCT_NORMAL, 73, deck, 20, 0, 500, 500);
        check("r8_cubex_initial_block", b.monsters[0].block, 13);
    }
    {
        auto b = audit_base();
        b.turn = 1;
        b.cardGenerationRng = Rng(91);
        b.relicCount = 1;
        b.relics[0] = static_cast<int>(RelicId::CHOICES_PARADOX);
        relics_hand_drawn(b);
        int bad = b.pending.count != 5;
        for (int i = 0; i < b.pending.count; ++i) {
            bad += card_def(b.pending.cards[i].id).pool != CardPool::IRONCLAD;
            bad += !card_has(b.pending.cards[i], CF_RETAIN);
        }
        check("r8_choices_paradox_contract", bad, 0);
    }
    {
        auto jack = audit_base();
        jack.cardGenerationRng = Rng(111);
        Card card = make_card(CardId::JACK_OF_ALL_TRADES, true, jack.nextUid++);
        jack.play_card_effect(card, 0);
        const bool distinct =
            jack.handCount == 2 && jack.hand[0].id != jack.hand[1].id &&
            jack.hand[0].id != CardId::JACK_OF_ALL_TRADES &&
            jack.hand[1].id != CardId::JACK_OF_ALL_TRADES;
        check("r8_jack_distinct_nonjack", distinct, 1);
    }
    {
        auto tool = audit_base();
        tool.turn = 1;
        tool.cardGenerationRng = Rng(123);
        tool.relicCount = 1;
        tool.relics[0] = static_cast<int>(RelicId::TOOLBOX);
        relics_hand_drawn(tool);
        int bad = tool.pending.count != 3 || !tool.pending.optional;
        for (int i = 0; i < tool.pending.count; ++i) {
            const CardDef &d = card_def(tool.pending.cards[i].id);
            bad += d.pool != CardPool::COLORLESS;
            bad += (d.flags & CF_CANNOT_GENERATE_IN_COMBAT) != 0;
            bad += tool.pending.cards[i].freeCombat ||
                   tool.pending.cards[i].costThisTurn;
            for (int j = 0; j < i; ++j) {
                bad += tool.pending.cards[i].id == tool.pending.cards[j].id;
            }
        }
        check("r8_toolbox_offer_contract", bad, 0);
    }

    // -------------------------------------------------------------- RNG contract
    // Vectors below come from .NET System.Random(0), matching the wrapper in
    // MegaCrit.Sts2.Core.Random/Rng.cs.
    {
        Rng rng(0);
        const int expected[] = {72, 81, 76, 55, 20, 55, 90, 44, 97, 27};
        int matches = 1;
        for (int i = 0; i < static_cast<int>(sizeof(expected) / sizeof(expected[0])); ++i) {
            matches &= rng.next_int_exclusive(100) == expected[i];
        }
        check("r7_rng_next_int_prefix_matches_dotnet", matches, 1);
        check("r7_rng_counter_tracks_next_int", static_cast<int>(rng.counter), 10);
    }
    {
        Rng rng(0);
        const bool expected[] = {false, false, false, false, true,
                                 false, false, true, false, true};
        int matches = 1;
        for (bool value : expected) matches &= rng.next_bool() == value;
        check("r7_rng_next_bool_prefix_matches_dotnet", matches, 1);
    }
    {
        Rng rng(0);
        for (int i = 0; i < 155215; ++i) (void) rng.next_int_exclusive(100);
        check("r7_rng_long_vector_matches_dotnet", rng.next_int_exclusive(100), 15);
    }
    {
        Rng fast(0, 5);
        check("r7_rng_fast_forward_counter", static_cast<int>(fast.counter), 5);
        check("r7_rng_fast_forward_next_value", fast.next_int_exclusive(100), 55);
        Rng fastCopy(0, 5);
        Rng rng(0);
        for (int i = 0; i < 5; ++i) (void) rng.next_int_exclusive(100);
        check("r7_rng_fast_forward_matches_draws",
              fastCopy.counter == rng.counter &&
                  fastCopy.next_int_exclusive(100) == rng.next_int_exclusive(100),
              1);
    }
    {
        Rng rng(0);
        check("r7_rng_gaussian_matches_dotnet",
              rng.next_gaussian_int(100, 10, 0, 200), 115);
        check("r7_rng_gaussian_does_not_increment_counter",
              static_cast<int>(rng.counter), 0);
        check("r7_rng_gaussian_consumes_raw_draws",
              rng.next_int_exclusive(100), 76);
    }

    // ---------------------------------------------------------------- atomicity
    // An illegal action must leave the whole context byte-identical.
    {
        auto b = base();
        hand(b, CardId::STRIKE_IRONCLAD);
        BattleContext before = b;
        Action bad;
        bad.type = ActionType::PLAY_CARD;
        bad.hand = 99;
        bad.target = 0;
        check("illegal_card_action_rejected", b.step(bad), 0);
        check("illegal_card_action_atomic", std::memcmp(&b, &before, sizeof(b)) == 0, 1);
    }
    {
        auto b = base();
        b.discard[b.discardCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 760);
        hand(b, CardId::HEADBUTT);
        play(b);
        BattleContext before = b;
        Action bad;
        bad.type = ActionType::CHOOSE;
        bad.uid = 65535;
        check("illegal_choice_rejected", b.step(bad), 0);
        check("illegal_choice_atomic", std::memcmp(&b, &before, sizeof(b)) == 0, 1);
    }

    // ---------------------------------------------------------- snapshot contract
    // Restore must validate all live counts and indices before replacing state.
    {
        RunContext valid;
        valid.init(777u, 0);
        RunContext restored;
        check("snapshot_valid_state_accepted",
              RunContext::restore(valid.serialize(), restored), 1);

        RunContext badDeck = valid;
        badDeck.deckCount = MAX_DECK + 1;
        check("snapshot_rejects_deck_count",
              RunContext::restore(badDeck.serialize(), restored), 0);

        RunContext badOffered = valid;
        badOffered.offeredCount = 2147483647;
        check("snapshot_rejects_offered_count",
              RunContext::restore(badOffered.serialize(), restored), 0);

        RunContext badPotion = valid;
        badPotion.potionCount = MAX_POTIONS + 1;
        check("snapshot_rejects_potion_count",
              RunContext::restore(badPotion.serialize(), restored), 0);

        RunContext badRelic = valid;
        badRelic.relicCount = MAX_RELICS + 1;
        check("snapshot_rejects_relic_count",
              RunContext::restore(badRelic.serialize(), restored), 0);

        RunContext badBattle = valid;
        badBattle.battle.drawCount = MAX_PILE + 1;
        check("snapshot_rejects_battle_draw_count",
              RunContext::restore(badBattle.serialize(), restored), 0);

        RunContext badPending = valid;
        badPending.battle.pending.count = MAX_PILE + 1;
        check("snapshot_rejects_pending_count",
              RunContext::restore(badPending.serialize(), restored), 0);
    }

    // Card contracts audited against the corresponding C# models.
    {
        const Card guilty = make_card(CardId::GUILTY, false, 1);
        const Card ethereal = make_card(CardId::APPARITION, false, 2);
        const Card costUpgrade = make_card(CardId::BARRICADE_CARD, false, 3);
        check("unchanged_guilty_is_not_upgradable", card_upgradable(guilty), 0);
        check("keyword_change_is_upgradable", card_upgradable(ethereal), 1);
        check("cost_change_is_upgradable", card_upgradable(costUpgrade), 1);
    }
    {
        auto b = audit_base();
        b.player.energy = 3;
        audit_hand(b, CardId::LUMINESCE);
        audit_play(b);
        check("luminesce_gains_energy", b.player.energy, 5);
        check("luminesce_exhausts", b.exhaustCount, 1);
    }
    {
        auto b = audit_base();
        audit_hand(b, CardId::STOMP);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        play(b, 1);
        play(b, 1);
        check("stomp_discounts_after_attacks", card_cost(b.hand[0]), 1);
        b.start_player_turn();
        check("stomp_discount_expires_next_turn", card_cost(b.hand[0]), 3);
    }
    {
        auto b = audit_base();
        hand(b, CardId::DUAL_WIELD, true);
        hand(b, CardId::STRIKE_IRONCLAD);
        hand(b, CardId::DEFEND_IRONCLAD);
        const int originalUid = b.hand[1].uid;
        audit_play(b);
        check("dual_wield_offers_only_attack_or_power", b.pending.count, 1);
        b.resolve_choice(static_cast<std::uint16_t>(originalUid));
        check("dual_wield_keeps_original_and_copies", b.handCount, 4);
        std::set<int> uids;
        int strikes = 0;
        for (int i = 0; i < b.handCount; ++i) {
            uids.insert(b.hand[i].uid);
            strikes += b.hand[i].id == CardId::STRIKE_IRONCLAD;
        }
        check("dual_wield_upgraded_makes_two_copies", strikes, 3);
        check("dual_wield_copy_uids_distinct", static_cast<int>(uids.size()), 4);
    }
    {
        auto b = audit_base();
        audit_hand(b, CardId::ENTHRALLED);
        audit_hand(b, CardId::STRIKE_IRONCLAD);
        check("enthralled_blocks_manual_other_card", b.play_card(1, 0), 0);
        const int hp = b.monsters[0].hp;
        b.auto_play_random(make_card(CardId::STRIKE_IRONCLAD, false, 950), false);
        check("enthralled_allows_autoplay", b.monsters[0].hp < hp, 1);
        play(b, 0);
        check("enthralled_can_be_played_itself", b.handCount, 1);
    }
    {
        auto b = audit_base();
        hand(b, CardId::TORIC_TOUGHNESS);
        hand(b, CardId::TORIC_TOUGHNESS, true);
        play(b);
        play(b);
        check("toric_two_instances", b.toricCount, 2);
        b.damage_player(12);
        check("toric_does_not_trigger_when_damage_breaks_block", b.player.block, 0);
        b.start_player_turn();
        check("toric_restores_each_instance_at_turn_start", b.player.block, 12);
        b.start_player_turn();
        check("toric_restores_for_second_turn", b.player.block, 12);
        check("toric_instances_expire_after_two_turns", b.toricCount, 0);
        b.start_player_turn();
        check("toric_does_not_restore_after_expiry", b.player.block, 0);
    }
    {
        auto b = audit_base();
        for (int i = 0; i < 9; ++i) b.add_player_power(PowerId::AUTOMATION, 1);
        for (int i = 0; i < 10; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::DEFEND_IRONCLAD);
        const int energy = b.player.energy;
        b.draw_cards(10);
        check("automation_nine_independent_instances", b.player.energy - energy, 9);
    }
    {
        auto b = audit_base();
        b.add_player_power(PowerId::ROLLING_BOULDER, 5);
        b.add_player_power(PowerId::ROLLING_BOULDER, 5);
        const int hp = b.monsters[0].hp;
        b.start_player_turn();
        b.start_player_turn();
        check("rolling_boulder_instances_grow_independently", hp - b.monsters[0].hp, 30);
    }
    {
        auto b = audit_base();
        const Card card = audit_card(b, CardId::DEFEND_IRONCLAD);
        const int hp = b.monsters[0].hp;
        b.add_player_power(PowerId::PANACHE, 5);
        b.after_card_played(card);  // the applying play primes the first instance
        b.after_card_played(card);
        b.after_card_played(card);
        b.add_player_power(PowerId::PANACHE, 9);
        b.after_card_played(card);  // applying play primes the second instance
        b.after_card_played(card);
        b.after_card_played(card);
        check("panache_first_instance_triggers_independently", hp - b.monsters[0].hp, 5);
        for (int i = 0; i < 3; ++i) b.after_card_played(card);
        check("panache_second_instance_has_own_counter", hp - b.monsters[0].hp, 14);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::INTANGIBLE)] = 1;
        b.add_monster_power(0, PowerId::GRAPPLE, 5);
        b.add_monster_power(0, PowerId::GRAPPLE, 5);
        const int hp = b.monsters[0].hp;
        b.gain_block(5, false, false);
        check("grapple_instances_damage_separately", hp - b.monsters[0].hp, 2);
        b.end_player_turn();
        check("grapple_instances_expire", b.monsters[0].grappleCount, 0);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::COVERED)] = 1;
        const int hp = b.monsters[0].hp;
        b.attack_monster(0, 10, 1, true);
        check("covered_blocks_powered_attack", hp - b.monsters[0].hp, 0);
        b.attack_monster(0, 10, 1, false);
        check("covered_allows_unpowered_damage", hp - b.monsters[0].hp, 10);
    }
    {
        auto b = audit_base();
        b.player.power[static_cast<int>(PowerId::SURROUNDED)] = 1;
        b.monsters[0].power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] = 1;
        b.monsters[1] = b.monsters[0];
        b.monsters[1].power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] = 0;
        b.monsters[1].power[static_cast<int>(PowerId::BACK_ATTACK_RIGHT)] = 1;
        b.monsterCount = 2;
        check("surrounded_back_attack_multiplier", b.calc_monster_damage(b.monsters[0], 10), 15);
        hand(b, CardId::STRIKE_IRONCLAD);
        play(b, 0);
        check("surrounded_turns_toward_card_target", b.player.surroundedFacingRight, 0);
        check("surrounded_other_side_now_attacks_from_behind", b.calc_monster_damage(b.monsters[1], 10), 15);
        check("surrounded_facing_attacker_has_no_bonus", b.calc_monster_damage(b.monsters[0], 10), 10);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::SOAR)] = 1;
        const int hp = b.monsters[0].hp;
        b.attack_monster(0, 10, 1, true);
        b.attack_monster(0, 10, 1, false);
        check("soar_only_halves_powered_attacks", hp - b.monsters[0].hp, 15);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::THIEVING_HOPPER, 0);
        b.monsters[0].hp = b.monsters[0].maxHp = 100;
        b.monsters[0].power[static_cast<int>(PowerId::FLUTTER)] = 2;
        b.attack_monster(0, 10, 2, true);
        check("flutter_halves_hits", b.monsters[0].hp, 90);
        check("flutter_expires_after_unblocked_hits", b.monsters[0].power[static_cast<int>(PowerId::FLUTTER)], 0);
        check("flutter_stuns_on_expiry", b.monsters[0].stunned, 1);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::TUNNELER, 0);
        b.monsters[0].block = 5;
        b.monsters[0].power[static_cast<int>(PowerId::BURROWED)] = 1;
        b.attack_monster(0, 5, 1, true);
        check("burrowed_stuns_on_block_break", b.monsters[0].stunned, 1);
        check("burrowed_removed_on_block_break", b.monsters[0].power[static_cast<int>(PowerId::BURROWED)], 0);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::TERROR_EEL, 0);
        b.monsters[0].hp = 80;
        b.monsters[0].power[static_cast<int>(PowerId::SHRIEK)] = 70;
        b.attack_monster(0, 10, 1, true);
        check("shriek_stuns_at_threshold", b.monsters[0].stunned, 1);
        check("shriek_removes_power", b.monsters[0].power[static_cast<int>(PowerId::SHRIEK)], 0);
    }
    {
        auto b = audit_base();
        b.monsters[0].hp = 160;
        b.monsters[0].strength = 3;
        b.monsters[0].power[static_cast<int>(PowerId::PLOW)] = 150;
        b.attack_monster(0, 10, 1, true);
        check("plow_stuns_at_threshold", b.monsters[0].stunned, 1);
        check("plow_clears_strength", b.monsters[0].strength, 0);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::CORPSE_SLUG, 1);
        b.monsterCount = 2;
        b.monsters[0].hp = 1;
        b.monsters[1].power[static_cast<int>(PowerId::RAVENOUS)] = 4;
        b.attack_monster(0, 10, 1, true);
        check("ravenous_gains_strength_on_ally_death", b.monsters[1].strength, 4);
        check("ravenous_stuns_on_ally_death", b.monsters[1].stunned, 1);
    }
    {
        auto b = audit_base();
        b.gold = 11;
        b.relics[b.relicCount++] = static_cast<int>(RelicId::BOWLER_HAT);
        b.relics[b.relicCount++] = static_cast<int>(RelicId::DRAGON_FRUIT);
        b.monsters[0].hp = 10;
        const int maxHp = b.player.maxHp;
        hand(b, CardId::HAND_OF_GREED);
        play(b);
        check("hand_of_greed_immediate_gold_with_bowler", b.gold, 35);
        check("hand_of_greed_dragon_fruit_each_gold_gain", b.player.maxHp - maxHp, 2);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::SKITTISH)] = 6;
        Card card = audit_card(b, CardId::TWIN_STRIKE);
        const int hp = b.monsters[0].hp;
        b.attack_from_card(card, 0, 5, 2);
        check("skittish_waits_for_all_hits_in_attack", hp - b.monsters[0].hp, 10);
        check("skittish_grants_block_after_attack", b.monsters[0].block, 6);
        b.attack_from_card(card, 0, 10);
        check("skittish_only_triggers_once_per_turn", b.monsters[0].block, 0);
        b.end_player_turn();
        check("skittish_resets_after_player_turn", b.monsters[0].skittishTriggeredThisTurn, 0);
    }
    {
        auto b = audit_base();
        b.monsters[0].power[static_cast<int>(PowerId::SKITTISH)] = 6;
        hand(b, CardId::FISTICUFFS);
        play(b);
        check("skittish_triggers_for_fisticuffs_attack_command", b.monsters[0].block, 6);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::DOOR, 0);
        b.monsterCount = 1;
        b.monsters[0].hp = 1;
        b.attack_monster(0, 10, 1, true);
        check("door_summons_doormaker", b.monsterCount, 2);
        b.monsters[1].hp = 123;
        b.monsters[1].strength = 4;
        b.monsters[1].move = 2;
        monster_act(b, b.monsters[1]);
        const int makerStrength = b.monsters[1].strength;
        b.monsters[0].hp = 1;
        b.attack_monster(0, 10, 1, true);
        check("door_reuses_doormaker_slot", b.monsterCount, 2);
        check("door_reuses_doormaker_health", b.monsters[1].hp, 123);
        check("door_reuses_doormaker_strength", b.monsters[1].strength, makerStrength);
        check("door_readds_doormaker", b.monsters[1].alive, 1);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::EYE_WITH_TEETH, 1);
        b.monsterCount = 2;
        b.add_monster_power(1, PowerId::ILLUSION, 1);
        b.monsters[1].hp = 1;
        b.attack_monster(1, 10, 1, true);
        check("illusion_death_enters_reviving_state", b.monsters[1].reviving, 1);
        check("illusion_does_not_end_while_primary_alive", static_cast<int>(b.outcome), static_cast<int>(Outcome::UNDECIDED));
        monster_act(b, b.monsters[1]);
        check("illusion_revives_to_full_health", b.monsters[1].hp, b.monsters[1].maxHp);
        check("illusion_revive_completes", b.monsters[1].reviving, 0);
        b.monsters[0].hp = 1;
        b.attack_monster(0, 10, 1, true);
        check("minion_does_not_prevent_victory", static_cast<int>(b.outcome), static_cast<int>(Outcome::PLAYER_VICTORY));
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::GREMLIN_MERC, 0);
        b.monsterCount = 1;
        b.monsters[0].hp = 1;
        b.monsters[0].stolenGold = 23;
        b.monsters[0].power[static_cast<int>(PowerId::SURPRISE)] = 1;
        b.attack_monster(0, 10, 1, true);
        int sneaky = -1, fat = -1;
        for (int i = 0; i < b.monsterCount; ++i) {
            if (b.monsters[i].id == MonsterId::SNEAKY_GREMLIN) sneaky = i;
            if (b.monsters[i].id == MonsterId::FAT_GREMLIN) fat = i;
        }
        check("surprise_spawns_both_gremlins", sneaky >= 0 && fat >= 0, 1);
        check("surprise_preserves_stolen_gold", fat >= 0 ? b.monsters[fat].stolenGold : -1, 23);
        if (fat >= 0) {
            b.monsters[fat].hp = 1;
            b.attack_monster(fat, 10, 1, true);
        }
        check("heist_queues_stolen_gold_reward", b.recoveredStolenGold, 23);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::GREMLIN_MERC, 0);
        b.monsterCount = 1;
        b.monsters[0].hp = 1;
        b.monsters[0].power[static_cast<int>(PowerId::SURPRISE)] = 1;
        b.gold = 0;
        hand(b, CardId::HAND_OF_GREED);
        play(b);
        check("fatal_uses_kill_result_when_enemy_slot_is_reused", b.gold, 20);
    }
    {
        auto b = audit_base();
        spawn_monster(b, MonsterId::DECIMILLIPEDE_SEGMENT, 0);
        spawn_monster(b, MonsterId::DECIMILLIPEDE_SEGMENT, 1);
        b.monsterCount = 2;
        b.monsters[0].power[static_cast<int>(PowerId::REATTACH)] = 25;
        b.monsters[1].power[static_cast<int>(PowerId::REATTACH)] = 25;
        b.monsters[0].hp = 1;
        b.monsters[1].hp = 1;
        const int maxHp = b.player.maxHp;
        hand(b, CardId::FEED);
        play(b);
        check("reattach_sibling_prevents_fatal", b.player.maxHp, maxHp);
        hand(b, CardId::FEED);
        Action action{ActionType::PLAY_CARD, 0, 1, 0};
        b.step(action);
        check("last_reattach_segment_allows_fatal", b.player.maxHp, maxHp + 3);
    }
    {
        auto b = audit_base();
        b.draw[b.drawCount++] = audit_card(b, CardId::WOUND);
        b.draw[b.drawCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.draw[b.drawCount++] = audit_card(b, CardId::DEFEND_IRONCLAD);
        b.draw[b.drawCount++] = audit_card(b, CardId::BASH);
        const auto counter = b.cardSelectionRng.counter;
        const Card wish = audit_card(b, CardId::WISH);
        b.start_draw_choice(wish, true, -1, -1);
        check("wish_offers_entire_draw_including_unplayable", b.pending.count, 4);
        check("full_draw_selection_does_not_consume_rng", b.cardSelectionRng.counter == counter, 1);
        bool woundOffered = false;
        for (int i = 0; i < b.pending.count; ++i) woundOffered |= b.pending.cards[i].id == CardId::WOUND;
        check("wish_includes_wound", woundOffered, 1);
    }
    {
        auto b = audit_base();
        for (int i = 0; i < 5; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        const auto counter = b.cardSelectionRng.counter;
        b.start_draw_choice(audit_card(b, CardId::SEEKER_STRIKE), false, -1, -1, 3);
        check("seeker_offers_three_cards", b.pending.count, 3);
        check("seeker_shuffles_entire_pile", b.cardSelectionRng.counter - counter, 4);
    }
    {
        auto b = audit_base();
        for (int i = 0; i < 5; ++i) b.draw[b.drawCount++] = audit_card(b, CardId::STRIKE_IRONCLAD);
        b.potions[0] = static_cast<int>(PotionId::DROPLET_OF_PRECOGNITION);
        b.potionCount = 1;
        b.use_potion(0, 0);
        check("droplet_offers_entire_draw_pile", b.pending.count, 5);
    }

    std::cout << "SUMMARY checks=" << checks << " failures=" << failures << "\n";
    return failures == 0 ? 0 : 1;
}
