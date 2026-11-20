// Source-port regressions for the v17 monster mechanics audit (docs/content-audit.md):
// Shrinker Beetle's permanent Shrink, Constrict/Shrink removal on applier death,
// Queen's SetMoveImmediate(Enrage) when Torch Head Amalgam dies, Lagavulin
// Matriarch's last asleep turn (Plating removed before its block), Tangled
// (Entangled +1 attack cost), Ringing/Smog acting only on afflicted cards.
// Expectations come from the v0.111.0 decompilation, not from a DLL trace.
#include "sts2/run.h"
#include "sts2/monsters.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <string>

using namespace sts2;

namespace {
std::unique_ptr<RunContext> fight(Encounter e, const std::string &seed = "V17MONSTERS") {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->begin_combat(e);
    r->battle.player.maxHp = r->battle.player.hp = 900;
    return r;
}
int find(const BattleContext &b, MonsterId id) {
    for (int i = 0; i < b.monsterCount; ++i) if (b.monsters[i].id == id) return i;
    return -1;
}
void end_turn(BattleContext &b) { assert(b.step(Action{ActionType::END_TURN, 0, 0, 0})); }
int hand_index(const BattleContext &b, CardType type) {
    for (int i = 0; i < b.handCount; ++i) if (card_type(b.hand[i]) == type) return i;
    return -1;
}

void shrinker_beetle() {
    auto r = fight(Encounter::SETUP_SHRINKER_BEETLE_WEAK);
    BattleContext &b = r->battle;
    for (int t = 0; t < 4 && b.player_power(PowerId::SHRINK) == 0; ++t) end_turn(b);
    assert(b.player_power(PowerId::SHRINK) == -1);  // ShrinkPower.IsInfinite
    end_turn(b);
    end_turn(b);
    assert(b.player_power(PowerId::SHRINK) == -1);  // never decremented
    b.kill_monster(find(b, MonsterId::SHRINKER_BEETLE));
    assert(b.player_power(PowerId::SHRINK) == 0);   // removed with its applier
}

void constrict_removed_with_strangler() {
    auto r = fight(Encounter::SETUP_SLITHERING_STRANGLER_NORMAL);
    BattleContext &b = r->battle;
    const int strangler = find(b, MonsterId::SLITHERING_STRANGLER);
    assert(strangler >= 0);
    b.add_player_power(PowerId::CONSTRICT, 3);
    b.kill_monster(strangler);
    assert(b.player_power(PowerId::CONSTRICT) == 0);
}

void queen_enrages_when_amalgam_dies() {
    for (bool alreadyActed : {false, true}) {
        auto r = fight(Encounter::SETUP_QUEEN_BOSS);
        BattleContext &b = r->battle;
        const int queen = find(b, MonsterId::QUEEN), amalgam = find(b, MonsterId::TORCH_HEAD_AMALGAM);
        assert(queen >= 0 && amalgam >= 0);
        b.monsters[queen].move = 3;  // BURN_BRIGHT_FOR_ME_MOVE is the pending NextMove
        b.monsters[queen].pendingRoll = alreadyActed;
        b.kill_monster(amalgam);
        assert(b.monsters[queen].move == (alreadyActed ? 3 : 7));  // 7 = ENRAGE_MOVE
    }
}

void lagavulin_last_asleep_turn() {
    auto r = fight(Encounter::SETUP_LAGAVULIN_MATRIARCH_BOSS);
    BattleContext &b = r->battle;
    const int lag = find(b, MonsterId::LAGAVULIN_MATRIARCH);
    assert(lag >= 0 && b.monster_power(lag, PowerId::ASLEEP) == 3 && b.monster_power(lag, PowerId::PLATING) == 12);
    int blocks[3];
    for (int t = 0; t < 3; ++t) { end_turn(b); blocks[t] = b.monsters[lag].block; }
    assert(blocks[0] == 12 && blocks[1] == 11);
    assert(blocks[2] == 0 && b.monster_power(lag, PowerId::PLATING) == 0 && b.monster_power(lag, PowerId::ASLEEP) == 0);
}

void tangled_ringing_smog() {
    auto r = fight(Encounter::SETUP_SLIMES_WEAK);
    BattleContext &b = r->battle;
    const int attack = hand_index(b, CardType::ATTACK), skill = hand_index(b, CardType::SKILL);
    assert(attack >= 0 && skill >= 0);
    const int attackCost = b.energy_cost_in_combat(b.hand[attack]);
    const int skillCost = b.energy_cost_in_combat(b.hand[skill]);
    b.add_player_power(PowerId::TANGLED, 1);
    assert(b.turn_affliction(b.hand[attack]) == 2 && b.turn_affliction(b.hand[skill]) == 0);
    assert(b.energy_cost_in_combat(b.hand[attack]) == attackCost + 1);
    assert(b.energy_cost_in_combat(b.hand[skill]) == skillCost);
    Card bound = b.hand[attack]; bound.bound = true;  // already afflicted: not Entangled
    assert(b.turn_affliction(bound) == 0 && b.energy_cost_in_combat(bound) == attackCost);
    end_turn(b);
    assert(b.player_power(PowerId::TANGLED) == 0);

    // Ringing: after one card play, only Ringing-afflicted cards are blocked.
    auto r2 = fight(Encounter::SETUP_SLIMES_WEAK, "V17RINGING");
    BattleContext &c = r2->battle;
    c.add_player_power(PowerId::RINGING, 1);
    c.hand[c.handCount - 1].bound = true;  // carries another affliction
    const int played = hand_index(c, CardType::SKILL) >= 0 ? hand_index(c, CardType::SKILL) : 0;
    assert(c.step(Action{ActionType::PLAY_CARD, static_cast<std::uint8_t>(played), 0, 0}));
    bool boundPlayable = false, ringingPlayable = false;
    for (const Action &a : c.legal_actions()) {
        if (a.type != ActionType::PLAY_CARD) continue;
        if (c.hand[a.hand].bound) boundPlayable = true; else ringingPlayable = true;
    }
    assert(boundPlayable && !ringingPlayable);

    // Smog: Smoggy locks unafflicted Skills after a Skill, cleared at turn end.
    std::unique_ptr<RunContext> r3;
    for (int k = 0; k < 50; ++k) {
        r3 = fight(Encounter::SETUP_SLIMES_WEAK, "V17SMOG" + std::to_string(k));
        int skills = 0;
        for (int i = 0; i < r3->battle.handCount; ++i) skills += card_type(r3->battle.hand[i]) == CardType::SKILL;
        if (skills >= 2) break;
    }
    BattleContext &d = r3->battle;
    d.add_player_power(PowerId::SMOGGY, 1);
    const int s = hand_index(d, CardType::SKILL);
    assert(s >= 0);
    assert(d.step(Action{ActionType::PLAY_CARD, static_cast<std::uint8_t>(s), 0, 0}));
    for (int i = 0; i < d.handCount; ++i)
        if (card_type(d.hand[i]) == CardType::SKILL) assert(d.turn_affliction(d.hand[i]) == 3);
    end_turn(d);
    assert(!d.skillsLocked);
}
// ThievingHopper._stealPriorities: Draw + Discard cards with a DeckVersion;
// first non-empty tier of (1) non-Imbued Uncommon, (2) non-Imbued Common/Rare/Event,
// (3) non-Imbued Basic/Quest, (4) Ancient or Imbued; all candidates if every tier is
// empty; NextItem on CombatCardGeneration.
int steal_from(std::initializer_list<Card> cards) {
    auto r = fight(Encounter::SETUP_THIEVING_HOPPER_WEAK, "V17HOPPER");
    BattleContext &b = r->battle;
    const int hopper = find(b, MonsterId::THIEVING_HOPPER);
    b.drawCount = b.discardCount = b.handCount = 0;
    b.originalDeckCount = 0;
    bool toDraw = true;
    for (const Card &c : cards) {
        b.originalDeckUids[b.originalDeckCount++] = c.uid;
        if (toDraw) b.draw[b.drawCount++] = c; else b.discard[b.discardCount++] = c;
        toDraw = !toDraw;  // candidates come from both piles
    }
    Monster &m = b.monsters[hopper];
    m.move = 0;  // THIEVERY_MOVE
    m.stunned = false;
    monster_act(b, m);
    assert(b.theftCount == 1);
    return b.theftUids[0];
}

void hopper_steal_priorities() {
    const Card basic = make_card(CardId::STRIKE_IRONCLAD, false, 101);
    const Card common = make_card(CardId::ANGER, false, 102);
    Card imbued = make_card(CardId::BATTLE_TRANCE, false, 103);  // Uncommon Skill
    assert(card_apply_enchantment(imbued, EnchantmentId::IMBUED, 1));
    const Card ancient = make_card(CardId::BREAK, false, 104);
    const Card curse = make_card(CardId::ASCENDERS_BANE, false, 105);
    const Card uncommon = make_card(CardId::BATTLE_TRANCE, false, 106);
    assert(steal_from({basic, common, imbued, ancient, curse, uncommon}) == 106);  // tier 1
    assert(steal_from({basic, common, imbued, ancient, curse}) == 102);  // Imbued Uncommon is not tier 1
    assert(steal_from({basic, imbued, ancient, curse}) == 101);          // tier 3
    for (int k = 0; k < 6; ++k) {
        const int uid = steal_from({imbued, ancient, curse});
        assert(uid == 103 || uid == 104);                                // tier 4, never the curse
    }
    assert(steal_from({curse}) == 105);                                  // every tier empty: all candidates
}
}  // namespace

int main() {
    shrinker_beetle();
    constrict_removed_with_strangler();
    queen_enrages_when_amalgam_dies();
    lagavulin_last_asleep_turn();
    tangled_ringing_smog();
    hopper_steal_priorities();
    std::cout << "native_monster_mechanics_v17 ok\n";
    return 0;
}
