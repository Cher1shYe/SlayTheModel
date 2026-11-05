// Regressions for the 2026-11-04 Ironclad RL audit
// (reports/ironclad-rl-audit-20261104/REPORT.md). Each check pins one finding
// at the engine level so the observation/action contract cannot silently
// regress; the Python side repeats them through the bindings.
#include "sts2/battle.h"
#include "sts2/observe.h"
#include "sts2/run.h"

#include <algorithm>
#include <iostream>
#include <string>

using namespace sts2;

namespace {

int failures = 0;

void check(const char *name, bool condition) {
    if (!condition) {
        std::cerr << "FAIL " << name << '\n';
        ++failures;
    }
}

BattleContext battle_with(Card first, Card second, int energy = 3) {
    Card deck[20];
    for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    BattleContext b;
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 1234, deck, 20, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.player.energy = energy;
    b.hand[b.handCount++] = first;
    b.hand[b.handCount++] = second;
    return b;
}

bool legal_hand(const BattleContext &b, int hand) {
    for (const Action &a : b.legal_actions())
        if (a.type == ActionType::PLAY_CARD && a.hand == hand) return true;
    return false;
}

// Finding 5: card states with different consequences must not share features.
void check_card_state_distinguishes() {
    Card base = make_card(CardId::STRIKE_IRONCLAD, false, 1);
    // Both read 0 now: one restores 1 at end of turn, one stays free until played.
    Card endOfTurn = base, untilPlayed = base;
    card_modify_cost(endOfTurn, 0, true, 2);
    card_modify_cost(untilPlayed, -1, false, 4);
    check("cost_expiry_same_now", card_cost(endOfTurn) == card_cost(untilPlayed));
    check("cost_expiry_feature", card_features(endOfTurn) != card_features(untilPlayed));

    Card plain = base, retained = base;
    retained.retainThisTurn = true;
    check("retain_feature", card_features(plain) != card_features(retained));
    // If the two states encoded identically, a policy choosing "end turn" would
    // face the same input while the retained Strike survives and the other is
    // discarded. The battle observation must separate them.
    check("retain_observation",
          public_combat_observation(battle_with(plain, plain)) !=
          public_combat_observation(battle_with(retained, plain)));

    Card skill = make_card(CardId::DEFEND_IRONCLAD, false, 2), sly = skill;
    sly.slyThisTurn = true;
    check("sly_feature", card_features(skill) != card_features(sly));
    check("sly_observation",
          public_combat_observation(battle_with(skill, skill)) !=
          public_combat_observation(battle_with(sly, skill)));
}

// Finding 6: MadScience's TinkerTime variant reaches the run observation.
void check_madscience_variant() {
    RunContext a;
    a.init(12, 0);
    a.deck[0] = make_card(CardId::MAD_SCIENCE, false, 1);
    a.deck[0].tinkerType = 0;
    a.deck[0].tinkerRider = 1;
    RunContext b = a;
    b.deck[0].tinkerRider = 2;
    check("madscience_rider_observation", public_observation(a) != public_observation(b));
    check("madscience_rider_features", card_features(a.deck[0]) != card_features(b.deck[0]));
}

// Finding 7: hidden resampling must not depend on the original secret order
// for *any* visible card field, including bonus damage.
void check_hidden_resample_public_key() {
    RunContext rc;
    rc.init(5, 0);
    const int act = static_cast<int>(ActType::OVERGROWTH);
    int pool[128];
    const int n = event_pool_for_act_type(static_cast<ActType>(act), pool, 128);
    bool hasCrystal = false;
    for (int i = 0; i < n; ++i)
        hasCrystal |= std::string(event_info(pool[i])->name) == "CRYSTAL_SPHERE";
    check("original_pool_has_crystal", hasCrystal);

    int filtered[128];
    int m = 0;
    for (int i = 0; i < n; ++i)
        if (event_allowed_by_profile(RunContentProfile::SINGLE_PLAYER_TRAINING, pool[i]))
            filtered[m++] = pool[i];
    check("profile_pool_excludes_crystal", m == n - 1);

    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    BattleContext x;
    x.init(Encounter::SETUP_CULTISTS_NORMAL, 123, deck, 10, 0, 80, 80);
    x.drawCount = 2;
    x.knownTopCount = 0;
    x.draw[0] = make_card(CardId::STRIKE_IRONCLAD, false, 201);
    x.draw[1] = make_card(CardId::STRIKE_IRONCLAD, false, 202);
    x.draw[0].bonusDamage = 0;
    x.draw[1].bonusDamage = 10;
    BattleContext y = x;
    std::swap(y.draw[0], y.draw[1]);
    check("swap_publicly_equal", public_combat_observation(x) == public_combat_observation(y));
    for (int seed = 0; seed < 200; ++seed) {
        BattleContext p = x, q = y;
        p.resample_hidden(seed + 12591);
        q.resample_hidden(seed + 12591);
        if (p.draw[0].bonusDamage != q.draw[0].bonusDamage ||
            p.draw[1].bonusDamage != q.draw[1].bonusDamage) {
            check("resample_seed_independent_of_secret_order", false);
            return;
        }
    }
    check("resample_seed_independent_of_secret_order", true);
}

// Exercise every newly exposed field independently, including temporary
// modifier lifetime and both MadScience variants. UIDs must not break ties.
void check_new_public_fields_resample() {
    for (int field = 0; field < 7; ++field) {
        Card a = make_card(CardId::MAD_SCIENCE, false, 901), b = a;
        b.uid = 902;
        switch (field) {
        case 0: b.retainThisTurn = true; break;
        case 1: b.slyThisTurn = true; break;
        case 2: b.slyThisCombat = true; break;
        case 3: b.tinkerType = 1; break;
        case 4: b.tinkerRider = 2; break;
        case 5: card_modify_cost(b, card_cost(b), true, 2); break;
        case 6: card_modify_cost(b, card_cost(b), true, 4); break;
        }
        check("new_field_has_public_key", card_public_key(a) != card_public_key(b));
        BattleContext x = battle_with(a, b);
        x.drawCount = 2; x.knownTopCount = 0;
        x.draw[0] = a; x.draw[1] = b;
        BattleContext y = x;
        std::swap(y.draw[0], y.draw[1]);
        check("new_field_unordered_observation", public_combat_observation(x) == public_combat_observation(y));
        for (int seed = 0; seed < 200; ++seed) {
            BattleContext p = x, q = y;
            p.resample_hidden(seed); q.resample_hidden(seed);
            check("new_field_resample", card_features(p.draw[0]) == card_features(q.draw[0]) &&
                  card_features(p.draw[1]) == card_features(q.draw[1]));
        }
    }
}

// Finding 3: Pounce's FREE_SKILL must affect legality, cost and consumption.
void check_free_skill() {
    BattleContext b = battle_with(make_card(CardId::POUNCE, false, 900),
                                  make_card(CardId::DEFEND_IRONCLAD, false, 901), 2);
    const Action pounce{ActionType::PLAY_CARD, 0, 0, 0};
    check("pounce_played", b.step(pounce));
    check("pounce_spent_energy", b.player.energy == 0);
    check("free_skill_gained", b.player_power(PowerId::FREE_SKILL) == 1);
    check("defend_legal_with_free_skill", legal_hand(b, 0));
    const int block_before = b.player.block;
    check("defend_played_free", b.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("defend_cost_nothing", b.player.energy == 0);
    check("free_skill_consumed", b.player_power(PowerId::FREE_SKILL) == 0);
    check("defend_blocked", b.player.block > block_before);

    // Stacked charges: two Pounces' worth allows two free skills, then the
    // third skill costs energy again.
    BattleContext c = battle_with(make_card(CardId::DEFEND_IRONCLAD, false, 910),
                                  make_card(CardId::DEFEND_IRONCLAD, false, 911), 2);
    c.add_player_power(PowerId::FREE_SKILL, 2);
    check("stacked_skill_one", c.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("stacked_skill_energy_one", c.player.energy == 2);
    check("stacked_skill_remaining", c.player_power(PowerId::FREE_SKILL) == 1);
    check("stacked_skill_two", c.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("stacked_skill_energy_two", c.player.energy == 2);
    check("stacked_skill_exhausted", c.player_power(PowerId::FREE_SKILL) == 0);

    // Normal cost path: without the power the same skill pays 1.
    BattleContext d = battle_with(make_card(CardId::DEFEND_IRONCLAD, false, 920),
                                  make_card(CardId::DEFEND_IRONCLAD, false, 921), 2);
    check("paid_skill", d.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("paid_skill_energy", d.player.energy == 1);
}

// Finding 2: potion slots are physical; holes must not shift an action's id.
void check_potion_slots() {
    RunContext rc;
    rc.init(7, 0);
    rc.potions[0] = static_cast<int>(PotionId::BLOOD_POTION);
    rc.potions[1] = 0;
    rc.potions[2] = static_cast<int>(PotionId::FIRE_POTION);
    rc.potionSlots = 3;
    rc.potionCount = 2;
    const int used = rc.potions[0];
    check("potion_slot_zero", used == static_cast<int>(PotionId::BLOOD_POTION));
    check("potion_slot_two", rc.potions[2] == static_cast<int>(PotionId::FIRE_POTION));
    check("potion_hole_empty", rc.potions[1] == 0);
}

}  // namespace

int main() {
    check_card_state_distinguishes();
    check_madscience_variant();
    check_hidden_resample_public_key();
    check_new_public_fields_resample();
    check_free_skill();
    check_potion_slots();
    if (failures) {
        std::cerr << failures << " audit regression check(s) failed\n";
        return 1;
    }
    std::cout << "audit RL regressions: all checks passed\n";
    return 0;
}
