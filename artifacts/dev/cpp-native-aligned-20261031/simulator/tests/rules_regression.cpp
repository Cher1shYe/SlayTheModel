// Native rule regressions for the 2026-10-28 deep audit (D01-D24).
//
// Every check isolates one rule and states the C# evidence in a comment next to
// it.  Built by CMake as `rules_test`; tests/test_native_rules.py runs it so a
// rule regression fails the normal pytest suite.  No check here claims client
// differential validation: the evidence level is "C# reference reading".
#include <cstring>
#include <iostream>
#include <set>
#include <stdexcept>
#include <type_traits>

#include "sts2/battle.h"
#include "sts2/card_candidates.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/relic_raw_rarity.h"
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
    // GRAPPLE is absent from target v0.111.0 ModelDb.AllCards. The legacy
    // power remains addressable, but the legacy card cannot enter live play.
    {
        auto b = audit_base();
        const int amount = 3;
        b.add_monster_power(0, PowerId::GRAPPLE, amount);
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
        b.add_monster_power(0, PowerId::GRAPPLE, 3);
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
        check("r5_09_howl_all_copies", hp - b.monsters[0].hp, 36);
    }
    // Native v0.111.0 Drum of Battle grants 2 Energy when exhausted.
    {
        auto b = audit_base();
        const int energy = b.player.energy;
        b.move_to_exhaust(audit_card(b, CardId::DRUM_OF_BATTLE_CARD));
        check("r5_10_drum_exhaust_energy", b.player.energy - energy, 2);
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
        check("r5_14_brightest_maxhp", b.player.maxHp, 498);
    }
    {
        auto b = audit_base();
        b.player.hp = 1;
        audit_hand(b, CardId::BRIGHTEST_FLAME);
        audit_play(b);
        check("r5_14_brightest_one_hp_maxhp", b.player.maxHp, 498);
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
        check("inferno_direct_hp_loss_no_damage_hook", hp - b.monsters[0].hp, 0);
        b.damage_player(1, true);
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
        check("stoke_exhausts_only_original_hand", b.exhaustCount, 2);
        check("stoke_preserves_exhaust_draws_and_generates_two", b.handCount, 4);
        check("stoke_does_not_draw_for_generation", b.drawCount, 6);
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
        choose_all(b);   // Headbutt's selector stays open on auto-play
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
                      card_def(CardId::GIANT_ROCK).rarity == Rarity::TOKEN,
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
        // Select a native RNG draw between the A0 regular (3%) and elite
        // (10%) rare thresholds, with zero rarity offset. This tests the rule
        // independently of any historical seed's particular random sequence.
        constexpr float normalRare = 0.03f, eliteRare = 0.10f;
        std::uint64_t thresholdSeed = 0;
        float firstRoll = -1.0f;
        bool foundThresholdSeed = false;
        for (std::uint64_t seed = 0; seed < 4096; ++seed) {
            Rng candidate(seed);
            const float roll = candidate.next_float();
            if (roll >= normalRare && roll < eliteRare) {
                thresholdSeed = seed;
                firstRoll = roll;
                foundThresholdSeed = true;
                break;
            }
        }
        check("r7_elite_threshold_fixture_found", foundThresholdSeed, 1);
        check("r7_elite_threshold_fixture_in_discriminating_interval",
              firstRoll >= normalRare && firstRoll < eliteRare, 1);
        if (foundThresholdSeed) {
            RunContext elite;
            elite.cardRarityOdds = 0.0f;
            elite.playerRng[PRNG_REWARDS] = Rng(thresholdSeed);
            elite.combatIsElite = true;
            RunContext normal = elite;
            normal.combatIsElite = false;
            elite.roll_card_reward(false);
            normal.roll_card_reward(false);
            check("r7_elite_reward_uses_elite_rare_threshold",
                  elite.offeredCount > 0 && card_def(elite.offered[0].id).rarity == Rarity::RARE, 1);
            check("r7_same_draw_regular_reward_is_not_rare",
                  normal.offeredCount > 0 && card_def(normal.offered[0].id).rarity != Rarity::RARE, 1);
        }
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
        // WelcomeToWongos.GenerateInitialOptions pulls the FeaturedItem at
        // event start: explicit Rare rarity (no Rewards roll) with the
        // shop-only filter, from the front of the player's rare deque.
        RunContext r;
        r.init(930007, 0);
        r.gold = 500;
        const int rareFront = r.playerRelicBag.entries[2][0];
        event_begin(r, event_id("WELCOME_TO_WONGOS"), false);
        check("r7_wongo_featured_is_front_rare", r.eventData[0], rareFront);
        int stillInBag = 0;
        for (int i = 0; i < r.playerRelicBag.counts[2]; ++i)
            stillInBag += r.playerRelicBag.entries[2][i] == rareFront ? 1 : 0;
        check("r7_wongo_featured_leaves_bag", stillInBag, 0);
        const int before = r.relicCount;
        event_choose(r, 1);
        check("r7_wongo_featured_obtained", r.relicCount, before + 1);
        check("r7_wongo_featured_is_pulled_relic", r.relics[r.relicCount - 1], rareFront);
    }
    {
        // BuyBargainBin pulls an explicit Common with IsAllowedInShops; the
        // shop-forbidden relic at the front stays in the deque.
        RunContext r;
        r.init(930008, 0);
        r.gold = 500;
        r.playerRelicBag.counts[0] = 2;
        r.playerRelicBag.entries[0][0] = static_cast<std::uint16_t>(RelicId::AMETHYST_AUBERGINE);
        int allowedCommon = -1;
        for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
            const RelicId id = static_cast<RelicId>(i);
            const RelicDef &def = relic_def(id);
            if (relic_raw_rarity(id) == 1 && relic_implemented(id) &&
                relic_allowed_in_shops(id) &&
                (def.pool == RelicPool::SHARED || def.pool == RelicPool::IRONCLAD)) {
                allowedCommon = i;
                break;
            }
        }
        check("r7_wongo_bargain_fixture", allowedCommon > 0 ? 1 : 0, 1);
        r.playerRelicBag.entries[0][1] = static_cast<std::uint16_t>(allowedCommon);
        event_begin(r, event_id("WELCOME_TO_WONGOS"), false);
        event_choose(r, 0);
        check("r7_wongo_bargain_skips_shop_forbidden",
              r.relics[r.relicCount - 1], allowedCommon);
        check("r7_wongo_bargain_keeps_forbidden",
              r.playerRelicBag.entries[0][0], static_cast<int>(RelicId::AMETHYST_AUBERGINE));
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
    // Actual native v0.111.0 / 41cef1ea MegaRandom vectors. Full mixed-method
    // state/counter coverage lives in native_rng_contract.cpp and its oracle JSON.
    {
        Rng rng(0);
        const int expected[] = {60, 74, 10, 41, 73, 99, 42, 53, 85, 91};
        int matches = 1;
        for (int i = 0; i < static_cast<int>(sizeof(expected) / sizeof(expected[0])); ++i) {
            matches &= rng.next_int_exclusive(100) == expected[i];
        }
        check("native_rng_next_int_prefix", matches, 1);
        check("r7_rng_counter_tracks_next_int", static_cast<int>(rng.counter), 10);
    }
    {
        Rng rng(0);
        const bool expected[] = {false, false, true, true, false,
                                 false, true, false, false, false};
        int matches = 1;
        for (bool value : expected) matches &= rng.next_bool() == value;
        check("native_rng_next_bool_prefix", matches, 1);
    }
    {
        Rng rng(0);
        for (int i = 0; i < 155215; ++i) (void) rng.next_int_exclusive(100);
        check("native_rng_long_vector", rng.next_int_exclusive(100), 17);
    }
    {
        Rng fast(0, 5);
        check("r7_rng_fast_forward_counter", static_cast<int>(fast.counter), 5);
        check("r7_rng_fast_forward_next_value", fast.next_int_exclusive(100), 99);
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
        check("native_rng_gaussian",
              rng.next_gaussian_int(100, 10, 0, 200), 114);
        check("native_rng_gaussian_increments_counter",
              static_cast<int>(rng.counter), 2);
        check("r7_rng_gaussian_consumes_raw_draws",
              rng.next_int_exclusive(100), 10);
    }

    // ---------------------------------------------------------------- atomicity
    // Native StableShuffle([0,1,2,3], Rng(22)) => [1,2,0,3]. The C++
    // draw stack is reversed because draw_cards pops its last element.
    {
        BattleContext a, b;
        const CardId sorted[] = {CardId::BASH, CardId::DEFEND_IRONCLAD,
                                 CardId::STRIKE_IRONCLAD, CardId::THRASH};
        for (int i = 0; i < 4; ++i) a.discard[i] = make_card(sorted[i], false, i + 1);
        a.discardCount = 4;
        // Include a remaining draw card, as native CardPileCmd.Shuffle does.
        b.draw[0] = make_card(CardId::BASH, false, 1);
        b.drawCount = 1;
        for (int i = 0; i < 3; ++i) b.discard[i] = make_card(sorted[3-i], false, 4-i);
        b.discardCount = 3;
        a.shuffleRng = Rng(22); b.shuffleRng = Rng(22);
        a.shuffle_discard_into_draw(); b.shuffle_discard_into_draw();
        const CardId expected[] = {CardId::THRASH, CardId::BASH,
                                   CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD};
        bool matches = a.drawCount == 4 && b.drawCount == 4 && !a.discardCount && !b.discardCount;
        for (int i = 0; i < 4; ++i)
            matches &= a.draw[i].id == expected[i] && b.draw[i].id == expected[i];
        check("native_discard_shuffle_sort_combine_and_stack_direction", matches, 1);
        check("native_discard_shuffle_counter", a.shuffleRng.counter, 3);
    }
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

    // ------------------------------------------------ TeaMaster (shared event)
    // C# TeaMaster: IsAllowed act<2 and gold>=150; options BoneTea 50,
    // EmberTea 150, TeaOfDiscourtesy free; each obtains its relic.
    {
        RunContext r;
        r.init(930050, 0);
        r.gold = 200;
        event_begin(r, event_id("TEA_MASTER"), false);
        check("tea_master_three_options", event_option_count(r), 3);
        check("tea_master_bone_available", event_option_available(r, 0), 1);
        check("tea_master_ember_available", event_option_available(r, 1), 1);
        event_choose(r, 0);
        check("tea_master_bone_cost", r.gold, 150);
        check("tea_master_bone_relic", run_has_relic(r, RelicId::BONE_TEA), 1);
    }
    {
        RunContext r;
        r.init(930051, 0);
        r.gold = 200;
        event_begin(r, event_id("TEA_MASTER"), false);
        event_choose(r, 1);
        check("tea_master_ember_cost", r.gold, 50);
        check("tea_master_ember_relic", run_has_relic(r, RelicId::EMBER_TEA), 1);
    }
    {
        RunContext r;
        r.init(930052, 0);
        r.gold = 200;
        event_begin(r, event_id("TEA_MASTER"), false);
        event_choose(r, 2);
        check("tea_master_discourtesy_cost", r.gold, 200);
        check("tea_master_discourtesy_relic",
              run_has_relic(r, RelicId::TEA_OF_DISCOURTESY), 1);
    }
    {
        RunContext r;
        r.init(930053, 0);
        r.gold = 49;
        check("tea_master_event_requires_150", event_is_allowed(r, event_id("TEA_MASTER")), 0);
    }

    // ------------------------------------------- RoundTeaParty / TrashHeap
    // C# RoundTeaParty: EnjoyTea obtains RoyalPoison and heals to full;
    // PickFight -> ContinueFight deals 11 unblockable/unpowered and pulls a
    // front relic. C# TrashHeap: DiveIn loses 8 and pulls one of five relics;
    // Grab gains 100 gold and adds one of ten cards.
    {
        RunContext r;
        r.init(930060, 0);
        r.hp = 20;
        r.maxHp = 80;
        event_begin(r, event_id("ROUND_TEA_PARTY"), false);
        event_choose(r, 0);
        check("round_tea_enjoy_heals_to_full", r.hp, 80);
        check("round_tea_enjoy_relic", run_has_relic(r, RelicId::ROYAL_POISON), 1);
    }
    {
        RunContext r;
        r.init(930061, 0);
        r.hp = 50;
        r.maxHp = 80;
        const int relicsBefore = r.relicCount;
        event_begin(r, event_id("ROUND_TEA_PARTY"), false);
        event_choose(r, 1);
        check("round_tea_fight_page", r.eventPage, 1);
        event_choose(r, 0);
        check("round_tea_fight_damage", r.hp, 39);
        check("round_tea_fight_relic", r.relicCount, relicsBefore + 1);
    }
    {
        RunContext r;
        r.init(930062, 0);
        r.hp = 50;
        const int relicsBefore = r.relicCount;
        event_begin(r, event_id("TRASH_HEAP"), false);
        event_choose(r, 0);
        check("trash_heap_dive_damage", r.hp, 42);
        check("trash_heap_dive_relic", r.relicCount, relicsBefore + 1);
        const RelicId got = static_cast<RelicId>(r.relics[r.relicCount - 1]);
        const bool fixedList = got == RelicId::DARKSTONE_PERIAPT ||
            got == RelicId::DREAM_CATCHER || got == RelicId::HAND_DRILL ||
            got == RelicId::MAW_BANK || got == RelicId::THE_BOOT;
        check("trash_heap_dive_fixed_relic", fixedList, 1);
    }
    {
        RunContext r;
        r.init(930063, 0);
        r.hp = 50;
        const int goldBefore = r.gold;
        const int deckBefore = r.deckCount;
        event_begin(r, event_id("TRASH_HEAP"), false);
        event_choose(r, 1);
        check("trash_heap_grab_gold", r.gold, goldBefore + 100);
        check("trash_heap_grab_card", r.deckCount, deckBefore + 1);
        const CardId got = r.deck[r.deckCount - 1].id;
        const bool fixedList = got == CardId::CALTROPS || got == CardId::CLASH ||
            got == CardId::DISTRACTION || got == CardId::DUAL_WIELD ||
            got == CardId::ENTRENCH || got == CardId::HELLO_WORLD_CARD ||
            got == CardId::OUTMANEUVER || got == CardId::REBOUND ||
            got == CardId::RIP_AND_TEAR || got == CardId::STACK;
        check("trash_heap_grab_fixed_card", fixedList, 1);
    }

    // ------------------------------------------------------ ColossalFlower
    // C# ColossalFlower: depth 0/1/2 prizes 35/75/135 gold; Reach Deeper
    // deals 5/6/7 unblockable/unpowered, and at depth 2 the second option
    // obtains Pollinous Core instead of a prize.
    {
        RunContext r;
        r.init(930070, 0);
        r.hp = 50;
        const int gold = r.gold;
        event_begin(r, event_id("COLOSSAL_FLOWER"), false);
        event_choose(r, 0);
        check("colossal_prize_1", r.gold - gold, 35);
    }
    {
        RunContext r;
        r.init(930071, 0);
        r.hp = 50;
        const int gold = r.gold;
        event_begin(r, event_id("COLOSSAL_FLOWER"), false);
        event_choose(r, 1);
        check("colossal_deeper_1_damage", r.hp, 45);
        event_choose(r, 0);
        check("colossal_prize_2", r.gold - gold, 75);
    }
    {
        RunContext r;
        r.init(930072, 0);
        r.hp = 50;
        const int relics = r.relicCount;
        event_begin(r, event_id("COLOSSAL_FLOWER"), false);
        event_choose(r, 1);
        event_choose(r, 1);
        check("colossal_deeper_2_damage", r.hp, 39);
        event_choose(r, 1);
        check("colossal_deeper_3_damage", r.hp, 32);
        check("colossal_core_relic", r.relicCount, relics + 1);
        check("colossal_core_id", run_has_relic(r, RelicId::POLLINOUS_CORE), 1);
    }
    {
        RunContext r;
        r.init(930073, 0);
        r.hp = 18;
        check("colossal_requires_19_hp",
              event_is_allowed(r, event_id("COLOSSAL_FLOWER")), 0);
    }

    // ------------------------------ WhisperingHollow / TheLegendsWereTrue
    // C# WhisperingHollow: gold option spends 35 +/- 9 (event RNG) and offers
    // two potion rewards; Hug transforms one card then deals 9 unblockable/
    // unpowered. C# TheLegendsWereTrue (act 0): SpoilsMap, or 8 damage plus
    // one random potion reward from the rewards RNG.
    {
        RunContext r;
        r.init(930080, 0);
        r.gold = 100;
        event_begin(r, event_id("WHISPERING_HOLLOW"), false);
        const int cost = r.eventData[0];
        // C# NextInt(-9, 10) is upper-exclusive: 26..44.
        check("whispering_gold_cost_range", cost >= 26 && cost <= 44, 1);
        event_choose(r, 0);
        check("whispering_gold_cost", r.gold, 100 - cost);
        check("whispering_gold_two_potions", r.pendingPotionCount, 2);
    }
    {
        RunContext r;
        r.init(930081, 0);
        r.hp = 50;
        event_begin(r, event_id("WHISPERING_HOLLOW"), false);
        event_choose(r, 1);
        check("whispering_hug_starts_selection", r.eventCardSelection, 4);
        int choice = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { choice = i; break; }
        check("whispering_hug_has_target", choice >= 0, 1);
        event_select_card(r, choice);
        check("whispering_hug_damage", r.hp, 41);
    }
    {
        RunContext r;
        r.init(930082, 0);
        event_begin(r, event_id("THE_LEGENDS_WERE_TRUE"), false);
        event_choose(r, 0);
        check("legends_spoils_map", r.deck[r.deckCount - 1].id == CardId::SPOILS_MAP, 1);
    }
    {
        RunContext r;
        r.init(930083, 0);
        r.hp = 50;
        event_begin(r, event_id("THE_LEGENDS_WERE_TRUE"), false);
        event_choose(r, 1);
        check("legends_exit_damage", r.hp, 42);
        check("legends_exit_potion", r.pendingPotionCount, 1);
    }

    // ------------------------------ JungleMazeAdventure / InfestedAutomaton
    // C# JungleMazeAdventure.CalculateVars rolls SoloGold 150 +/- 15 and
    // JoinForcesGold 50 +/- 15 from the event RNG; GainGold truncates the
    // decimal total. Solo deals 18 unblockable/unpowered before the gold.
    // C# InfestedAutomaton: STUDY creates one Power from the owner's pool with
    // noncombat default odds; TOUCH_CORE creates one canonical 0-cost non-X
    // card. Both add the card directly to the deck.
    {
        RunContext r;
        r.init(930090, 0);
        r.hp = 60;
        event_begin(r, event_id("JUNGLE_MAZE_ADVENTURE"), false);
        const int solo = r.eventData[0];
        const int join = r.eventData[1];
        check("jungle_solo_gold_range", solo >= 135 && solo <= 164, 1);
        check("jungle_join_gold_range", join >= 35 && join <= 64, 1);
        const int gold = r.gold;
        event_choose(r, 0);
        check("jungle_solo_damage", r.hp, 42);
        check("jungle_solo_gold", r.gold, gold + solo);
    }
    {
        RunContext r;
        r.init(930091, 0);
        r.hp = 60;
        event_begin(r, event_id("JUNGLE_MAZE_ADVENTURE"), false);
        const int join = r.eventData[1];
        const int gold = r.gold;
        event_choose(r, 1);
        check("jungle_join_no_damage", r.hp, 60);
        check("jungle_join_gold", r.gold, gold + join);
    }
    {
        RunContext r;
        r.init(930092, 0);
        r.hp = 1;
        check("jungle_allowed_at_low_hp_single_player",
              event_is_allowed(r, event_id("JUNGLE_MAZE_ADVENTURE")), 1);
    }
    {
        RunContext r;
        r.init(930093, 0);
        const int deck = r.deckCount;
        event_begin(r, event_id("INFESTED_AUTOMATON"), false);
        event_choose(r, 0);
        check("infested_study_adds_card", r.deckCount, deck + 1);
        check("infested_study_power",
              card_def(r.deck[r.deckCount - 1].id).type == CardType::POWER, 1);
    }
    {
        RunContext r;
        r.init(930094, 0);
        const int deck = r.deckCount;
        event_begin(r, event_id("INFESTED_AUTOMATON"), false);
        event_choose(r, 1);
        check("infested_core_adds_card", r.deckCount, deck + 1);
        check("infested_core_zero_cost",
              card_def(r.deck[r.deckCount - 1].id).cost == 0, 1);
    }

    // ------------------------------ DollRoom / SlipperyBridge /
    // TheFutureOfPotions
    // C# DollRoom (act 1): RANDOM picks one of three declaration-order dolls
    // with one event-RNG call; the other options deal 5/15 unblockable damage
    // and StableShuffle (ModelId sort, then UnstableShuffle) to show 2 or 3.
    // SlipperyBridge: floor > 6 and a removable card; first pick prefers
    // non-Basic removable cards. HOLD_ON deals 3 + holds damage, marks the
    // shown card skipped and offers a new one.
    // C# TheFutureOfPotions: options are the first three occupied potion
    // slots; the lazily built type map rolls once per occupied potion; a trade
    // discards the potion and offers three upgraded cards of the potion's
    // mapped rarity and that random type.
    {
        const int daughter = static_cast<int>(RelicId::DAUGHTER_OF_THE_WIND);
        const int struggles = static_cast<int>(RelicId::MR_STRUGGLES);
        const int bing = static_cast<int>(RelicId::BING_BONG);
        RunContext r;
        r.init(930100, 0);
        r.act = 1;
        const int relics = r.relicCount;
        event_begin(r, event_id("DOLL_ROOM"), false);
        check("doll_room_three_options", event_option_count(r), 3);
        event_choose(r, 0);
        check("doll_room_random_relic", r.relicCount, relics + 1);
        const int got = r.relics[r.relicCount - 1];
        check("doll_room_relic_is_doll", got == daughter || got == struggles || got == bing, 1);
    }
    {
        RunContext r;
        r.init(930101, 0);
        r.act = 1;
        r.hp = 60;
        const int relics = r.relicCount;
        event_begin(r, event_id("DOLL_ROOM"), false);
        event_choose(r, 1);
        check("doll_room_take_time_damage", r.hp, 55);
        check("doll_room_take_time_options", event_option_count(r), 2);
        const int first = r.eventData[0];
        const int second = r.eventData[1];
        check("doll_room_take_time_distinct", first != second, 1);
        event_choose(r, 0);
        check("doll_room_take_time_relic", r.relicCount, relics + 1);
        check("doll_room_take_time_relic_id", r.relics[r.relicCount - 1], first);
    }
    {
        RunContext r;
        r.init(930102, 0);
        r.act = 1;
        r.hp = 60;
        event_begin(r, event_id("DOLL_ROOM"), false);
        event_choose(r, 2);
        check("doll_room_examine_damage", r.hp, 45);
        check("doll_room_examine_options", event_option_count(r), 3);
    }
    {
        RunContext r;
        r.init(930110, 0);
        r.floor = 7;
        const int deck = r.deckCount;
        event_begin(r, event_id("SLIPPERY_BRIDGE"), false);
        const int uid = r.eventData[0];
        int idx = -1;
        for (int i = 0; i < r.deckCount; ++i) if (r.deck[i].uid == uid) idx = i;
        check("slippery_offers_deck_card", idx >= 0, 1);
        event_choose(r, 1);
        check("slippery_hold_damage", r.hp, 77);
        check("slippery_hold_count", r.eventData[1], 1);
        check("slippery_hold_new_card", r.eventData[0] != 0, 1);
        event_choose(r, 0);
        check("slippery_overcome_removes", r.deckCount, deck - 1);
    }
    {
        RunContext r;
        r.init(930111, 0);
        r.floor = 6;
        check("slippery_floor_gate", event_is_allowed(r, event_id("SLIPPERY_BRIDGE")), 0);
    }
    {
        RunContext r;
        r.init(930120, 0);
        r.add_potion(PotionId::FIRE_POTION);
        r.add_potion(PotionId::BLOCK_POTION);
        const int before = r.potionCount;
        event_begin(r, event_id("THE_FUTURE_OF_POTIONS"), false);
        check("future_options_match_potions", event_option_count(r), 2);
        check("future_potion_slot_recorded", r.eventData[0], 0);
        const int slot = r.eventData[0];
        const int potion = r.potions[slot];
        event_choose(r, 0);
        check("future_potion_discarded", r.potionCount, before - 1);
        check("future_potion_slot_cleared", r.potions[slot], 0);
        check("future_reward_pending", r.rewardCardPending[0], 1);
        check("future_reward_three", r.rewardCardCounts[0], 3);
        bool upgraded = true;
        for (int i = 0; i < r.rewardCardCounts[0]; ++i)
            upgraded &= r.rewardCards[0][i].upgraded;
        check("future_reward_upgraded", upgraded, 1);
        const Rarity want = potion_def(static_cast<PotionId>(potion)).rarity == Rarity::COMMON
            ? Rarity::COMMON : Rarity::UNCOMMON;
        bool rarityOk = true;
        for (int i = 0; i < r.rewardCardCounts[0]; ++i)
            rarityOk &= card_def(r.rewardCards[0][i].id).rarity == want;
        check("future_reward_rarity", rarityOk, 1);
    }
    {
        RunContext r;
        r.init(930121, 0);
        r.add_potion(PotionId::FIRE_POTION);
        check("future_requires_two_potions",
              event_is_allowed(r, event_id("THE_FUTURE_OF_POTIONS")), 0);
    }

    // ------------------------------ ZenWeaver
    // C# ZenWeaver: allowed at gold >= 125; option 1/2 are locked below
    // 125/250. Breathing Techniques spends 50 and adds two Enlightenment;
    // the others remove one/two cards (IsRemovable = non-Eternal) and then
    // spend 125/250.
    {
        RunContext r;
        r.init(930130, 0);
        r.gold = 124;
        check("zen_requires_125", event_is_allowed(r, event_id("ZEN_WEAVER")), 0);
        r.gold = 200;
        check("zen_allowed_200", event_is_allowed(r, event_id("ZEN_WEAVER")), 1);
        const int deck = r.deckCount;
        event_begin(r, event_id("ZEN_WEAVER"), false);
        check("zen_three_options", event_option_count(r), 3);
        check("zen_option2_locked_below_250", event_option_available(r, 2), 0);
        check("zen_option1_available", event_option_available(r, 1), 1);
        event_choose(r, 0);
        check("zen_breathing_gold", r.gold, 150);
        check("zen_breathing_two_cards", r.deckCount, deck + 2);
        check("zen_breathing_enlightenment",
              r.deck[r.deckCount - 1].id == CardId::ENLIGHTENMENT, 1);
    }
    {
        RunContext r;
        r.init(930131, 0);
        r.gold = 200;
        const int deck = r.deckCount;
        event_begin(r, event_id("ZEN_WEAVER"), false);
        event_choose(r, 1);
        check("zen_emotional_starts_selection", r.eventCardSelection, 6);
        int choice = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { choice = i; break; }
        check("zen_emotional_has_target", choice >= 0, 1);
        event_select_card(r, choice);
        check("zen_emotional_gold", r.gold, 75);
        check("zen_emotional_removed", r.deckCount, deck - 1);
    }
    {
        RunContext r;
        r.init(930132, 0);
        r.gold = 300;
        const int deck = r.deckCount;
        event_begin(r, event_id("ZEN_WEAVER"), false);
        check("zen_option2_available_at_300", event_option_available(r, 2), 1);
        event_choose(r, 2);
        check("zen_arachnid_starts_selection", r.eventCardSelection, 6);
        int first = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { first = i; break; }
        event_select_card(r, first);
        check("zen_arachnid_still_selecting", r.eventCardSelection, 6);
        int second = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { second = i; break; }
        event_select_card(r, second);
        check("zen_arachnid_gold", r.gold, 50);
        check("zen_arachnid_removed_two", r.deckCount, deck - 2);
        check("zen_arachnid_finished", r.screen != RunScreen::EVENT, 1);
    }

    // ------------------------------ Amalgamator
    // C# Amalgamator: allowed when the deck has >= 2 removable Basic
    // Strike-tagged and >= 2 removable Basic Defend-tagged cards. Combining
    // removes exactly two matching cards and adds UltimateStrike/Defend.
    {
        RunContext r;
        r.init(930140, 0);
        check("amalgamator_allowed_on_starting_deck",
              event_is_allowed(r, event_id("AMALGAMATOR")), 1);
        const int deck = r.deckCount;
        event_begin(r, event_id("AMALGAMATOR"), false);
        event_choose(r, 0);
        check("amalgamator_starts_selection", r.eventCardSelection, 6);
        int first = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { first = i; break; }
        check("amalgamator_strike_selectable", first >= 0, 1);
        event_select_card(r, first);
        check("amalgamator_still_selecting", r.eventCardSelection, 6);
        int second = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { second = i; break; }
        event_select_card(r, second);
        check("amalgamator_net_deck", r.deckCount, deck - 1);
        check("amalgamator_ultimate_strike",
              r.deck[r.deckCount - 1].id == CardId::ULTIMATE_STRIKE, 1);
        check("amalgamator_finished", r.screen != RunScreen::EVENT, 1);
    }
    {
        RunContext r;
        r.init(930141, 0);
        const int deck = r.deckCount;
        event_begin(r, event_id("AMALGAMATOR"), false);
        event_choose(r, 1);
        int first = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { first = i; break; }
        event_select_card(r, first);
        int second = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { second = i; break; }
        event_select_card(r, second);
        check("amalgamator_defend_net_deck", r.deckCount, deck - 1);
        check("amalgamator_ultimate_defend",
              r.deck[r.deckCount - 1].id == CardId::ULTIMATE_DEFEND, 1);
    }
    {
        RunContext r;
        r.init(930142, 0);
        // Strip all Defends so the Defend count fails.
        for (int i = 0; i < r.deckCount;) {
            if (card_def(r.deck[i].id).flags & CF_DEFEND) {
                for (int j = i + 1; j < r.deckCount; ++j) r.deck[j - 1] = r.deck[j];
                --r.deckCount;
            } else {
                ++i;
            }
        }
        check("amalgamator_needs_two_defends",
              event_is_allowed(r, event_id("AMALGAMATOR")), 0);
    }

    // ------------------------------ ColorfulPhilosophers
    // C#: allowed with more than one unlocked character pool. Options follow
    // CardPoolColorOrder (Necrobinder, Ironclad, Regent, Silent, Defect),
    // skip the owner's pool and locked pools, then remove random entries until
    // three remain. The choice offers Common/Uncommon/Rare card rewards of
    // three uniform cards each from that pool.
    {
        RunContext r;
        r.init(930150, 0);
        r.act = 1;
        check("colorful_allowed_with_all_pools",
              event_is_allowed(r, event_id("COLORFUL_PHILOSOPHERS")), 1);
        event_begin(r, event_id("COLORFUL_PHILOSOPHERS"), false);
        check("colorful_three_options", event_option_count(r), 3);
        for (int i = 0; i < 3; ++i) {
            const CardPool pool = static_cast<CardPool>(r.eventData[i]);
            check("colorful_option_excludes_ironclad", pool != CardPool::IRONCLAD, 1);
            check("colorful_option_is_unlocked",
                  native_card_pool_unlocked(r, pool), 1);
        }
        const CardPool chosen = static_cast<CardPool>(r.eventData[0]);
        event_choose(r, 0);
        check("colorful_three_rewards", r.rewardCardPending[0] +
              r.rewardCardPending[1] + r.rewardCardPending[2], 3);
        bool poolOk = true, rarityOk = true, countOk = true;
        const Rarity want[3] = {Rarity::COMMON, Rarity::UNCOMMON, Rarity::RARE};
        for (int slot = 0; slot < 3; ++slot) {
            countOk &= r.rewardCardCounts[slot] == 3;
            for (int i = 0; i < r.rewardCardCounts[slot]; ++i) {
                const CardDef &d = card_def(r.rewardCards[slot][i].id);
                poolOk &= d.pool == chosen;
                rarityOk &= d.rarity == want[slot];
            }
        }
        check("colorful_reward_pool", poolOk, 1);
        check("colorful_reward_rarity", rarityOk, 1);
        check("colorful_reward_counts", countOk, 1);
    }
    {
        RunContext r;
        r.init(930151, 0);
        r.act = 1;
        r.nativeProgress.unlockedCharacterMask = 1;  // Ironclad only
        check("colorful_needs_second_pool",
              event_is_allowed(r, event_id("COLORFUL_PHILOSOPHERS")), 0);
    }
    {
        RunContext r;
        r.init(930152, 0);
        r.act = 1;
        r.nativeProgress.unlockedCharacterMask = 3;  // Ironclad + Silent
        event_begin(r, event_id("COLORFUL_PHILOSOPHERS"), false);
        check("colorful_single_eligible_option", event_option_count(r), 1);
        check("colorful_silent_pool",
              r.eventData[0] == static_cast<int>(CardPool::SILENT), 1);
    }

    // ------------------------------ LuminousChoir
    // C#: allowed at gold >= 149 with a non-empty relic grab bag. CalculateVars
    // rolls the tribute cost as 149 - NextInt(0, 50). Reach Into The Flesh
    // removes two cards then adds SporeMind; Offer Tribute spends the rolled
    // cost and pulls the next relic from the front of the player's bag.
    {
        RunContext r;
        r.init(930160, 0);
        r.gold = 149;
        check("choir_allowed_at_149",
              event_is_allowed(r, event_id("LUMINOUS_CHOIR")), 1);
        event_begin(r, event_id("LUMINOUS_CHOIR"), false);
        const int cost = r.eventData[0];
        // C#: 149 - NextInt(0, 50), upper-exclusive -> 100..149.
        check("choir_cost_range", cost >= 100 && cost <= 149, 1);
        r.gold = 0;
        check("choir_tribute_locked_without_gold", event_option_available(r, 1), 0);
        const int deck = r.deckCount;
        event_choose(r, 0);
        check("choir_reach_starts_selection", r.eventCardSelection, 6);
        int first = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { first = i; break; }
        event_select_card(r, first);
        check("choir_reach_still_selecting", r.eventCardSelection, 6);
        int second = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { second = i; break; }
        event_select_card(r, second);
        check("choir_reach_net_deck", r.deckCount, deck - 1);
        check("choir_reach_spore_mind",
              r.deck[r.deckCount - 1].id == CardId::SPORE_MIND, 1);
    }
    {
        RunContext r;
        r.init(930161, 0);
        r.gold = 200;
        const int relics = r.relicCount;
        event_begin(r, event_id("LUMINOUS_CHOIR"), false);
        const int cost = r.eventData[0];
        check("choir_tribute_available", event_option_available(r, 1), 1);
        event_choose(r, 1);
        check("choir_tribute_gold", r.gold, 200 - cost);
        check("choir_tribute_relic", r.relicCount, relics + 1);
    }
    {
        RunContext r;
        r.init(930162, 0);
        r.gold = 148;
        check("choir_requires_149",
              event_is_allowed(r, event_id("LUMINOUS_CHOIR")), 0);
    }

    // ------------------------------ MorphicGrove
    // C#: allowed at gold >= 100 with >= 2 transformable cards. Group spends
    // all gold and transforms two selected cards; Loner gains 5 max HP.
    {
        RunContext r;
        r.init(930170, 0);
        r.gold = 99;
        check("grove_requires_100",
              event_is_allowed(r, event_id("MORPHIC_GROVE")), 0);
        r.gold = 100;
        check("grove_allowed_at_100",
              event_is_allowed(r, event_id("MORPHIC_GROVE")), 1);
        const int deck = r.deckCount;
        event_begin(r, event_id("MORPHIC_GROVE"), false);
        event_choose(r, 0);
        check("grove_group_spends_all_gold", r.gold, 0);
        check("grove_group_starts_selection", r.eventCardSelection, 4);
        int first = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { first = i; break; }
        event_select_card(r, first);
        check("grove_group_still_selecting", r.eventCardSelection, 4);
        int second = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { second = i; break; }
        event_select_card(r, second);
        check("grove_group_keeps_deck_size", r.deckCount, deck);
        check("grove_group_finished", r.screen != RunScreen::EVENT, 1);
    }
    {
        RunContext r;
        r.init(930171, 0);
        const int maxHp = r.maxHp;
        const int hp = r.hp;
        event_begin(r, event_id("MORPHIC_GROVE"), false);
        event_choose(r, 1);
        check("grove_loner_max_hp", r.maxHp, maxHp + 5);
        check("grove_loner_hp", r.hp, hp + 5);
    }

    // ------------------------------ Bugslayer
    {
        RunContext r;
        r.init(930180, 0);
        const int deck = r.deckCount;
        event_begin(r, event_id("BUGSLAYER"), false);
        event_choose(r, 0);
        check("bugslayer_exterminate_added", r.deckCount, deck + 1);
        check("bugslayer_exterminate_id", static_cast<int>(r.deck[deck].id),
              static_cast<int>(CardId::EXTERMINATE));
        check("bugslayer_finished", r.screen != RunScreen::EVENT, 1);
        event_begin(r, event_id("BUGSLAYER"), false);
        event_choose(r, 1);
        check("bugslayer_squash_id", static_cast<int>(r.deck[deck + 1].id),
              static_cast<int>(CardId::SQUASH));
    }

    // ------------------------------ EndlessConveyor
    // C#: allowed at gold >= 120; every grab costs 40 gold (even the free
    // Golden Fysh dish still locks its option below 40). Dish enum in
    // events.cpp: 1 caviar, 5 suspicious condiment, 7 golden fysh,
    // 8 seapunk salad (every 5th roll).
    {
        RunContext r;
        r.init(930190, 0);
        r.gold = 119;
        check("conveyor_requires_120",
              event_is_allowed(r, event_id("ENDLESS_CONVEYOR")), 0);
        r.gold = 120;
        check("conveyor_allowed_at_120",
              event_is_allowed(r, event_id("ENDLESS_CONVEYOR")), 1);
        event_begin(r, event_id("ENDLESS_CONVEYOR"), false);
        check("conveyor_page0", r.eventPage, 0);
        check("conveyor_initial_options", event_option_count(r), 2);
        check("conveyor_initial_no_gold_spent", r.gold, 120);

        // Caviar: pay 40, gain 4 max HP, advance to the grab page.
        r.gold = 1000;
        r.maxHp = 80;
        r.hp = 80;
        r.eventData[3] = 1;
        event_choose(r, 0);
        check("conveyor_caviar_gold", r.gold, 960);
        check("conveyor_caviar_max_hp", r.maxHp, 84);
        check("conveyor_grab_page", r.eventPage, 1);
        check("conveyor_grab_page_options", event_option_count(r), 2);
        check("conveyor_grab_page_still_open", r.screen == RunScreen::EVENT, 1);

        // Golden Fysh is free but still requires the 40-gold unlock.
        r.eventData[3] = 7;
        event_choose(r, 0);
        check("conveyor_golden_fysh_gold", r.gold, 1035);
        r.gold = 39;
        check("conveyor_grab_locked",
              event_option_available(r, 0), 0);
        r.gold = 1000;

        // Seapunk Salad adds Feeding Frenzy; the fifth roll also forces the
        // next dish to Seapunk Salad (no RNG consumed).
        const int deck = r.deckCount;
        r.eventData[1] = 4;
        r.eventData[3] = 8;
        event_choose(r, 0);
        check("conveyor_seapunk_deck", r.deckCount, deck + 1);
        check("conveyor_seapunk_id",
              static_cast<int>(r.deck[deck].id),
              static_cast<int>(CardId::FEEDING_FRENZY_CARD));
        check("conveyor_seapunk_current", r.eventData[3], 8);
    }
    {
        RunContext r;
        r.init(930191, 0);
        r.gold = 120;
        int upgradable = 0;
        for (int i = 0; i < r.deckCount; ++i) upgradable += card_upgradable(r.deck[i]);
        event_begin(r, event_id("ENDLESS_CONVEYOR"), false);
        event_choose(r, 1);  // ObserveChef upgrades one random card.
        int upgraded = 0;
        for (int i = 0; i < r.deckCount; ++i) upgraded += r.deck[i].upgraded;
        check("conveyor_observe_upgrades_one", upgraded, upgradable > 0 ? 1 : 0);
        check("conveyor_observe_finished", r.screen != RunScreen::EVENT, 1);
    }

    // ------------------------------ Trial
    // C#: Accept rolls NextInt(3) for merchant/noble/nondescript; Reject opens
    // a page with Accept or an abandon-run DoubleDown. eventData[0] stores the
    // trial kind and eventData[1] the remaining multi-card selections.
    {
        RunContext r;
        r.init(930200, 0);
        event_begin(r, event_id("TRIAL"), false);
        check("trial_page0", r.eventPage, 0);
        check("trial_options", event_option_count(r), 2);
        event_choose(r, 0);
        check("trial_accept_page", r.eventPage, 1);
        check("trial_kind_range", r.eventData[0] >= 0 && r.eventData[0] <= 2, 1);

        // Merchant guilty: Regret plus two front relics.
        r.eventPage = 1;
        r.eventData[0] = 0;
        const int deck = r.deckCount;
        const int relics = r.relicCount;
        event_choose(r, 0);
        check("trial_merchant_guilty_curse", r.deckCount, deck + 1);
        check("trial_merchant_guilty_curse_id",
              static_cast<int>(r.deck[deck].id),
              static_cast<int>(CardId::REGRET));
        check("trial_merchant_guilty_relics", r.relicCount, relics + 2);

        // Merchant innocent: Shame plus two selected upgrades.
        RunContext m;
        m.init(930203, 0);
        event_begin(m, event_id("TRIAL"), false);
        m.eventPage = 1;
        m.eventData[0] = 0;
        event_choose(m, 1);
        check("trial_merchant_innocent_curse",
              static_cast<int>(m.deck[m.deckCount - 1].id),
              static_cast<int>(CardId::SHAME));
        check("trial_merchant_innocent_selection", m.eventCardSelection, 1);
        int first = -1, second = -1;
        for (int i = 0; i < m.deckCount; ++i)
            if (event_card_selectable(m, i)) {
                if (first < 0) first = i; else if (second < 0) second = i;
            }
        event_select_card(m, first);
        check("trial_two_selections_remaining", m.eventData[1], 1);
        if (second >= 0) event_select_card(m, second);
        check("trial_two_upgrades_finished", m.screen != RunScreen::EVENT, 1);

        // Noble: guilty heals 10, innocent gives Regret + 300 gold.
        RunContext n;
        n.init(930204, 0);
        event_begin(n, event_id("TRIAL"), false);
        n.eventPage = 1;
        n.eventData[0] = 1;
        n.hp = 30;
        n.maxHp = 80;
        event_choose(n, 0);
        check("trial_noble_guilty_heal", n.hp, 40);
        RunContext ni;
        ni.init(930206, 0);
        event_begin(ni, event_id("TRIAL"), false);
        ni.eventPage = 1;
        ni.eventData[0] = 1;
        const int gold = ni.gold;
        event_choose(ni, 1);
        check("trial_noble_innocent_gold", ni.gold, gold + 300);
        check("trial_noble_innocent_curse",
              static_cast<int>(ni.deck[ni.deckCount - 1].id),
              static_cast<int>(CardId::REGRET));

        // Nondescript guilty: Doubt plus two 3-card custom rewards.
        RunContext d;
        d.init(930205, 0);
        event_begin(d, event_id("TRIAL"), false);
        d.eventPage = 1;
        d.eventData[0] = 2;
        event_choose(d, 0);
        int pending = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) pending += d.rewardCardPending[i];
        check("trial_nondescript_guilty_rewards", pending, 2);
        check("trial_nondescript_guilty_curse",
              static_cast<int>(d.deck[d.deckCount - 1].id),
              static_cast<int>(CardId::DOUBT));

        // Nondescript innocent: Doubt plus two selected transformations.
        RunContext t;
        t.init(930201, 0);
        event_begin(t, event_id("TRIAL"), false);
        t.eventPage = 1;
        t.eventData[0] = 2;
        t.eventData[1] = 0;
        event_choose(t, 1);
        check("trial_nondescript_innocent_selection",
              t.eventCardSelection, 4);
        check("trial_nondescript_innocent_curse",
              static_cast<int>(t.deck[t.deckCount - 1].id),
              static_cast<int>(CardId::DOUBT));
        int x = -1, y = -1;
        for (int i = 0; i < t.deckCount; ++i)
            if (event_card_selectable(t, i)) {
                if (x < 0) x = i; else if (y < 0) y = i;
            }
        event_select_card(t, x);
        if (y >= 0) event_select_card(t, y);
        check("trial_nondescript_innocent_finished",
              t.screen != RunScreen::EVENT, 1);

        // Reject -> Accept re-rolls; Reject -> DoubleDown abandons the run.
        RunContext u;
        u.init(930202, 0);
        event_begin(u, event_id("TRIAL"), false);
        event_choose(u, 1);
        check("trial_reject_page", u.eventPage, 2);
        event_choose(u, 0);
        check("trial_reject_accept_page", u.eventPage, 1);
        event_begin(u, event_id("TRIAL"), false);
        event_choose(u, 1);
        event_choose(u, 1);
        check("trial_double_down_abandons", u.screen == RunScreen::RUN_OVER, 1);
        check("trial_double_down_not_won", u.won, 0);
    }

    // ------------------------------ PunchOff
    // C#: allowed at total floor >= 6; CalculateVars rolls 91..99; Nab adds
    // Injury + relic reward; Fight enters the PunchOff encounter and defers a
    // relic and potion reward to the post-combat reward screen.
    {
        RunContext r;
        r.init(930210, 0);
        r.floor = 5;
        check("punchoff_requires_floor6",
              event_is_allowed(r, event_id("PUNCH_OFF")), 0);
        r.floor = 6;
        check("punchoff_allowed_floor6",
              event_is_allowed(r, event_id("PUNCH_OFF")), 1);
        event_begin(r, event_id("PUNCH_OFF"), false);
        // C#: NextInt(91, 99), upper-exclusive -> 91..98.
        check("punchoff_flavour_gold_range",
              r.eventData[0] >= 91 && r.eventData[0] <= 98, 1);
        check("punchoff_options", event_option_count(r), 2);
        const int deck = r.deckCount;
        event_choose(r, 0);
        check("punchoff_nab_injury", r.deckCount, deck + 1);
        check("punchoff_nab_injury_id", static_cast<int>(r.deck[deck].id),
              static_cast<int>(CardId::INJURY));
        check("punchoff_nab_relic_reward", r.pendingRelicCount > 0, 1);

        RunContext f;
        f.init(930211, 0);
        f.floor = 10;
        event_begin(f, event_id("PUNCH_OFF"), false);
        event_choose(f, 1);
        check("punchoff_take_them_page", f.eventPage, 1);
        check("punchoff_take_them_options", event_option_count(f), 1);
        event_choose(f, 0);
        check("punchoff_fight_combat", f.screen == RunScreen::COMBAT, 1);
        check("punchoff_fight_relic_flag", f.eventData[1], 1);
        check("punchoff_fight_potion_flag", f.eventData[2], 1);
        check("punchoff_fight_encounter",
              static_cast<int>(f.battle.encounter),
              static_cast<int>(Encounter::SETUP_PUNCH_OFF));
        for (int i = 0; i < f.battle.monsterCount; ++i) {
            const int reduction =
                f.battle.monsters[i].maxHp - f.battle.monsters[i].hp;
            // C#: StartingHpReduction = Rng.NextInt(2, 10) -> 2..9.
            check("punchoff_construct_hp_reduction",
                  reduction >= 2 && reduction <= 9, 1);
        }
        // PunchOffEventEncounter keeps the default ShouldGiveRewards=true:
        // normal monster rewards (gold, potion roll, 3-card reward) come first,
        // then the event's RelicReward and PotionReward extras.
        for (int i = 0; i < f.battle.monsterCount; ++i) {
            f.battle.monsters[i].hp = 0;
            f.battle.monsters[i].alive = false;
        }
        f.battle.outcome = Outcome::PLAYER_VICTORY;
        f.finish_combat();
        check("punchoff_standard_gold",
              f.pendingGoldReward >= 10 && f.pendingGoldReward <= 20, 1);
        check("punchoff_standard_cards", f.rewardCardCounts[0], 3);
        check("punchoff_standard_card_pending", f.rewardCardPending[0], 1);
        check("punchoff_extra_relic", f.pendingRelicCount, 1);
        check("punchoff_extra_potion", f.pendingPotionCount >= 1, 1);
        check("punchoff_extras_cleared", f.eventData[1] + f.eventData[2], 0);
        check("punchoff_fight_done", f.eventId, -1);
        check("punchoff_fight_reward_screen", f.screen == RunScreen::REWARDS, 1);
    }

    // DenseVegetationEventEncounter also keeps standard monster rewards; the
    // event passes shouldResumeAfterCombat=false, so the room ends on leave.
    {
        RunContext d;
        d.init(930212, 0);
        event_begin(d, event_id("DENSE_VEGETATION"), false);
        event_choose(d, 1);  // page 1: fight
        check("dense_vegetation_fight_page", d.screen == RunScreen::EVENT, 1);
        event_choose(d, 0);
        check("dense_vegetation_fight_combat",
              d.screen == RunScreen::COMBAT, 1);
        check("dense_vegetation_fight_encounter",
              static_cast<int>(d.battle.encounter),
              static_cast<int>(Encounter::SETUP_DENSE_VEGETATION));
        for (int i = 0; i < d.battle.monsterCount; ++i) {
            d.battle.monsters[i].hp = 0;
            d.battle.monsters[i].alive = false;
        }
        d.battle.outcome = Outcome::PLAYER_VICTORY;
        d.finish_combat();
        check("dense_vegetation_standard_gold",
              d.pendingGoldReward >= 10 && d.pendingGoldReward <= 20, 1);
        check("dense_vegetation_standard_cards", d.rewardCardCounts[0], 3);
        check("dense_vegetation_no_extra_relic", d.pendingRelicCount, 0);
        check("dense_vegetation_event_done", d.eventId, -1);
        check("dense_vegetation_reward_screen",
              d.screen == RunScreen::REWARDS, 1);
    }

    // ------------------------------ BattlewornDummy
    // C#: three settings enter BattleFriendV1/V2/V3 with no standard rewards,
    // BattlewornDummyTimeLimitPower 3 escapes the dummy after the third enemy
    // turn end (RanOutOfTime -> DEFEAT page). Victory grants one uniform
    // character+shared potion (V1), two StableShuffle upgrades (V2), or the
    // front relic (V3).
    {
        RunContext r;
        r.init(930230, 0);
        event_begin(r, event_id("BATTLEWORN_DUMMY"), false);
        check("battleworn_options", event_option_count(r), 3);

        RunContext f;
        f.init(930231, 0);
        event_begin(f, event_id("BATTLEWORN_DUMMY"), false);
        f.eventData[3] = 77;  // begin clears event state
        event_begin(f, event_id("BATTLEWORN_DUMMY"), false);
        check("battleworn_begin_clears_data", f.eventData[3], 0);
        event_choose(f, 0);
        check("battleworn_v1_combat", f.screen == RunScreen::COMBAT, 1);
        check("battleworn_v1_encounter", static_cast<int>(f.battle.encounter),
              static_cast<int>(Encounter::SETUP_BATTLEWORN_DUMMY_V1));
        check("battleworn_v1_monster", static_cast<int>(f.battle.monsters[0].id),
              static_cast<int>(MonsterId::BATTLE_FRIEND_V1));
        check("battleworn_v1_hp", f.battle.monsters[0].maxHp, 75);
        const int limitIdx = static_cast<int>(PowerId::BATTLEWORN_DUMMY_TIME_LIMIT);
        check("battleworn_v1_time_limit", f.battle.monsters[0].power[limitIdx], 3);
        f.battle.end_player_turn();
        check("battleworn_v1_time_limit_after_turn1",
              f.battle.monsters[0].power[limitIdx], 2);
        f.battle.end_player_turn();
        check("battleworn_v1_time_limit_after_turn2",
              f.battle.monsters[0].power[limitIdx], 1);
        f.battle.end_player_turn();
        check("battleworn_v1_escaped", f.battle.monsters[0].alive, 0);
        check("battleworn_v1_escaped_with_hp",
              f.battle.monsters[0].hp > 0, 1);
        check("battleworn_v1_victory_after_escape",
              f.battle.outcome == Outcome::PLAYER_VICTORY, 1);
        f.finish_combat();
        check("battleworn_v1_ran_out_finished", f.eventId, -1);
        check("battleworn_v1_ran_out_no_rewards",
              f.screen == RunScreen::MAP, 1);
        check("battleworn_v1_ran_out_no_potion",
              f.pendingPotionCount, 0);

        // Defeat-by-time is distinct from a kill: the kill path offers a potion.
        RunContext k;
        k.init(930232, 0);
        event_begin(k, event_id("BATTLEWORN_DUMMY"), false);
        event_choose(k, 0);
        k.battle.monsters[0].hp = 0;
        k.battle.monsters[0].alive = false;
        k.battle.outcome = Outcome::PLAYER_VICTORY;
        k.finish_combat();
        check("battleworn_v1_kill_reward_screen",
              k.screen == RunScreen::REWARDS, 1);
        check("battleworn_v1_kill_potion", k.pendingPotionCount, 1);
        check("battleworn_v1_kill_event_done", k.eventId, -1);

        // V2 upgrades two random upgradable deck cards.
        RunContext v2;
        v2.init(930233, 0);
        int upgradedBefore = 0;
        for (int i = 0; i < v2.deckCount; ++i) upgradedBefore += v2.deck[i].upgraded;
        event_begin(v2, event_id("BATTLEWORN_DUMMY"), false);
        event_choose(v2, 1);
        check("battleworn_v2_monster", static_cast<int>(v2.battle.monsters[0].id),
              static_cast<int>(MonsterId::BATTLE_FRIEND_V2));
        check("battleworn_v2_hp", v2.battle.monsters[0].maxHp, 150);
        v2.battle.monsters[0].hp = 0;
        v2.battle.monsters[0].alive = false;
        v2.battle.outcome = Outcome::PLAYER_VICTORY;
        v2.finish_combat();
        int upgradedAfter = 0;
        for (int i = 0; i < v2.deckCount; ++i) upgradedAfter += v2.deck[i].upgraded;
        check("battleworn_v2_two_upgrades", upgradedAfter - upgradedBefore, 2);
        check("battleworn_v2_no_reward_screen",
              v2.screen == RunScreen::MAP, 1);

        // V3 offers the front relic through the reward screen.
        RunContext v3;
        v3.init(930234, 0);
        event_begin(v3, event_id("BATTLEWORN_DUMMY"), false);
        event_choose(v3, 2);
        check("battleworn_v3_monster", static_cast<int>(v3.battle.monsters[0].id),
              static_cast<int>(MonsterId::BATTLE_FRIEND_V3));
        check("battleworn_v3_hp", v3.battle.monsters[0].maxHp, 300);
        v3.battle.monsters[0].hp = 0;
        v3.battle.monsters[0].alive = false;
        v3.battle.outcome = Outcome::PLAYER_VICTORY;
        v3.finish_combat();
        check("battleworn_v3_relic_reward", v3.pendingRelicCount, 1);
        check("battleworn_v3_reward_screen",
              v3.screen == RunScreen::REWARDS, 1);
    }

    // ------------------------------ ThisOrThat
    // C#: CalculateVars rolls gold 41..68 before options. PLAIN loses 6 HP then
    // gains that gold; ORNATE pulls the front relic and adds a Clumsy curse.
    {
        RunContext p;
        p.init(930250, 0);
        const int hp = p.hp, gold = p.gold;
        event_begin(p, event_id("THIS_OR_THAT"), false);
        check("thisorthat_options", event_option_count(p), 2);
        check("thisorthat_gold_range",
              p.eventData[0] >= 41 && p.eventData[0] <= 68, 1);
        const int rolled = p.eventData[0];
        event_choose(p, 0);
        check("thisorthat_plain_hp", p.hp, hp - 6);
        check("thisorthat_plain_gold", p.gold, gold + rolled);
        check("thisorthat_plain_done", p.eventId, -1);

        RunContext o;
        o.init(930251, 0);
        const int deck = o.deckCount, relics = o.relicCount;
        event_begin(o, event_id("THIS_OR_THAT"), false);
        event_choose(o, 1);
        check("thisorthat_ornate_curse", o.deckCount, deck + 1);
        check("thisorthat_ornate_curse_id",
              static_cast<int>(o.deck[deck].id), static_cast<int>(CardId::CLUMSY));
        check("thisorthat_ornate_relic", o.relicCount, relics + 1);
        check("thisorthat_ornate_done", o.eventId, -1);
    }

    // ------------------------------ TheLanternKey
    // C#: RETURN_THE_KEY gains 100 gold; KEEP_THE_KEY offers FIGHT, which
    // enters MysteriousKnightEventEncounter (FlailKnight 101 HP, Strength 6,
    // Plating 6) and offers the fixed LanternKey special card after victory.
    {
        RunContext r;
        r.init(930240, 0);
        const int gold = r.gold;
        event_begin(r, event_id("THE_LANTERN_KEY"), false);
        check("lanternkey_options", event_option_count(r), 2);
        event_choose(r, 0);
        check("lanternkey_return_gold", r.gold, gold + 100);
        check("lanternkey_return_finished", r.eventId, -1);

        RunContext k;
        k.init(930241, 0);
        event_begin(k, event_id("THE_LANTERN_KEY"), false);
        event_choose(k, 1);
        check("lanternkey_keep_page", k.eventPage, 1);
        check("lanternkey_keep_options", event_option_count(k), 1);
        event_choose(k, 0);
        check("lanternkey_fight_combat", k.screen == RunScreen::COMBAT, 1);
        check("lanternkey_encounter", static_cast<int>(k.battle.encounter),
              static_cast<int>(Encounter::SETUP_MYSTERIOUS_KNIGHT));
        const Monster &mk = k.battle.monsters[0];
        check("lanternkey_knight_id", static_cast<int>(mk.id),
              static_cast<int>(MonsterId::MYSTERIOUS_KNIGHT));
        check("lanternkey_knight_hp", mk.maxHp, 101);
        check("lanternkey_knight_strength", mk.strength, 6);
        check("lanternkey_knight_plating",
              mk.power[static_cast<int>(PowerId::PLATING)], 6);
        const int initial = mk.move;  // FlailKnight starts on RAM.
        check("lanternkey_knight_initial_ram", initial, 3);
        k.battle.monsters[0].hp = 0;
        k.battle.monsters[0].alive = false;
        k.battle.outcome = Outcome::PLAYER_VICTORY;
        k.finish_combat();
        check("lanternkey_reward_screen", k.screen == RunScreen::REWARDS, 1);
        check("lanternkey_standard_gold",
              k.pendingGoldReward >= 10 && k.pendingGoldReward <= 20, 1);
        check("lanternkey_standard_cards", k.rewardCardCounts[0], 3);
        check("lanternkey_standard_card_pending", k.rewardCardPending[0], 1);
        check("lanternkey_special_card_pending", k.pendingCardReward, 1);
        check("lanternkey_special_card_count", k.rewardCardCounts[1], 1);
        check("lanternkey_special_card_pending_slot", k.rewardCardPending[1], 1);
        check("lanternkey_special_card_id",
              static_cast<int>(k.rewardCards[1][0].id),
              static_cast<int>(CardId::LANTERN_KEY));
        check("lanternkey_event_done", k.eventId, -1);

        // A8+ scales the inherited FlailKnight initial HP to 108.
        RunContext a;
        a.init(930242, 0);
        a.ascension = 8;
        event_begin(a, event_id("THE_LANTERN_KEY"), false);
        event_choose(a, 1);
        event_choose(a, 0);
        check("lanternkey_a8_knight_hp", a.battle.monsters[0].maxHp, 108);
    }

    // ------------------------------ StoneOfAllTime
    // C#: NextItem(Player.Potions) picks among non-null physical slots; Lift
    // discards that potion (leaving the slot empty) and gains 10 max HP.
    {
        RunContext r;
        r.init(930260, 0);
        r.act = 1;
        r.potionSlots = 3;
        r.potions[0] = 0;
        r.potions[1] = static_cast<int>(PotionId::FOUL_POTION);
        r.potions[2] = 0;
        r.potionCount = 1;
        event_begin(r, event_id("STONE_OF_ALL_TIME"), false);
        check("stone_potion_index_nonnull", r.eventData[0], 0);
        event_choose(r, 0);
        check("stone_lift_slot_cleared", r.potions[1], 0);
        check("stone_lift_empty_slot_kept", r.potions[0], 0);
        check("stone_lift_potion_count", r.potionCount, 0);
        check("stone_lift_max_hp", r.maxHp, 90);
        check("stone_lift_finished", r.eventId, -1);
    }

    // ------------------------------ DenseVegetation / BrainLeech
    // DenseVegetation: gold 61..99, TRUDGE_ON loses 8 and gains it; Rest heals
    // 30% max HP before offering the fight. BrainLeech: ShareKnowledge picks 1
    // of 5 noncombat Ironclad cards; Rip loses 5 HP and offers 3 colorless.
    {
        RunContext d;
        d.init(930270, 0);
        event_begin(d, event_id("DENSE_VEGETATION"), false);
        const int rolled = d.eventData[0];
        check("dense_vegetation_gold_range", rolled >= 61 && rolled <= 99, 1);
        const int hp = d.hp, gold = d.gold;
        event_choose(d, 0);
        check("dense_vegetation_trudge_hp", d.hp, hp - 8);
        check("dense_vegetation_trudge_gold", d.gold, gold + rolled);
        check("dense_vegetation_trudge_done", d.eventId, -1);

        RunContext b;
        b.init(930271, 0);
        event_begin(b, event_id("BRAIN_LEECH"), false);
        event_choose(b, 0);
        check("brain_leech_grid_kind", b.cardGrid.kind, 1);
        check("brain_leech_grid_candidates", b.cardGrid.count, 5);
        check("brain_leech_grid_select_one", b.cardGrid.minSelect, 1);
        check("brain_leech_grid_max_one", b.cardGrid.maxSelect, 1);

        RunContext c;
        c.init(930272, 0);
        const int ripHp = c.hp;
        event_begin(c, event_id("BRAIN_LEECH"), false);
        event_choose(c, 1);
        check("brain_leech_rip_hp", c.hp, ripHp - 5);
        check("brain_leech_rip_card_reward", c.pendingCardReward, 1);
        check("brain_leech_rip_cards", c.rewardCardCounts[0], 3);
        check("brain_leech_rip_done", c.eventId, -1);
    }

    // ------------------------------ PotionCourier / SpiritGrafter
    // PotionCourier: GrabPotions offers three fixed FoulPotions; Ransack picks
    // one random uncommon character/shared potion via the rewards RNG.
    // SpiritGrafter: LetItIn heals 25 and adds Metamorphosis; Rejection upgrades
    // one card then takes 10 unblockable/unpowered damage.
    {
        RunContext p;
        p.init(930273, 0);
        p.act = 1;
        event_begin(p, event_id("POTION_COURIER"), false);
        event_choose(p, 0);
        check("potion_courier_foul_count", p.pendingPotionCount, 3);
        check("potion_courier_foul_ids",
              p.pendingPotions[0] == static_cast<int>(PotionId::FOUL_POTION) &&
              p.pendingPotions[1] == static_cast<int>(PotionId::FOUL_POTION) &&
              p.pendingPotions[2] == static_cast<int>(PotionId::FOUL_POTION), 1);

        RunContext q;
        q.init(930274, 0);
        q.act = 1;
        event_begin(q, event_id("POTION_COURIER"), false);
        const std::int64_t counter = q.playerRng[PRNG_REWARDS].counter;
        event_choose(q, 1);
        check("potion_courier_ransack_rng",
              q.playerRng[PRNG_REWARDS].counter > counter, 1);
        check("potion_courier_ransack_reward", q.pendingPotionCount, 1);
        check("potion_courier_ransack_uncommon",
              potion_def(static_cast<PotionId>(q.pendingPotions[0])).rarity ==
                  Rarity::UNCOMMON, 1);

        RunContext s;
        s.init(930275, 0);
        s.hp = 50;
        const int deck = s.deckCount;
        event_begin(s, event_id("SPIRIT_GRAFTER"), false);
        event_choose(s, 0);
        check("spirit_grafter_letit_hp", s.hp, 75);
        check("spirit_grafter_letit_card", s.deckCount, deck + 1);
        check("spirit_grafter_letit_id",
              static_cast<int>(s.deck[deck].id),
              static_cast<int>(CardId::METAMORPHOSIS));

        RunContext t;
        t.init(930276, 0);
        t.hp = 60;
        event_begin(t, event_id("SPIRIT_GRAFTER"), false);
        event_choose(t, 1);
        check("spirit_grafter_rejection_selection", t.eventCardSelection, 5);
        int target = -1;
        for (int i = 0; i < t.deckCount; ++i)
            if (event_card_selectable(t, i)) { target = i; break; }
        check("spirit_grafter_rejection_target", target >= 0, 1);
        event_select_card(t, target);
        check("spirit_grafter_rejection_upgraded", t.deck[target].upgraded, 1);
        check("spirit_grafter_rejection_hp", t.hp, 50);
        check("spirit_grafter_rejection_done", t.eventId, -1);
    }

    // ------------------------------ Orobas
    // C#: OptionPool3 offers TouchOfOrobas only with a Starter-rarity relic
    // and ArchaicTooth only with Bash/Neutralize/Unleash/FallingStar/Dualcast
    // in the deck; with neither, the third entry is a locked/disabled option.
    {
        RunContext o;
        o.init(930280, 0);
        event_begin(o, event_id("OROBAS"), false);
        check("orobas_options", event_option_count(o), 3);
        check("orobas_third_available_with_starter",
              event_option_available(o, 2), 1);

        RunContext l;
        l.init(930281, 0);
        l.relicCount = 0;
        int write = 0;
        for (int i = 0; i < l.deckCount; ++i) {
            if (l.deck[i].id == CardId::BASH) continue;
            l.deck[write++] = l.deck[i];
        }
        l.deckCount = write;
        event_begin(l, event_id("OROBAS"), false);
        check("orobas_third_locked", event_option_available(l, 2), 0);
        check("orobas_locked_not_selectable", event_choose(l, 2), 0);
    }

    // ------------------------------ RanwidTheElder / RelicTrader
    // C#: Ranwid needs act > 0, gold >= 100, a potion and a tradable relic;
    // options trade the chosen potion / 100 gold / chosen relic. RelicTrader
    // needs act > 0 and >= 5 tradable relics, offers three StableShuffle-picked
    // trades and pulls the replacement relics up front.
    {
        RunContext r;
        r.init(930220, 0);
        r.act = 0;
        r.gold = 150;
        r.add_potion(PotionId::BLOCK_POTION);
        r.add_relic(RelicId::ANCHOR);
        check("ranwid_needs_act2",
              event_is_allowed(r, event_id("RANWID_THE_ELDER")), 0);
        r.act = 1;
        check("ranwid_allowed", event_is_allowed(r, event_id("RANWID_THE_ELDER")), 1);
        check("ranwid_starter_not_tradable",
              relic_is_tradable(r, 0), 0);  // Burning Blood
        event_begin(r, event_id("RANWID_THE_ELDER"), false);
        check("ranwid_options", event_option_count(r), 3);
        check("ranwid_potion_choice_slot", r.eventData[0] >= 0, 1);
        check("ranwid_relic_choice_slot", r.eventData[1] >= 0, 1);
        check("ranwid_relic_choice_tradable",
              relic_is_tradable(r, r.eventData[1]), 1);

        const int potions = r.potionCount;
        const int relics = r.relicCount;
        event_choose(r, 0);
        check("ranwid_trade_potion_removed", r.potionCount, potions - 1);
        check("ranwid_trade_potion_relic", r.relicCount, relics + 1);
        check("ranwid_trade_finished", r.screen != RunScreen::EVENT, 1);

        RunContext g;
        g.init(930221, 0);
        g.act = 1;
        g.gold = 150;
        g.add_potion(PotionId::BLOCK_POTION);
        g.add_relic(RelicId::ANCHOR);
        event_begin(g, event_id("RANWID_THE_ELDER"), false);
        event_choose(g, 1);
        check("ranwid_trade_gold", g.gold, 50);
        check("ranwid_trade_gold_relic", g.relicCount, relics + 1);

        RunContext x;
        x.init(930222, 0);
        x.act = 1;
        x.gold = 150;
        x.add_potion(PotionId::BLOCK_POTION);
        x.add_relic(RelicId::ANCHOR);
        event_begin(x, event_id("RANWID_THE_ELDER"), false);
        const int tradedSlot = x.eventData[1];
        const int tradedId = x.relics[tradedSlot];
        const int relicCount = x.relicCount;
        event_choose(x, 2);
        check("ranwid_trade_relic_net", x.relicCount, relicCount + 1);
        int tradedLeft = 0;
        for (int i = 0; i < x.relicCount; ++i)
            tradedLeft += x.relics[i] == tradedId ? 1 : 0;
        check("ranwid_trade_relic_removed", tradedLeft, 0);
    }
    {
        RunContext r;
        r.init(930223, 0);
        r.act = 1;
        r.add_relic(RelicId::ANCHOR);
        r.add_relic(RelicId::BLOOD_VIAL);
        r.add_relic(RelicId::BAG_OF_PREPARATION);
        r.add_relic(RelicId::LANTERN);
        check("relic_trader_needs_five",
              event_is_allowed(r, event_id("RELIC_TRADER")), 0);
        r.add_relic(RelicId::MEAL_TICKET);
        check("relic_trader_allowed",
              event_is_allowed(r, event_id("RELIC_TRADER")), 1);
        event_begin(r, event_id("RELIC_TRADER"), false);
        check("relic_trader_options", event_option_count(r), 3);
        check("relic_trader_choice_count", r.eventData[3], 3);
        check("relic_trader_new_relics", r.eventRelics[0] != 0 &&
              r.eventRelics[1] != 0 && r.eventRelics[2] != 0, 1);
        const int ownedSlot = r.eventData[1];
        const int oldId = r.relics[ownedSlot];
        const RelicId newId = static_cast<RelicId>(r.eventRelics[1]);
        const int count = r.relicCount;
        event_choose(r, 1);
        check("relic_trader_net_relics", r.relicCount, count);
        bool found = false;
        for (int i = 0; i < r.relicCount; ++i)
            found |= static_cast<RelicId>(r.relics[i]) == newId;
        check("relic_trader_obtained_new", found, 1);
        bool oldFound = false;
        for (int i = 0; i < r.relicCount; ++i)
            oldFound |= r.relics[i] == oldId;
        check("relic_trader_removed_old", oldFound, 0);
    }

    // ------------------------------ SelfHelpBook / WoodCarvings
    // Sharp: +2 damage on Attack cards. Slither: playable non-X cards,
    // random cost 0..3 each time drawn. SelfHelpBook offers the three
    // enchantments that have targets; WoodCarvings transforms a Basic card to
    // Peck/ToricToughness or enchants one card with Slither.
    {
        Card strike = Card{};
        strike.id = CardId::STRIKE_IRONCLAD;
        strike.uid = 1;
        Card defend = Card{};
        defend.id = CardId::DEFEND_IRONCLAD;
        defend.uid = 2;
        check("sharp_attack_allowed", card_can_enchant(strike, EnchantmentId::SHARP), 1);
        check("sharp_skill_rejected", card_can_enchant(defend, EnchantmentId::SHARP), 0);
        check("slither_strike_allowed", card_can_enchant(strike, EnchantmentId::SLITHER), 1);
        Card whirlwind = Card{};
        whirlwind.id = CardId::WHIRLWIND;
        whirlwind.uid = 3;
        check("slither_x_cost_rejected",
              card_can_enchant(whirlwind, EnchantmentId::SLITHER), 0);

        RunContext r;
        r.init(930230, 0);
        event_begin(r, event_id("SELF_HELP_BOOK"), false);
        check("selfhelp_options", event_option_count(r), 3);
        check("selfhelp_sharp_available", event_option_available(r, 0), 1);
        check("selfhelp_swift_locked", event_option_available(r, 2), 0);
        event_choose(r, 0);
        check("selfhelp_sharp_selection", r.eventCardSelection, 7);
        int attack = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { attack = i; break; }
        event_select_card(r, attack);
        check("selfhelp_sharp_applied",
              static_cast<int>(r.deck[attack].enchantment),
              static_cast<int>(EnchantmentId::SHARP));
        check("selfhelp_sharp_amount", r.deck[attack].enchantmentAmount, 2);
        check("selfhelp_finished", r.screen != RunScreen::EVENT, 1);

        RunContext e;
        e.init(930231, 0);
        e.deckCount = 0;
        event_begin(e, event_id("SELF_HELP_BOOK"), false);
        check("selfhelp_no_targets_single_option", event_option_count(e), 1);
        event_choose(e, 0);
        check("selfhelp_skip_finished", e.screen != RunScreen::EVENT, 1);
    }
    {
        RunContext r;
        r.init(930232, 0);
        check("woodcarvings_allowed",
              event_is_allowed(r, event_id("WOOD_CARVINGS")), 1);
        event_begin(r, event_id("WOOD_CARVINGS"), false);
        check("woodcarvings_options", event_option_count(r), 3);
        check("woodcarvings_snake_available", event_option_available(r, 1), 1);
        const int deck = r.deckCount;
        event_choose(r, 0);
        check("woodcarvings_bird_selection", r.eventCardSelection, 4);
        int basic = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { basic = i; break; }
        event_select_card(r, basic);
        check("woodcarvings_bird_deck_size", r.deckCount, deck);
        check("woodcarvings_bird_card", static_cast<int>(r.deck[deck - 1].id),
              static_cast<int>(CardId::PECK));

        RunContext t;
        t.init(930233, 0);
        event_begin(t, event_id("WOOD_CARVINGS"), false);
        event_choose(t, 2);
        const int tdeck = t.deckCount;
        int tbasic = -1;
        for (int i = 0; i < t.deckCount; ++i)
            if (event_card_selectable(t, i)) { tbasic = i; break; }
        event_select_card(t, tbasic);
        check("woodcarvings_torus_card",
              static_cast<int>(t.deck[tdeck - 1].id),
              static_cast<int>(CardId::TORIC_TOUGHNESS));

        RunContext s;
        s.init(930234, 0);
        event_begin(s, event_id("WOOD_CARVINGS"), false);
        event_choose(s, 1);
        check("woodcarvings_snake_selection", s.eventCardSelection, 10);
        int target = -1;
        for (int i = 0; i < s.deckCount; ++i)
            if (event_card_selectable(s, i)) { target = i; break; }
        event_select_card(s, target);
        check("woodcarvings_snake_applied",
              static_cast<int>(s.deck[target].enchantment),
              static_cast<int>(EnchantmentId::SLITHER));
        check("woodcarvings_snake_finished", s.screen != RunScreen::EVENT, 1);
    }

    // ------------------------------ PerfectFit / SoulsPower / Corrupted
    {
        Card strike = Card{};
        strike.id = CardId::STRIKE_IRONCLAD;
        strike.uid = 1;
        Card skill = Card{};
        skill.id = CardId::DEFEND_IRONCLAD;
        skill.uid = 2;
        check("perfectfit_attack_allowed",
              card_can_enchant(strike, EnchantmentId::PERFECT_FIT), 1);
        check("corrupted_attack_allowed",
              card_can_enchant(strike, EnchantmentId::CORRUPTED), 1);
        check("corrupted_skill_rejected",
              card_can_enchant(skill, EnchantmentId::CORRUPTED), 0);

        // Find an exhaustible playable card for SoulsPower.
        Card exhaustCard{};
        bool foundExhaust = false;
        for (int id = 1; id < static_cast<int>(CardId::COUNT) && !foundExhaust; ++id) {
            Card c{};
            c.id = static_cast<CardId>(id);
            if (card_has(c, CF_EXHAUST) && card_is_playable(c) &&
                card_def(c.id).type != CardType::CURSE &&
                card_def(c.id).type != CardType::STATUS) {
                exhaustCard = c;
                foundExhaust = true;
            }
        }
        check("soulspower_exhaust_target_found", foundExhaust, 1);
        check("soulspower_exhaust_allowed",
              card_can_enchant(exhaustCard, EnchantmentId::SOULS_POWER), 1);
        check("soulspower_strike_rejected",
              card_can_enchant(strike, EnchantmentId::SOULS_POWER), 0);
        check("soulspower_removes_keyword",
              card_has(exhaustCard, CF_EXHAUST), 1);
        card_apply_enchantment(exhaustCard, EnchantmentId::SOULS_POWER, 1);
        check("soulspower_keyword_gone", card_has(exhaustCard, CF_EXHAUST), 0);
    }
    {
        RunContext r;
        r.init(930240, 0);
        check("fieldholes_allowed",
              event_is_allowed(r, event_id("FIELD_OF_MAN_SIZED_HOLES")), 1);
        event_begin(r, event_id("FIELD_OF_MAN_SIZED_HOLES"), false);
        check("fieldholes_options", event_option_count(r), 2);
        event_choose(r, 1);
        check("fieldholes_perfectfit_selection", r.eventCardSelection, 11);
        int idx = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { idx = i; break; }
        event_select_card(r, idx);
        check("fieldholes_perfectfit_applied",
              static_cast<int>(r.deck[idx].enchantment),
              static_cast<int>(EnchantmentId::PERFECT_FIT));

        RunContext k;
        k.init(930241, 0);
        event_begin(k, event_id("FIELD_OF_MAN_SIZED_HOLES"), false);
        const int deck = k.deckCount;
        event_choose(k, 0);
        check("fieldholes_resist_selection", k.eventCardSelection, 6);
        check("fieldholes_resist_count", k.eventData[1], 2);
        int a = -1;
        for (int i = 0; i < k.deckCount; ++i)
            if (event_card_selectable(k, i)) { a = i; break; }
        event_select_card(k, a);
        check("fieldholes_resist_still_open", k.eventCardSelection, 6);
        int b = -1;
        for (int i = 0; i < k.deckCount; ++i)
            if (event_card_selectable(k, i)) { b = i; break; }
        event_select_card(k, b);
        check("fieldholes_resist_deck_net", k.deckCount, deck - 1);
        check("fieldholes_normality",
              static_cast<int>(k.deck[k.deckCount - 1].id),
              static_cast<int>(CardId::NORMALITY));
        check("fieldholes_finished", k.screen != RunScreen::EVENT, 1);
    }
    {
        RunContext r;
        r.init(930242, 0);
        r.add_card_to_deck(r.make_run_card(CardId::OFFERING, false));
        r.add_card_to_deck(r.make_run_card(CardId::OFFERING, false));
        check("grave_allowed_with_exhaust",
              event_is_allowed(r, event_id("GRAVE_OF_THE_FORGOTTEN")), 1);
        event_begin(r, event_id("GRAVE_OF_THE_FORGOTTEN"), false);
        check("grave_confront_available", event_option_available(r, 0), 1);
        event_choose(r, 0);
        check("grave_decay_added",
              static_cast<int>(r.deck[r.deckCount - 1].id),
              static_cast<int>(CardId::DECAY));
        check("grave_souls_selection", r.eventCardSelection, 11);
        int idx = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { idx = i; break; }
        event_select_card(r, idx);
        int chosen = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (r.deck[i].enchantment == EnchantmentId::SOULS_POWER) chosen = i;
        check("grave_souls_applied", chosen >= 0, 1);
        check("grave_souls_card",
              static_cast<int>(r.deck[chosen].id),
              static_cast<int>(CardId::OFFERING));
        check("grave_souls_no_exhaust", card_has(r.deck[chosen], CF_EXHAUST), 0);

        RunContext a;
        a.init(930243, 0);
        a.add_card_to_deck(a.make_run_card(CardId::OFFERING, false));
        event_begin(a, event_id("GRAVE_OF_THE_FORGOTTEN"), false);
        event_choose(a, 1);
        bool hasSoul = false;
        for (int i = 0; i < a.relicCount; ++i)
            hasSoul |= static_cast<RelicId>(a.relics[i]) == RelicId::FORGOTTEN_SOUL;
        check("grave_accept_relic", hasSoul, 1);
    }
    {
        RunContext r;
        r.init(930244, 0);
        r.act = 0;
        check("symbiote_requires_act2",
              event_is_allowed(r, event_id("SYMBIOTE")), 0);
        r.act = 1;
        check("symbiote_allowed_act2",
              event_is_allowed(r, event_id("SYMBIOTE")), 1);
        event_begin(r, event_id("SYMBIOTE"), false);
        check("symbiote_options", event_option_count(r), 2);
        check("symbiote_approach_available", event_option_available(r, 0), 1);
        event_choose(r, 0);
        check("symbiote_corrupted_selection", r.eventCardSelection, 11);
        int idx = -1;
        for (int i = 0; i < r.deckCount; ++i)
            if (event_card_selectable(r, i)) { idx = i; break; }
        event_select_card(r, idx);
        check("symbiote_corrupted_applied",
              static_cast<int>(r.deck[idx].enchantment),
              static_cast<int>(EnchantmentId::CORRUPTED));

        RunContext k;
        k.init(930245, 0);
        k.act = 1;
        event_begin(k, event_id("SYMBIOTE"), false);
        const int deck = k.deckCount;
        event_choose(k, 1);
        check("symbiote_transform_selection", k.eventCardSelection, 4);
        check("symbiote_transform_count", k.eventData[1], 2);
        int x = -1;
        for (int i = 0; i < k.deckCount; ++i)
            if (event_card_selectable(k, i)) { x = i; break; }
        event_select_card(k, x);
        int y = -1;
        for (int i = 0; i < k.deckCount; ++i)
            if (event_card_selectable(k, i)) { y = i; break; }
        event_select_card(k, y);
        check("symbiote_transform_deck_size", k.deckCount, deck);
        check("symbiote_transform_finished", k.screen != RunScreen::EVENT, 1);
    }

    // ------------------------------------------------- batch 11: Pael/Tanx
    // Goopy (:132364): base CanEnchant plus the Defend tag; OnEnchant adds
    // Exhaust; EnchantBlockAdditive is Amount - 1; AfterCardPlayed grows the
    // play copy and its deck version.
    {
        check("goopy_accepts_defend",
              card_can_enchant(make_card(CardId::DEFEND_IRONCLAD, false, 1), EnchantmentId::GOOPY), 1);
        check("goopy_rejects_attack",
              card_can_enchant(make_card(CardId::STRIKE_IRONCLAD, false, 1), EnchantmentId::GOOPY), 0);
        Card goopy = make_card(CardId::DEFEND_IRONCLAD, false, 1);
        goopy.enchantment = EnchantmentId::GOOPY;
        check("goopy_adds_exhaust", card_has(goopy, CF_EXHAUST), 1);
        check("plain_defend_has_no_exhaust",
              card_has(make_card(CardId::DEFEND_IRONCLAD, false, 1), CF_EXHAUST), 0);
    }
    {
        RunContext r;
        r.init(940100, 0);
        r.deckCount = 2;
        r.deck[0] = r.make_run_card(CardId::DEFEND_IRONCLAD, false);
        r.deck[1] = r.make_run_card(CardId::DEFEND_IRONCLAD, false);
        card_apply_enchantment(r.deck[0], EnchantmentId::GOOPY, 1);
        const std::uint16_t uid = r.deck[0].uid;
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        r.battle.handCount = r.battle.drawCount = r.battle.discardCount = r.battle.exhaustCount = 0;
        r.battle.hand[r.battle.handCount++] = r.deck[0];
        r.battle.player.energy = 10;
        Action play_defend;
        play_defend.type = ActionType::PLAY_CARD;
        play_defend.hand = 0;
        play_defend.target = 0;
        check("goopy_play_block",
              r.step_combat(play_defend) && r.battle.player.block == 5, 1);
        check("goopy_play_exhausts", r.battle.exhaustCount, 1);
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        int deckAmount = 0;
        for (int i = 0; i < r.deckCount; ++i)
            if (r.deck[i].uid == uid) deckAmount = r.deck[i].enchantmentAmount;
        check("goopy_deck_growth", deckAmount, 2);
    }
    {
        // Instinct: powered attacks deal double damage.
        BattleContext b = audit_base();
        Card strike = make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        strike.enchantment = EnchantmentId::INSTINCT;
        strike.enchantmentAmount = 1;
        b.hand[b.handCount++] = strike;
        const int hp = b.monsters[0].hp;
        play(b, 0);
        check("instinct_damage_doubled", hp - b.monsters[0].hp, 12);
    }
    {
        // TriBoomerang.AfterObtained: enchant three Instinct-eligible deck
        // cards (none other than Attacks).
        RunContext r;
        r.init(940101, 0);
        check("tri_boomerang_obtain", r.add_relic(RelicId::TRI_BOOMERANG), 1);
        check("tri_boomerang_selector", r.cardGrid.kind, 15);
        int picked = 0;
        for (int i = 0; i < r.deckCount && picked < 3; ++i) {
            if (card_def(r.deck[i].id).type != CardType::ATTACK) continue;
            picked += r.step({RunActionType::SELECT_GRID_CARD, i}) ? 1 : 0;
        }
        check("tri_boomerang_picks_three", picked, 3);
        check("tri_boomerang_confirm",
              r.step({RunActionType::CONFIRM_GRID_CARDS, 0}), 1);
        int instinct = 0;
        for (int i = 0; i < r.deckCount; ++i)
            instinct += r.deck[i].enchantment == EnchantmentId::INSTINCT &&
                        r.deck[i].enchantmentAmount == 1;
        check("tri_boomerang_enchantments", instinct, 3);
    }
    {
        // PaelsClaw.AfterObtained: every Goopy-enchantable deck card gains
        // Goopy 1. Pael only offers it with at least three such cards.
        RunContext r;
        r.init(940102, 0);
        r.deckCount = 3;
        r.deck[0] = r.make_run_card(CardId::DEFEND_IRONCLAD, false);
        r.deck[1] = r.make_run_card(CardId::DEFEND_IRONCLAD, false);
        r.deck[2] = r.make_run_card(CardId::STRIKE_IRONCLAD, false);
        check("paels_claw_obtain", r.add_relic(RelicId::PAELS_CLAW), 1);
        check("paels_claw_defends",
              r.deck[0].enchantment == EnchantmentId::GOOPY &&
              r.deck[0].enchantmentAmount == 1 &&
              r.deck[1].enchantment == EnchantmentId::GOOPY &&
              r.deck[1].enchantmentAmount == 1, 1);
        check("paels_claw_skips_attack", r.deck[2].enchantment == EnchantmentId::NONE, 1);
    }

    {
        // WarHammer.AfterCombatVictory: only Elites trigger it; it upgrades
        // exactly four upgradable cards using the Niche stream.
        RunContext r;
        r.init(940103, 0);
        check("war_hammer_obtain", r.add_relic(RelicId::WAR_HAMMER), 1);
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        r.combatIsElite = true;
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        int upgraded = 0;
        for (int i = 0; i < r.deckCount; ++i) upgraded += r.deck[i].upgraded ? 1 : 0;
        check("war_hammer_upgrades_four", upgraded, 4);
        RunContext normal;
        normal.init(940104, 0);
        check("war_hammer_normal_obtain", normal.add_relic(RelicId::WAR_HAMMER), 1);
        normal.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        normal.battle.outcome = Outcome::PLAYER_VICTORY;
        normal.finish_combat();
        upgraded = 0;
        for (int i = 0; i < normal.deckCount; ++i) upgraded += normal.deck[i].upgraded ? 1 : 0;
        check("war_hammer_ignores_normal_combat", upgraded, 0);
    }

    // ------------------------------------------------- batch 12: Neow
    // Neow.GenerateInitialOptions (:125527): curse NextItem over the ten
    // IsAllowedAtNeow options, conflict removals, three ordered NextBool pairs,
    // the IsAllowedAtNeow filter, then UnstableShuffle/take 2/append curse.
    {
        static const RelicId curseOptions[] = {
            RelicId::CURSED_PEARL, RelicId::DOWSING_ROD, RelicId::HEFTY_TABLET,
            RelicId::LARGE_CAPSULE, RelicId::LEAFY_POULTICE, RelicId::NEOWS_BONES,
            RelicId::NEOWS_SACRIFICE, RelicId::PRECARIOUS_SHEARS,
            RelicId::SILKEN_TRESS, RelicId::SILVER_CRUCIBLE};
        static const RelicId positives[] = {
            RelicId::ARCANE_SCROLL, RelicId::BOOMING_CONCH, RelicId::FISHING_ROD,
            RelicId::GOLDEN_PEARL, RelicId::KALEIDOSCOPE, RelicId::LEAD_PAPERWEIGHT,
            RelicId::LOST_COFFER, RelicId::MASSIVE_SCROLL, RelicId::NEOWS_TORMENT,
            RelicId::NEW_LEAF, RelicId::PHIAL_HOLSTER, RelicId::PRECISE_SCISSORS,
            RelicId::SCROLL_BOXES, RelicId::WINGED_BOOTS};
        for (const std::uint64_t seed : {std::uint64_t{1}, std::uint64_t{7},
                                          std::uint64_t{424242}}) {
            RunContext r;
            r.init(seed, 0);
            event_begin(r, event_id("NEOW"), true);
            Rng expect(r.seed, "NEOW");
            RelicId curses[10];
            int cn = 0;
            for (const RelicId id : curseOptions)
                if (neow_relic_allowed(r, id)) curses[cn++] = id;
            const RelicId curse = curses[expect.next_int(0, cn - 1)];
            RelicId list[20];
            int n = 0;
            for (const RelicId id : positives) {
                if (curse == RelicId::CURSED_PEARL && id == RelicId::GOLDEN_PEARL) continue;
                if (curse == RelicId::HEFTY_TABLET && id == RelicId::ARCANE_SCROLL) continue;
                if (curse == RelicId::LEAFY_POULTICE && id == RelicId::NEW_LEAF) continue;
                if (curse == RelicId::PRECARIOUS_SHEARS && id == RelicId::PRECISE_SCISSORS) continue;
                if (curse == RelicId::NEOWS_SACRIFICE &&
                    (id == RelicId::PHIAL_HOLSTER || id == RelicId::LOST_COFFER)) continue;
                list[n++] = id;
            }
            if (curse != RelicId::LARGE_CAPSULE)
                list[n++] = expect.next_bool() ? RelicId::LAVA_ROCK : RelicId::SMALL_CAPSULE;
            list[n++] = expect.next_bool() ? RelicId::NUTRITIOUS_OYSTER
                                           : RelicId::STONE_HUMIDIFIER;
            list[n++] = expect.next_bool() ? RelicId::NEOWS_TALISMAN : RelicId::POMANDER;
            int m = 0;
            for (int i = 0; i < n; ++i)
                if (neow_relic_allowed(r, list[i])) list[m++] = list[i];
            for (int i = m - 1; i > 0; --i) {
                const int j = expect.next_int(0, i);
                const RelicId t = list[i]; list[i] = list[j]; list[j] = t;
            }
            check("neow_option_a", r.eventRelics[0], static_cast<int>(list[0]));
            check("neow_option_b", r.eventRelics[1], static_cast<int>(list[1]));
            check("neow_option_curse", r.eventRelics[2], static_cast<int>(curse));
        }
    }
    {
        // neow_relic_options order and filtering (AllPossibleOptions order).
        RunContext r;
        r.init(1, 0);
        RelicId options[32];
        const int n = neow_relic_options(r, options, 32, true);
        check("neow_options_include_dowsing",
              options[1] == RelicId::DOWSING_ROD, 1);
        check("neow_options_exclude_bones",
              options[5] == RelicId::NEOWS_SACRIFICE, 1);
        int massive = 0;
        for (int i = 0; i < n; ++i) massive += options[i] == RelicId::MASSIVE_SCROLL;
        check("neow_options_exclude_multiplayer", massive, 0);
    }
    {
        RunContext r;
        r.init(940200, 0);
        const int before = r.deckCount;
        check("dowsing_rod_obtain", r.add_relic(RelicId::DOWSING_ROD), 1);
        int dowsing = 0;
        for (int i = 0; i < r.deckCount; ++i) dowsing += r.deck[i].id == CardId::DOWSING;
        check("dowsing_rod_adds_card", dowsing, 1);
        check("dowsing_rod_deck_count", r.deckCount, before + 1);
    }
    {
        RunContext r;
        r.init(940201, 0);
        check("neows_talisman_obtain", r.add_relic(RelicId::NEOWS_TALISMAN), 1);
        int upgradedStrike = 0, upgradedDefend = 0, other = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            if (!r.deck[i].upgraded) continue;
            if (card_def(r.deck[i].id).rarity != Rarity::BASIC) { ++other; continue; }
            if (card_is_strike(r.deck[i])) ++upgradedStrike;
            else if (card_is_defend(r.deck[i])) ++upgradedDefend;
            else ++other;
        }
        check("neows_talisman_strike", upgradedStrike, 1);
        check("neows_talisman_defend", upgradedDefend, 1);
        check("neows_talisman_only_basics", other, 0);
    }
    {
        RunContext r;
        r.init(940202, 0);
        check("neows_sacrifice_obtain", r.add_relic(RelicId::NEOWS_SACRIFICE), 1);
        check("neows_sacrifice_potion", r.potionCount, 1);
        check("neows_sacrifice_ambergris",
              r.potionCount == 1 && r.potions[0] == static_cast<int>(PotionId::AMBERGRIS), 1);
        int guilty = 0;
        for (int i = 0; i < r.deckCount; ++i) guilty += r.deck[i].id == CardId::GUILTY;
        check("neows_sacrifice_guilty", guilty, 1);
    }
    {
        RunContext r;
        r.init(940203, 0);
        const int slots = r.potionSlots;
        check("phial_holster_obtain", r.add_relic(RelicId::PHIAL_HOLSTER), 1);
        check("phial_holster_slot", r.potionSlots, slots + 1);
        check("phial_holster_potions", r.potionCount, 2);
    }
    {
        // HeftyTablet: three Rare candidates, optional choose-one, chosen card
        // plus Injury. CardFactory.CreateForReward uses Uniform odds and
        // NoUpgradeRoll; CordSelectCmd allows skipping.
        RunContext r;
        r.init(940204, 0);
        const int before = r.deckCount;
        check("hefty_tablet_obtain", r.add_relic(RelicId::HEFTY_TABLET), 1);
        check("hefty_tablet_selector", r.cardGrid.kind, 16);
        check("hefty_tablet_candidates", r.cardGrid.count, 3);
        int rare = 0;
        for (int i = 0; i < r.cardGrid.count; ++i)
            rare += card_def(r.cardGrid.cards[i].id).rarity == Rarity::RARE;
        check("hefty_tablet_all_rare", rare, 3);
        const std::uint16_t chosenUid = r.cardGrid.cards[0].uid;
        check("hefty_tablet_select", r.step({RunActionType::SELECT_GRID_CARD, 0}), 1);
        int injury = 0, chosen = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            injury += r.deck[i].id == CardId::INJURY;
            chosen += r.deck[i].uid == chosenUid;
        }
        check("hefty_tablet_adds_two", r.deckCount, before + 2);
        check("hefty_tablet_injury", injury, 1);
        check("hefty_tablet_chosen", chosen, 1);

        RunContext skip;
        skip.init(940205, 0);
        const int skipBefore = skip.deckCount;
        check("hefty_tablet_skip_obtain", skip.add_relic(RelicId::HEFTY_TABLET), 1);
        check("hefty_tablet_skip_confirm",
              skip.step({RunActionType::CONFIRM_GRID_CARDS, 0}), 1);
        injury = 0;
        for (int i = 0; i < skip.deckCount; ++i) injury += skip.deck[i].id == CardId::INJURY;
        check("hefty_tablet_skip_only_injury", skip.deckCount, skipBefore + 1);
        check("hefty_tablet_skip_injury", injury, 1);
    }
    {
        // NeowsBones: two required relic rewards from the Neow option pool and
        // one generatable curse drawn from Rng.Niche.
        RunContext r;
        r.init(940206, 0);
        const int before = r.deckCount;
        check("neows_bones_obtain", r.add_relic(RelicId::NEOWS_BONES), 1);
        check("neows_bones_rewards", r.pendingRelicCount, 2);
        check("neows_bones_required",
              r.pendingRelicRequired[0] && r.pendingRelicRequired[1], 1);
        RelicId options[32];
        const int n = neow_relic_options(r, options, 32, true);
        int valid = 0;
        for (int i = 0; i < r.pendingRelicCount; ++i) {
            const auto id = static_cast<RelicId>(r.pendingRelics[i]);
            for (int j = 0; j < n; ++j) valid += options[j] == id;
        }
        check("neows_bones_options_from_neow", valid, 2);
        int curses = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            const CardId id = r.deck[i].id;
            curses += id == CardId::CLUMSY || id == CardId::DEBT || id == CardId::DECAY ||
                      id == CardId::DOUBT || id == CardId::GUILTY || id == CardId::INJURY ||
                      id == CardId::NORMALITY || id == CardId::REGRET || id == CardId::SHAME ||
                      id == CardId::WRITHE;
        }
        check("neows_bones_curse", r.deckCount, before + 1);
        check("neows_bones_generatable_curse", curses >= 1, 1);
    }
    {
        // Kaleidoscope: two CardRewards of three cards, each from a distinct
        // non-Ironclad character pool (Rng.Niche pool shuffle).
        RunContext r;
        r.init(940207, 0);
        check("kaleidoscope_obtain", r.add_relic(RelicId::KALEIDOSCOPE), 1);
        int pending = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) pending += r.rewardCardPending[i];
        check("kaleidoscope_rewards", pending, 2);
        int sets = 0, distinct = 0, nonIronclad = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
            if (!r.rewardCardPending[i]) continue;
            ++sets;
            bool used[16]{};
            bool ok = r.rewardCardCounts[i] == 3;
            for (int j = 0; j < r.rewardCardCounts[i]; ++j) {
                const CardPool pool = card_def(r.rewardCards[i][j].id).pool;
                ok = ok && pool != CardPool::IRONCLAD && !used[static_cast<int>(pool)];
                used[static_cast<int>(pool)] = true;
            }
            distinct += ok;
            for (int j = 0; j < r.rewardCardCounts[i]; ++j)
                nonIronclad += card_def(r.rewardCards[i][j].id).pool != CardPool::IRONCLAD;
        }
        check("kaleidoscope_two_sets", sets, 2);
        check("kaleidoscope_distinct_pools", distinct, 2);
        check("kaleidoscope_cross_character", nonIronclad, 6);
    }
    {
        // FishingRod: count Monster-room victories; every third upgrades one
        // Niche-selected upgradable card.
        RunContext r;
        r.init(940208, 0);
        check("fishing_rod_obtain", r.add_relic(RelicId::FISHING_ROD), 1);
        int upgrades = 0;
        for (int i = 0; i < r.deckCount; ++i) upgrades += r.deck[i].upgraded ? 1 : 0;
        relics_combat_end(r, true, false);
        relics_combat_end(r, true, false);
        int afterTwo = 0;
        for (int i = 0; i < r.deckCount; ++i) afterTwo += r.deck[i].upgraded ? 1 : 0;
        check("fishing_rod_two_combats", afterTwo, upgrades);
        relics_combat_end(r, true, false);
        int afterThree = 0;
        for (int i = 0; i < r.deckCount; ++i) afterThree += r.deck[i].upgraded ? 1 : 0;
        check("fishing_rod_third_combat", afterThree, upgrades + 1);
        // Native counts every room whose Encounter.RoomType is Monster; all
        // event encounters (DenseVegetation, MysteriousKnight, BattlewornDummy,
        // PunchOff) report Monster, while Elite/Boss rooms do not count.
        int rodSlot = -1;
        for (int i = 0; i < r.relicCount; ++i)
            if (r.relics[i] == static_cast<int>(RelicId::FISHING_ROD)) rodSlot = i;
        check("fishing_rod_slot", rodSlot >= 0, 1);
        relics_combat_end(r, true, true);  // boss room
        check("fishing_rod_boss_ignored", r.relicAux[rodSlot], 3);
        r.combatIsElite = true;
        relics_combat_end(r, true, false);  // elite room
        r.combatIsElite = false;
        check("fishing_rod_elite_ignored", r.relicAux[rodSlot], 3);
        RunContext ev;
        ev.init(940210, 0);
        check("fishing_rod_event_obtain", ev.add_relic(RelicId::FISHING_ROD), 1);
        ev.eventCombat = true;
        int evUpgrades = 0;
        for (int i = 0; i < ev.deckCount; ++i) evUpgrades += ev.deck[i].upgraded ? 1 : 0;
        for (int i = 0; i < 3; ++i) relics_combat_end(ev, true, false);
        int evAfter = 0;
        for (int i = 0; i < ev.deckCount; ++i) evAfter += ev.deck[i].upgraded ? 1 : 0;
        check("fishing_rod_event_monster_counts", evAfter, evUpgrades + 1);
    }
    {
        // WingedBoots: the next row is fully travelable and a non-child edge
        // consumes one of the three uses.
        RunContext r;
        r.init(940209, 0);
        check("winged_boots_obtain", r.add_relic(RelicId::WINGED_BOOTS), 1);
        int freeRowNodes = 0;
        for (int c = 0; c < MAP_WIDTH; ++c) freeRowNodes += r.map.at(r.curRow + 1, c) >= 0;
        int listed = 0;
        const auto moves = r.available_map_nodes();
        for (const int node : moves) {
            for (int c = 0; c < MAP_WIDTH; ++c)
                listed += r.map.at(r.curRow + 1, c) == node;
        }
        check("winged_boots_next_row", listed, freeRowNodes);
        // Find any node whose next row contains a point that is not one of its
        // ordinary children, then take that free edge from that node.
        int fromNode = -1, freeNode = -1;
        for (int node = 0; node < r.map.pointCount && freeNode < 0; ++node) {
            int row = -1, col = -1;
            for (int rr = 0; rr < MAP_MAX_ROWS && row < 0; ++rr)
                for (int cc = 0; cc < MAP_WIDTH; ++cc)
                    if (r.map.at(rr, cc) == node) { row = rr; col = cc; break; }
            if (row < 0) continue;
            for (int c = 0; c < MAP_WIDTH && freeNode < 0; ++c) {
                const int next = r.map.at(row + 1, c);
                if (next < 0) continue;
                bool child = false;
                for (int i = 0; i < r.map.nodes[node].childCount; ++i)
                    child = child || r.map.nodes[node].children[i] == next;
                if (!child) { fromNode = node; freeNode = next; }
            }
        }
        check("winged_boots_free_edge_exists", freeNode >= 0, 1);
        if (fromNode >= 0 && freeNode >= 0) {
            for (int rr = 0; rr < MAP_MAX_ROWS; ++rr)
                for (int cc = 0; cc < MAP_WIDTH; ++cc)
                    if (r.map.at(rr, cc) == fromNode) { r.curRow = rr; r.curCol = cc; }
            // The run opens on the Act Ancient event; travel happens from the
            // map screen after it resolves.
            r.screen = RunScreen::MAP;
            r.eventId = -1;
            check("winged_boots_free_move", r.step({RunActionType::MOVE, freeNode}), 1);
            int uses = 0;
            for (int i = 0; i < r.relicCount; ++i)
                if (r.relics[i] == static_cast<int>(RelicId::WINGED_BOOTS)) uses = r.relicAux[i];
            check("winged_boots_use_counted", uses, 1);
        }
    }
    {
        // Ambergris: heal 50% MaxHp and grant one extra player turn.
        BattleContext b = base();
        b.player.hp = 40;
        b.apply_potion(PotionId::AMBERGRIS, 0);
        check("ambergris_heal", b.player.hp, 40 + b.player.maxHp * 50 / 100);
        check("ambergris_extra_turn", b.ambergrisExtraTurns, 1);
        const int turn = b.turn;
        b.end_player_turn();
        check("ambergris_turn_taken", b.turn, turn + 1);
        check("ambergris_consumed", b.ambergrisExtraTurns, 0);
    }

    // ------------------------------------------------- batch 13: MeatCleaver
    // MeatCleaver.TryModifyRestSiteOptions adds CookRestSiteOption: enabled
    // with >= 2 removable cards; remove exactly 2, then GainMaxHp 5.
    {
        RunContext r;
        r.init(940300, 0);
        check("meat_cleaver_obtain", r.add_relic(RelicId::MEAT_CLEAVER), 1);
        r.screen = RunScreen::REST;
        int cook = 0;
        for (const auto &a : r.legal_actions())
            cook += static_cast<int>(a.type) == static_cast<int>(RunActionType::REST_COOK);
        check("cook_rest_option", cook, 1);
        const int before = r.deckCount;
        const int maxHp = r.maxHp;
        check("cook_begin", r.step({RunActionType::REST_COOK, 0}), 1);
        check("cook_selector", r.cardGrid.kind, 17);
        check("cook_select_first", r.step({RunActionType::SELECT_GRID_CARD, 0}), 1);
        check("cook_select_second", r.step({RunActionType::SELECT_GRID_CARD, 1}), 1);
        check("cook_removes_two", r.deckCount, before - 2);
        check("cook_max_hp", r.maxHp, maxHp + 5);
        check("cook_ends_rest", r.screen == RunScreen::MAP, 1);

        RunContext cancel;
        cancel.init(940301, 0);
        check("cook_cancel_obtain", cancel.add_relic(RelicId::MEAT_CLEAVER), 1);
        cancel.screen = RunScreen::REST;
        check("cook_cancel_begin", cancel.step({RunActionType::REST_COOK, 0}), 1);
        check("cook_cancel", cancel.step({RunActionType::CANCEL_GRID_PREVIEW, 0}), 1);
        check("cook_cancel_grid", cancel.cardGrid.kind, 0);
        check("cook_cancel_deck", cancel.deckCount, before);

        RunContext none;
        none.init(940302, 0);
        none.screen = RunScreen::REST;
        cook = 0;
        for (const auto &a : none.legal_actions())
            cook += static_cast<int>(a.type) == static_cast<int>(RunActionType::REST_COOK);
        check("cook_requires_relic", cook, 0);
    }

    // ------------------------------------------------- batch 14: TinkerTime
    // TinkerTime.GenerateInitialOptions has one option; ChooseCardType and
    // ChooseRiderEffect each offer TakeRandom(2, base.Rng) (UnstableShuffle,
    // then Take). RiderChosen adds a MadScience with the chosen variant.
    {
        RunContext r;
        r.init(940400, 0);
        const int tinker = event_id("TINKER_TIME");
        check("tinker_time_found", tinker >= 0, 1);
        event_begin(r, tinker, false);
        check("tinker_time_begin", r.screen == RunScreen::EVENT && r.eventId == tinker, 1);
        check("tinker_time_page0_options", event_option_count(r), 1);
        check("tinker_time_choose_type", r.step({RunActionType::EVENT_CHOICE, 0}), 1);
        check("tinker_time_page1_options", event_option_count(r), 2);
        const int firstType = r.eventData[0], secondType = r.eventData[1];
        check("tinker_time_types_distinct", firstType != secondType, 1);
        check("tinker_time_types_in_range", firstType >= 0 && firstType <= 2 &&
                                             secondType >= 0 && secondType <= 2, 1);
        check("tinker_time_choose_specific_type", r.step({RunActionType::EVENT_CHOICE, 0}), 1);
        check("tinker_time_page2_options", event_option_count(r), 2);
        const int rider0 = r.eventData[0], rider1 = r.eventData[1];
        const int lo = firstType == 0 ? 1 : firstType == 1 ? 4 : 7;
        check("tinker_time_riders_distinct", rider0 != rider1, 1);
        check("tinker_time_riders_for_type",
              rider0 >= lo && rider0 <= lo + 2 && rider1 >= lo && rider1 <= lo + 2, 1);
        const int deckBefore = r.deckCount;
        check("tinker_time_choose_rider", r.step({RunActionType::EVENT_CHOICE, 0}), 1);
        check("tinker_time_adds_card", r.deckCount, deckBefore + 1);
        const Card &added = r.deck[r.deckCount - 1];
        check("tinker_time_card_id", static_cast<int>(added.id),
              static_cast<int>(CardId::MAD_SCIENCE));
        check("tinker_time_card_type", added.tinkerType, firstType);
        check("tinker_time_card_rider", added.tinkerRider, rider0);
    }
    {
        // MadScience base effects and riders (CardModel.Type/TargetType and
        // OnPlay in the decompile).
        auto mad = [](BattleContext &b, int type, int rider) {
            Card c = make_card(CardId::MAD_SCIENCE, false, b.nextUid++);
            c.tinkerType = static_cast<std::uint8_t>(type);
            c.tinkerRider = static_cast<std::uint8_t>(rider);
            b.hand[b.handCount++] = c;
        };
        {   // Attack + Violence: 12 damage three times, no extra rider.
            BattleContext b = base();
            const int hp0 = b.monsters[0].hp;
            mad(b, 0, 2);
            play(b);
            check("mad_science_violence_damage", hp0 - b.monsters[0].hp, 36);
        }
        {   // Attack + Sapping: 12 damage then 2 Weak / 2 Vulnerable.
            BattleContext b = base();
            const int hp0 = b.monsters[0].hp;
            mad(b, 0, 1);
            play(b);
            check("mad_science_sapping_damage", hp0 - b.monsters[0].hp, 12);
            check("mad_science_sapping_weak", b.monsters[0].weak, 2);
            check("mad_science_sapping_vulnerable", b.monsters[0].vulnerable, 2);
        }
        {   // Attack + Choking: StranglePower 6.
            BattleContext b = base();
            mad(b, 0, 3);
            play(b);
            check("mad_science_choking", b.monster_power(0, PowerId::STRANGLE), 6);
        }
        {   // Skill + Energized: 8 block and +2 energy (net +1 after cost).
            BattleContext b = base();
            mad(b, 1, 4);
            play(b);
            check("mad_science_skill_block", b.player.block, 8);
            check("mad_science_energized_energy", b.player.energy, 21);
        }
        {   // Skill + Wisdom: draw 3.
            BattleContext b = base();
            for (int i = 0; i < 3; ++i)
                b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
            mad(b, 1, 5);
            play(b);
            check("mad_science_wisdom_draw", b.handCount, 3);
        }
        {   // Skill + Chaos: one free card from the character pool in hand.
            BattleContext b = base();
            mad(b, 1, 6);
            play(b);
            check("mad_science_chaos_hand", b.handCount, 1);
            check("mad_science_chaos_free", b.handCount > 0 ? card_cost(b.hand[0]) : -1, 0);
        }
        {   // Power + Expertise: +2 Strength and +2 Dexterity.
            BattleContext b = base();
            mad(b, 2, 7);
            play(b);
            check("mad_science_expertise_strength", b.player_power(PowerId::STRENGTH), 2);
            check("mad_science_expertise_dexterity", b.player_power(PowerId::DEXTERITY), 2);
        }
        {   // Power + Curious: Power cards cost 1 less.
            BattleContext b = base();
            mad(b, 2, 8);
            play(b);
            check("mad_science_curious_power", b.player_power(PowerId::CURIOUS), 1);
            hand(b, CardId::INFLAME);
            b.player.energy = 0;
            int inflame = 0;
            for (const Action &a : b.legal_actions())
                if (a.type == ActionType::PLAY_CARD && b.hand[a.hand].id == CardId::INFLAME)
                    ++inflame;
            check("mad_science_curious_cost", inflame, 1);
        }
        {   // Power + Improvement: gains ImprovementPower for combat end.
            BattleContext b = base();
            mad(b, 2, 9);
            play(b);
            check("mad_science_improvement_power", b.player_power(PowerId::IMPROVEMENT), 1);
        }
        {   // ImprovementPower.AfterCombatEnd upgrades one random upgradable
            // deck card per stack with the CombatCardSelection stream.
            RunContext r;
            r.init(940401, 0);
            int before = 0;
            for (int i = 0; i < r.deckCount; ++i) before += r.deck[i].upgraded ? 1 : 0;
            r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
            r.battle.add_player_power(PowerId::IMPROVEMENT, 2);
            r.battle.outcome = Outcome::PLAYER_VICTORY;
            r.finish_combat();
            int after = 0;
            for (int i = 0; i < r.deckCount; ++i) after += r.deck[i].upgraded ? 1 : 0;
            check("mad_science_improvement_upgrades", after, before + 2);
        }
    }

    // ------------------------------------------------- batch 15: FakeMerchant
    // BeforeEventStarted: UnstableShuffle the nine fake relics with the event
    // Rng, take six, price at round(50 * PlayerRng.Shops.NextFloat(.85, 1.15)).
    {
        const int fake = event_id("FAKE_MERCHANT");
        check("fake_merchant_found", fake >= 0, 1);
        RunContext r;
        r.init(940500, 1);  // act 2
        event_begin(r, fake, false);
        check("fake_merchant_screen", r.screen == RunScreen::EVENT, 1);
        check("fake_merchant_leave_option", event_option_count(r), 1);
        bool distinct = true;
        for (int i = 0; i < RunContext::FAKE_MERCHANT_RELICS; ++i) {
            const int id = r.fakeMerchantRelics[i];
            check("fake_merchant_relic_inventory", id > 0 && id < static_cast<int>(RelicId::COUNT), 1);
            check("fake_merchant_price_range",
                  r.fakeMerchantPrices[i] >= 43 && r.fakeMerchantPrices[i] <= 58, 1);
            for (int j = 0; j < i; ++j) distinct &= id != r.fakeMerchantRelics[j];
        }
        check("fake_merchant_distinct", distinct, 1);
        // Buy one entry: gold drops by its price and the relic is obtained.
        const int buy = 0;
        r.gold = 1000;
        const int relics0 = r.relicCount;
        const int price = r.fakeMerchantPrices[buy];
        const int baseGold = r.gold;
        int listed = 0;
        for (const auto &a : r.legal_actions())
            listed += a.type == RunActionType::BUY_RELIC ? 1 : 0;
        check("fake_merchant_buy_listed", listed, 6);
        check("fake_merchant_buy", r.step({RunActionType::BUY_RELIC, buy}), 1);
        check("fake_merchant_gold_spent", r.gold, baseGold - price);
        check("fake_merchant_relic_gained", r.relicCount, relics0 + 1);
        check("fake_merchant_sold", r.fakeMerchantSold[buy], 1);
        listed = 0;
        bool soldListed = false;
        for (const auto &a : r.legal_actions()) {
            if (a.type != RunActionType::BUY_RELIC) continue;
            ++listed;
            soldListed |= a.index == buy;
        }
        check("fake_merchant_sold_hidden", listed, 5);
        check("fake_merchant_sold_not_buyable", soldListed ? 1 : 0, 0);
        check("fake_merchant_leave", r.step({RunActionType::EVENT_CHOICE, 0}), 1);
        check("fake_merchant_ends_room", r.eventId, -1);
    }
    {
        // FoulPotionThrown: reward list is FakeMerchantsRug then every stocked
        // entry; the encounter keeps normal monster rewards with 300 gold.
        const int fake = event_id("FAKE_MERCHANT");
        RunContext r;
        r.init(940501, 2);
        r.gold = 500;
        r.add_potion(PotionId::FOUL_POTION);
        event_begin(r, fake, false);
        const int bought = 2;
        check("fake_merchant_prebuy", r.step({RunActionType::BUY_RELIC, bought}), 1);
        int slot = -1;
        for (int i = 0; i < r.potionSlots; ++i)
            if (r.potions[i] == static_cast<int>(PotionId::FOUL_POTION)) slot = i;
        check("fake_merchant_foul_potion", slot >= 0, 1);
        check("fake_merchant_throw", r.use_potion_out_of_combat(slot), 1);
        check("fake_merchant_combat_screen", r.screen == RunScreen::COMBAT, 1);
        check("fake_merchant_combat_encounter",
              static_cast<int>(r.battle.encounter),
              static_cast<int>(Encounter::SETUP_FAKE_MERCHANT));
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check("fake_merchant_gold_reward", r.pendingGoldReward, 300);
        check("fake_merchant_extra_relics", r.pendingRelicCount, 6);
        check("fake_merchant_rug_reward",
              r.pendingRelics[0], static_cast<int>(RelicId::FAKE_MERCHANTS_RUG));
        bool includesBought = false;
        for (int i = 0; i < r.pendingRelicCount; ++i)
            includesBought |= r.pendingRelics[i] == r.fakeMerchantRelics[bought];
        check("fake_merchant_bought_not_reward", includesBought ? 1 : 0, 0);
        check("fake_merchant_event_ended", r.eventId, -1);
    }

    // ------------------------------------------------- batch 16: CrystalSphere
    {
        const int crystal = event_id("CRYSTAL_SPHERE");
        check("crystal_sphere_found", crystal >= 0, 1);
        RunContext r;
        r.init(940600, 1);
        r.gold = 200;
        event_begin(r, crystal, false);
        check("crystal_sphere_options", event_option_count(r), 2);
        check("crystal_sphere_cost_range",
              r.eventData[0] >= 51 && r.eventData[0] <= 99, 1);
        const int deck0 = r.deckCount;
        check("crystal_payment_plan", r.step({RunActionType::EVENT_CHOICE, 1}), 1);
        check("crystal_payment_curse", r.deckCount, deck0 + 1);
        check("crystal_payment_curse_id",
              static_cast<int>(r.deck[r.deckCount - 1].id),
              static_cast<int>(CardId::DEBT));
        check("crystal_divinations", r.crystalDivinations, 6);
        check("crystal_minigame_options", event_option_count(r), 0);
        check("crystal_active", event_crystal_active(r) ? 1 : 0, 1);
        // Initial fog: each corner plus its rook-neighbours two steps out.
        int hidden = 0;
        for (int i = 0; i < RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H; ++i)
            hidden += r.crystalHidden[i] ? 1 : 0;
        check("crystal_initial_hidden", hidden, 97);
        check("crystal_items", r.crystalItemCount, 15);
        int placed = 0, smallGold = -1, relicItem = -1;
        for (int i = 0; i < r.crystalItemCount; ++i) {
            placed += r.crystalItems[i].placed ? 1 : 0;
            if (r.crystalItems[i].type == 7 && smallGold < 0) smallGold = i;
            if (r.crystalItems[i].type == 0) relicItem = i;
        }
        check("crystal_all_placed", placed, 15);
        check("crystal_small_gold_present", smallGold >= 0, 1);
        check("crystal_relic_present", relicItem >= 0, 1);
        // One small divination reveals a 1x1 gold item.
        const int cell = r.crystalItems[smallGold].y * RunContext::CRYSTAL_GRID_W +
                         r.crystalItems[smallGold].x;
        check("crystal_small_divine", r.step({RunActionType::CRYSTAL_DIVINE, cell * 2}), 1);
        check("crystal_gold_revealed", r.crystalItems[smallGold].revealed ? 1 : 0, 1);
        check("crystal_divinations_left", r.crystalDivinations, 5);
        // A Big divination clears the 3x3 around the cell.
        int hidden0 = 0;
        for (int i = 0; i < RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H; ++i)
            hidden0 += r.crystalHidden[i] ? 1 : 0;
        const int bx = 5, by = 5;
        int expectedCleared = 0;
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx)
                expectedCleared += r.crystalHidden[(by + dy) * RunContext::CRYSTAL_GRID_W + bx + dx];
        check("crystal_big_divine",
              r.step({RunActionType::CRYSTAL_DIVINE, (by * RunContext::CRYSTAL_GRID_W + bx) * 2 + 1}), 1);
        int hidden1 = 0;
        for (int i = 0; i < RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H; ++i)
            hidden1 += r.crystalHidden[i] ? 1 : 0;
        check("crystal_big_clears_nine", hidden0 - hidden1, expectedCleared);
        // Spend the remaining divinations; the event hands out its rewards.
        while (r.crystalDivinations > 0) {
            const int target = (r.crystalDivinations % 2) ? cell * 2 + 1 : 0;
            check("crystal_spend_divination", r.step({RunActionType::CRYSTAL_DIVINE, target}), 1);
        }
        check("crystal_event_ended", r.eventId, -1);
        check("crystal_gold_reward", r.pendingGoldReward >= 10, 1);
        check("crystal_rewards_screen", r.screen == RunScreen::REWARDS, 1);
    }
    {
        // Reward construction order: relic rarity roll, then potion/card with
        // the event Rng; gold amounts merge into the pending gold reward.
        const int crystal = event_id("CRYSTAL_SPHERE");
        RunContext r;
        r.init(940601, 1);
        r.gold = 200;
        event_begin(r, crystal, false);
        check("crystal_reward_start", r.step({RunActionType::EVENT_CHOICE, 1}), 1);
        int relicItem = -1, cardItem = -1, potionItem = -1, goldItem = -1;
        for (int i = 0; i < r.crystalItemCount; ++i) {
            const int t = r.crystalItems[i].type;
            if (t == 0) relicItem = i;
            else if (t == 3) cardItem = i;
            else if (t == 1) potionItem = i;
            else if (t == 7) goldItem = i;
        }
        check("crystal_reward_items",
              relicItem >= 0 && cardItem >= 0 && potionItem >= 0 && goldItem >= 0, 1);
        r.crystalRevealed[0] = static_cast<std::uint8_t>(relicItem);
        r.crystalRevealed[1] = static_cast<std::uint8_t>(cardItem);
        r.crystalRevealed[2] = static_cast<std::uint8_t>(potionItem);
        r.crystalRevealed[3] = static_cast<std::uint8_t>(goldItem);
        r.crystalRevealedCount = 4;
        r.crystalDivinations = 1;
        check("crystal_reward_finish",
              r.step({RunActionType::CRYSTAL_DIVINE, 0}), 1);
        check("crystal_relic_reward", r.pendingRelicCount, 1);
        check("crystal_relic_identity",
              r.pendingRelics[0] > 0 &&
              r.pendingRelics[0] < static_cast<int>(RelicId::COUNT), 1);
        check("crystal_card_reward", r.pendingCardReward ? 1 : 0, 1);
        check("crystal_card_reward_size", r.rewardCardCounts[0], 3);
        check("crystal_potion_reward", r.pendingPotionCount, 1);
        check("crystal_gold_amount", r.pendingGoldReward, 10);
        check("crystal_reward_screen", r.screen == RunScreen::REWARDS, 1);
    }
    {
        // UncoverFuture charges 50 + 1..49 gold and grants three divinations.
        const int crystal = event_id("CRYSTAL_SPHERE");
        RunContext r;
        r.init(940602, 2);
        r.gold = 200;
        event_begin(r, crystal, false);
        const int cost = r.eventData[0];
        check("crystal_uncover", r.step({RunActionType::EVENT_CHOICE, 0}), 1);
        check("crystal_uncover_gold", r.gold, 200 - cost);
        check("crystal_uncover_divinations", r.crystalDivinations, 3);
    }

    // ------------------------------------------------- batch 17: encounter plan
    {
        // ActModel.GenerateRooms runs on Rng.UpFront: events are shuffled
        // first, then the weak/regular/elite encounter bags, then Boss =
        // rng.NextItem(AllBossEncounters) and the Ancient. MonsterAi is only
        // the native monster-intent stream and must not select encounters.
        RunContext r;
        r.init(20261104, 0);
        const int upBefore = static_cast<int>(r.runRng[RNG_UP_FRONT].counter);
        const int aiBefore = static_cast<int>(r.runRng[RNG_MONSTER_AI].counter);
        r.roll_act_rooms();
        check("encounter_plan_uses_upfront",
              static_cast<int>(r.runRng[RNG_UP_FRONT].counter) > upBefore, 1);
        check("encounter_plan_ignores_monster_ai",
              static_cast<int>(r.runRng[RNG_MONSTER_AI].counter), aiBefore);
        // NumberOfWeakEncounters(Overgrowth)=3 and BaseNumberOfRooms=15; the
        // elite bag is always filled 15 deep and RoomSet.NextNormalEncounter
        // wraps by normalEncountersVisited % Count.
        check("normal_bag_rooms", r.normalBagN, r.map.rooms);
        check("elite_bag_depth", r.eliteBagN, 15);
        check("normal_bag_first_is_weak",
              std::strstr(encounter_def(r.normalBag[0]).key, "WEAK") != nullptr, 1);
        // A room entry with no concrete pull is a generator invariant failure,
        // not an invitation to draw a random encounter off MonsterAi.
        bool threw = false;
        try {
            r.begin_combat(Encounter::INVALID);
        } catch (const std::invalid_argument &) {
            threw = true;
        }
        check("begin_combat_rejects_invalid", threw ? 1 : 0, 1);
    }

    std::cout << "SUMMARY checks=" << checks << " failures=" << failures << "\n";
    return failures == 0 ? 0 : 1;
}
