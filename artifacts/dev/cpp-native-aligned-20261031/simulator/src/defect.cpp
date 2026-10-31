#include "sts2/defect.h"
#include "sts2/battle.h"
#include "sts2/relics.h"

namespace sts2 {
namespace {
int focus_value(const BattleContext &bc, int base, OrbId id) {
    int value = std::max(0, base + bc.player_power(PowerId::FOCUS));
    // Powers precede relics in CombatState.IterateHookListeners.
    if (id == OrbId::LIGHTNING && relic_has(bc, RelicId::INFUSED_CORE)) ++value;
    return value;
}
void damage_all(BattleContext &bc, int amount) {
    for (int i = 0; i < bc.monsterCount; ++i)
        if (bc.monsters[i].alive && bc.monsters[i].hp > 0)
            bc.damage_monster(i, amount, true, false);
}
bool temporary_focus(PowerId id) {
    return id == PowerId::FOCUSED_STRIKE || id == PowerId::HOTFIX ||
           id == PowerId::SYNCHRONIZE || id == PowerId::HYPERBEAM_FOCUS_DOWN;
}
bool tracked(PowerId id) {
    switch (id) {
        case PowerId::BIASED_COGNITION: case PowerId::CONSUMING_SHADOW:
        case PowerId::COOLANT: case PowerId::CREATIVE_AI: case PowerId::ECHO_FORM:
        case PowerId::FERAL: case PowerId::FOCUSED_STRIKE: case PowerId::HOTFIX:
        case PowerId::SYNCHRONIZE: case PowerId::HYPERBEAM_FOCUS_DOWN:
        case PowerId::HAILSTORM: case PowerId::HIBERNATE: case PowerId::ITERATION:
        case PowerId::LIGHTNING_ROD: case PowerId::LOOP: case PowerId::MACHINE_LEARNING:
        case PowerId::ONE_FOR_ALL: case PowerId::SIGNAL_BOOST: case PowerId::SMOKESTACK:
        case PowerId::SPINNER: case PowerId::STORM: case PowerId::SUBROUTINE:
        case PowerId::THUNDER: case PowerId::TRASH_TO_TREASURE: case PowerId::FREE_POWER:
            return true;
        default: return false;
    }
}
template <class F> void ordered_powers(BattleContext &bc, F f) {
    // Hook iterates a snapshot, so removal of the current power cannot skip
    // the next power, and powers created within this hook do not join it.
    const auto state = bc.defect;
    for (int i = 0; i < state.powerOrderCount; ++i) {
        const PowerId id = static_cast<PowerId>(state.powerOrder[i]);
        if (bc.player_power(id) != 0) f(id, bc.player_power(id));
    }
}
template <class F> void each_card(BattleContext &bc, F f) {
    for (auto pile : {std::pair<Card *, int>{bc.hand, bc.handCount},
                      {bc.draw, bc.drawCount}, {bc.discard, bc.discardCount},
                      {bc.exhaust, bc.exhaustCount}, {bc.playPile, bc.playCount}})
        for (int i = 0; i < pile.second; ++i) f(pile.first[i]);
    if (bc.activePlay.active) f(bc.activePlay.card);
}
void passive_with_trigger_hooks(BattleContext &bc, int index) {
    const int count = 1 + (index == 0 && relic_has(bc, RelicId::GOLD_PLATED_CABLES) ? 1 : 0);
    for (int i = 0; i < count; ++i) defect_orb_passive(bc, index);
}
}  // namespace

void defect_init(BattleContext &bc) {
    bc.defect = DefectState{};
    bc.defect.orbCapacity = bc.characterPool == CardPool::DEFECT ? 3 : 0;
}

void defect_add_orb_slots(BattleContext &bc, int amount) {
    auto &s = bc.defect;
    s.orbCapacity = std::clamp(s.orbCapacity + amount, 0, MAX_ORBS);
    while (s.orbCount > s.orbCapacity) s.orbs[--s.orbCount] = OrbState{};
}

int defect_unique_orbs(const BattleContext &bc) {
    bool seen[6]{}; int count = 0;
    for (int i = 0; i < bc.defect.orbCount; ++i) {
        const int id = static_cast<int>(bc.defect.orbs[i].id);
        if (id && !seen[id]) {seen[id] = true; ++count;}
    }
    return count;
}

void defect_evoke(BattleContext &bc, int index, bool dequeue) {
    auto &s = bc.defect;
    if (index < 0 || index >= s.orbCount) return;
    const OrbState orb = s.orbs[index];
    if (dequeue) {
        for (int i = index; i + 1 < s.orbCount; ++i) s.orbs[i] = s.orbs[i + 1];
        s.orbs[--s.orbCount] = OrbState{};
    }
    int target = -1;
    switch (orb.id) {
        case OrbId::LIGHTNING:
            target = bc.random_alive_monster();
            if (target >= 0) bc.damage_monster(target, focus_value(bc, 8, orb.id), true, false);
            break;
        case OrbId::FROST: bc.gain_block(focus_value(bc, 5, orb.id), false, false); break;
        case OrbId::DARK:
            for (int i = 0; i < bc.monsterCount; ++i)
                if (bc.monsters[i].alive && bc.monsters[i].hp > 0 &&
                    (target < 0 || bc.monsters[i].hp < bc.monsters[target].hp)) target = i;
            if (target >= 0) bc.damage_monster(target, orb.value, true, false);
            break;
        case OrbId::PLASMA: bc.player.energy += 2; break;
        case OrbId::GLASS: {
            const int value = 2 * focus_value(bc, orb.value, orb.id);
            if (value > 0) damage_all(bc, value);
            break;
        }
        default: break;
    }
    if (orb.id == OrbId::LIGHTNING && target >= 0 && bc.monsters[target].alive &&
        bc.monsters[target].hp > 0 && bc.player_power(PowerId::THUNDER) > 0)
        bc.damage_monster(target, bc.player_power(PowerId::THUNDER), true, false);
}

void defect_orb_passive(BattleContext &bc, int index, int target) {
    auto &s = bc.defect;
    if (index < 0 || index >= s.orbCount) return;
    auto &orb = s.orbs[index];
    switch (orb.id) {
        case OrbId::LIGHTNING:
            if (target < 0) target = bc.random_alive_monster();
            if (target >= 0) bc.damage_monster(target, focus_value(bc, 3, orb.id), true, false);
            break;
        case OrbId::FROST: bc.gain_block(focus_value(bc, 2, orb.id), false, false); break;
        case OrbId::DARK: orb.value += focus_value(bc, 6, orb.id); break;
        case OrbId::PLASMA: ++bc.player.energy; break;
        case OrbId::GLASS: {
            const int value = focus_value(bc, orb.value, orb.id);
            if (value > 0) {orb.value = std::max(0, orb.value - 1); damage_all(bc, value);}
            break;
        }
        default: break;
    }
}

void defect_channel(BattleContext &bc, OrbId id) {
    if (id == OrbId::NONE) return;
    auto &s = bc.defect;
    if (s.orbCapacity == 0 && bc.characterPool != CardPool::DEFECT) defect_add_orb_slots(bc, 1);
    if (s.orbCount >= s.orbCapacity) defect_evoke(bc, 0, true);
    if (s.orbCapacity > 0) {
        s.orbs[s.orbCount++] = {id, id == OrbId::DARK ? 6 : id == OrbId::GLASS ? 4 : 0};
        if (id == OrbId::LIGHTNING) ++s.lightningChanneled;
        for (int i = 0; i < bc.relicCount; ++i)
            if (!bc.relicMelted[i] && bc.relics[i] == static_cast<int>(RelicId::METRONOME)) {
                if (++bc.relicAux[i] == 7) damage_all(bc, 30);
            }
    }
}

void defect_channel_random(BattleContext &bc) {
    static constexpr OrbId choices[] = {OrbId::LIGHTNING, OrbId::FROST, OrbId::DARK, OrbId::PLASMA, OrbId::GLASS};
    defect_channel(bc, choices[bc.orbRng.next_int(0, 4)]);
}

Card defect_random_power(BattleContext &bc) {
    CardId choices[static_cast<int>(CardId::COUNT)]; int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const auto &d = card_def(static_cast<CardId>(i));
        if (d.pool == bc.characterPool && d.type == CardType::POWER && card_native_available(d.id) &&
            !(d.flags & (CF_MULTIPLAYER_ONLY | CF_CANNOT_GENERATE_IN_COMBAT))) choices[n++] = d.id;
    }
    std::stable_sort(choices, choices + n, [](CardId a, CardId b) {
        return card_def(a).nativePoolOrder < card_def(b).nativePoolOrder;
    });
    bc.cardGenerationRng.shuffle(choices, n);
    return n ? make_card(choices[0], false, bc.require_card_uid()) : Card{};
}

void defect_begin_turn(BattleContext &bc) {
    auto &s = bc.defect;
    s.firstSeriesStartedThisTurn = s.finishedThisTurn = s.energySpentThisTurn = 0;
    s.zeroEnergyAttacksStartedThisTurn = s.statusesDrawnThisTurn = 0;
}
void defect_after_energy_reset(BattleContext &bc) {
    ordered_powers(bc, [&](PowerId id, int amount) {
        if (id == PowerId::LIGHTNING_ROD) {defect_channel(bc, OrbId::LIGHTNING); bc.add_player_power(id, -1);}
        if (id == PowerId::SPINNER) for (int i = 0; i < amount; ++i) defect_channel(bc, OrbId::GLASS);
    });
}
void defect_before_hand_draw(BattleContext &bc) {
    for (int i = 0, n = bc.player_power(PowerId::CREATIVE_AI); i < n; ++i) {
        Card c = defect_random_power(bc);
        if (c.id != CardId::INVALID) {bc.add_card_to_hand(c); bc.notify_card_generated(c);}
    }
}
int defect_modify_hand_draw(const BattleContext &bc, int count) {
    return count + bc.player_power(PowerId::MACHINE_LEARNING);
}
void defect_player_turn_start(BattleContext &bc) {
    ordered_powers(bc, [&](PowerId id, int amount) {
        if (id == PowerId::LOOP) for (int i = 0; i < amount && bc.defect.orbCount; ++i) defect_orb_passive(bc, 0);
        if (id == PowerId::HIBERNATE) bc.add_player_power(id, -1);
    });
}
void defect_after_side_turn_start(BattleContext &bc) {
    ordered_powers(bc, [&](PowerId id, int amount) {
        if (id == PowerId::BIASED_COGNITION) bc.add_player_power(PowerId::FOCUS, -amount);
        if (id == PowerId::COOLANT) bc.gain_block(defect_unique_orbs(bc) * amount, false, false);
        if (id == PowerId::FERAL) bc.defect.feralReturnsThisTurn = 0;
    });
    for (int i = 0, count = bc.defect.orbCount; i < count; ++i)
        if (bc.defect.orbs[i].id == OrbId::PLASMA) passive_with_trigger_hooks(bc, i);
}
void defect_before_side_turn_end(BattleContext &bc) {
    if (bc.player_power(PowerId::HAILSTORM) > 0)
        for (int i = 0; i < bc.defect.orbCount; ++i)
            if (bc.defect.orbs[i].id == OrbId::FROST) {damage_all(bc, bc.player_power(PowerId::HAILSTORM)); break;}
    // OrbQueue.BeforeTurnEnd precedes hand end-of-turn and Ethereal effects.
    for (int i = 0, count = bc.defect.orbCount; i < count; ++i)
        if (bc.defect.orbs[i].id != OrbId::PLASMA) passive_with_trigger_hooks(bc, i);
}
void defect_after_side_turn_end(BattleContext &bc) {
    ordered_powers(bc, [&](PowerId id, int amount) {
        if (id == PowerId::CONSUMING_SHADOW)
            for (int i = 0; i < amount && bc.defect.orbCount; ++i) defect_evoke(bc, bc.defect.orbCount - 1);
        if (temporary_focus(id)) bc.add_player_power(id, -amount);
    });
}

bool defect_returns_to_hand(BattleContext &bc, const Card &card, int energySpent, bool dupe) {
    if (!dupe && card_is_attack(card) && energySpent == 0 &&
        bc.defect.feralReturnsThisTurn < bc.player_power(PowerId::FERAL)) {
        ++bc.defect.feralReturnsThisTurn; return true;
    }
    return false;
}
int defect_modify_play_count(BattleContext &bc, const Card &card, int count) {
    if (bc.defect.firstSeriesStartedThisTurn < bc.player_power(PowerId::ECHO_FORM)) ++count;
    if (card_is_power(card) && bc.player_power(PowerId::SIGNAL_BOOST) > 0) {
        ++count; bc.add_player_power(PowerId::SIGNAL_BOOST, -1);
    }
    return count;
}
void defect_play_started(BattleContext &bc, const Card &card, int energySpent, bool firstInSeries) {
    if (firstInSeries) {++bc.defect.firstSeriesStartedThisTurn; bc.defect.energySpentThisTurn += energySpent;}
    if (card_is_attack(card) && energySpent == 0) ++bc.defect.zeroEnergyAttacksStartedThisTurn;
}
void defect_before_card_played(BattleContext &bc, ActivePlay &play) {
    play.defect.storm = card_is_power(play.card) ? bc.player_power(PowerId::STORM) : 0;
    play.defect.subroutine = card_is_power(play.card) ? bc.player_power(PowerId::SUBROUTINE) : 0;
    if (card_is_power(play.card) && bc.player_power(PowerId::FREE_POWER) > 0) bc.add_player_power(PowerId::FREE_POWER, -1);
}
void defect_after_card_played(BattleContext &bc, ActivePlay &play) {
    ordered_powers(bc, [&](PowerId id, int) {
        if (id == PowerId::STORM) for (int i = 0; i < play.defect.storm; ++i) defect_channel(bc, OrbId::LIGHTNING);
        if (id == PowerId::SUBROUTINE) bc.player.energy += play.defect.subroutine;
    });
    play.defect.storm = play.defect.subroutine = 0;
    ++bc.defect.finishedThisTurn;
}
void defect_after_card_drawn(BattleContext &bc, const Card &card) {
    if (bc.activePlay.active && bc.activePlay.card.id == CardId::SCRAPE && bc.activePlay.defect.stage == 1 &&
        bc.defect.drawDepth == bc.activePlay.defect.drawDepth) {
        auto &s = bc.activePlay.defect;
        if (s.drawnCount >= 160) throw std::overflow_error("Scrape draw history exceeds storage");
        s.drawnUids[s.drawnCount++] = card.uid;
    }
    if (card_def(card.id).type == CardType::STATUS && ++bc.defect.statusesDrawnThisTurn == 1)
        bc.draw_cards(bc.player_power(PowerId::ITERATION));
}
void defect_after_card_generated(BattleContext &bc, const Card &card) {
    if (card_def(card.id).type != CardType::STATUS) return;
    ordered_powers(bc, [&](PowerId id, int amount) {
        if (id == PowerId::SMOKESTACK) damage_all(bc, amount);
        if (id == PowerId::TRASH_TO_TREASURE)
            for (int i = 0; i < amount; ++i) defect_channel_random(bc);
    });
    each_card(bc, [](Card &c) {if (c.id == CardId::ROCKET_PUNCH) card_modify_cost(c, -1, false, 4);});
}
int defect_damage_additive(const BattleContext &bc, const Card &card, int energySpent) {
    return card_is_attack(card) && card_def(card.id).cost >= 0 && energySpent == 0 ? bc.player_power(PowerId::ONE_FOR_ALL) : 0;
}
void defect_power_changed(BattleContext &bc, PowerId id, int delta) {
    if (!delta || !tracked(id)) return;
    auto &s = bc.defect;
    int index = -1;
    for (int i = 0; i < s.powerOrderCount; ++i) if (s.powerOrder[i] == static_cast<std::uint16_t>(id)) index = i;
    if (bc.player_power(id) != 0 && index < 0) {
        if (s.powerOrderCount == 32) throw std::overflow_error("Defect power order exceeds storage");
        s.powerOrder[s.powerOrderCount++] = static_cast<std::uint16_t>(id);
        if (id == PowerId::FERAL) s.feralReturnsThisTurn = s.zeroEnergyAttacksStartedThisTurn;
    } else if (bc.player_power(id) == 0 && index >= 0) {
        for (int i = index; i + 1 < s.powerOrderCount; ++i) s.powerOrder[i] = s.powerOrder[i + 1];
        s.powerOrder[--s.powerOrderCount] = 0;
    }
    if (temporary_focus(id)) bc.add_player_power(PowerId::FOCUS, id == PowerId::HYPERBEAM_FOCUS_DOWN ? -delta : delta);
}

}  // namespace sts2
