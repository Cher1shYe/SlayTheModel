#include "sts2/defect.h"
#include "sts2/battle.h"
#include "sts2/relics.h"

namespace sts2 {
namespace {
void generated(BattleContext &bc, CardId id, bool upgraded = false, bool hand = false) {
    Card c = make_card(id, upgraded, bc.require_card_uid());
    if (hand) bc.add_card_to_hand(c); else bc.add_card_to_discard(c);
    bc.notify_card_generated(c);
}
void channels(BattleContext &bc, OrbId id, int count) {
    for (int i = 0; i < count; ++i) defect_channel(bc, id);
}
int effective_hand_cost(const BattleContext &bc, const Card &c) {
    if ((card_is_skill(c) && bc.player_power(PowerId::CORRUPTION) > 0) ||
        (card_is_attack(c) && bc.player_power(PowerId::FREE_ATTACK) > 0) ||
        (card_is_skill(c) && bc.player_power(PowerId::FREE_SKILL) > 0) ||
        (card_is_power(c) && bc.player_power(PowerId::FREE_POWER) > 0)) return 0;
    return card_cost(c);
}
void record_genetic_growth(BattleContext &bc, Card &card, int amount) {
    card.bonusBlock += amount;
    // Only physical combat versions of original deck cards have DeckVersion.
    if (std::find(bc.originalDeckUids, bc.originalDeckUids + bc.originalDeckCount, card.uid) ==
        bc.originalDeckUids + bc.originalDeckCount) return;
    auto &s = bc.defect;
    int i = 0; while (i < s.geneticCount && s.geneticUids[i] != card.uid) ++i;
    if (i == s.geneticCount) {
        if (s.geneticCount == 160) throw std::overflow_error("Genetic Algorithm history exceeds storage");
        s.geneticUids[s.geneticCount++] = card.uid;
    }
    s.geneticGrowth[i] += amount;
}
void grow_claws(BattleContext &bc, Card &card, int amount) {
    for (auto pile : {std::pair<Card *, int>{bc.hand, bc.handCount}, {bc.draw, bc.drawCount},
                      {bc.discard, bc.discardCount}, {bc.exhaust, bc.exhaustCount}, {bc.playPile, bc.playCount}})
        for (int i = 0; i < pile.second; ++i)
            if (pile.first[i].id == CardId::CLAW) pile.first[i].bonusDamage += amount;
    card.bonusDamage += amount;
}
void start_flak(BattleContext &bc, ActivePlay &play) {
    auto &state = play.defect;
    state.stage = 1; state.cursor = state.drawnCount = 0;
    // Native AllPiles order is Hand, Draw, Discard, Exhaust, Play; exclude Exhaust.
    for (auto pile : {std::pair<Card *, int>{bc.hand, bc.handCount}, {bc.draw, bc.drawCount},
                      {bc.discard, bc.discardCount}, {bc.playPile, bc.playCount}})
        for (int i = 0; i < pile.second; ++i)
            if (card_def(pile.first[i].id).type == CardType::STATUS) {
                if (state.drawnCount == 160) throw std::overflow_error("Flak Cannon status snapshot exceeds storage");
                state.drawnUids[state.drawnCount++] = pile.first[i].uid;
            }
}
Card *find_any(BattleContext &bc, std::uint16_t uid) {
    if (auto *c = bc.find_in_hand(uid)) return c;
    if (auto *c = bc.find_in_draw(uid)) return c;
    if (auto *c = bc.find_in_discard(uid)) return c;
    for (int i = 0; i < bc.playCount; ++i) if (bc.playPile[i].uid == uid) return &bc.playPile[i];
    return nullptr;
}
}  // namespace

bool defect_resume_effect(BattleContext &bc, ActivePlay &play) {
    auto &state = play.defect;
    if (!state.stage) return true;
    if (bc.pending.op != ChoiceOp::NONE || bc.pendingDrawRemainder > 0) return false;
    switch (play.card.id) {
        case CardId::SCAVENGE:
            bc.add_player_power(PowerId::ENERGY_NEXT_TURN, card_var(play.card, VarId::ENERGY));
            state.stage = 0; return true;
        case CardId::MODDED:
            card_modify_cost(play.card, 1, false, 0);
            state.stage = 0; return true;
        case CardId::OVERCLOCK:
            generated(bc, CardId::BURN); state.stage = 0; return true;
        case CardId::SCRAPE:
            for (int i = 0; i < state.drawnCount; ++i) {
                Card *c = bc.find_in_hand(state.drawnUids[i]);
                if (!c || (effective_hand_cost(bc, *c) == 0 && card_def(c->id).cost >= 0)) continue;
                const Card copy = *c;
                bc.detach_card(copy.uid); bc.move_to_discard(copy);
                // A discard can open a nested Sly play / draw selector.
                if (bc.pending.op != ChoiceOp::NONE) {
                    for (int j = i + 1; j < state.drawnCount; ++j) state.drawnUids[j - i - 1] = state.drawnUids[j];
                    state.drawnCount -= i + 1; return false;
                }
            }
            state.stage = state.drawnCount = 0; return true;
        case CardId::REBOOT:
            if (state.stage == 1) {
                state.stage = 2; bc.draw_cards(card_var(play.card, VarId::CARDS));
                if (bc.pending.op != ChoiceOp::NONE || bc.pendingDrawRemainder) return false;
            }
            state.stage = 0; return true;
        case CardId::FLAK_CANNON:
            while (state.cursor < state.drawnCount) {
                const auto uid = state.drawnUids[state.cursor++];
                Card *c = find_any(bc, uid);
                if (c) {const Card copy = *c; bc.detach_card(uid); bc.move_to_exhaust(copy);}
                if (bc.pending.op != ChoiceOp::NONE || bc.pendingDrawRemainder) return false;
            }
            bc.attack_random_from_card(play.card, card_base_damage(play.card), state.drawnCount);
            state.stage = 0; return true;
        case CardId::UPROAR: state.stage = 0; return true;
        default: state.stage = 0; return true;
    }
}

bool defect_resolve_choice(BattleContext &, std::uint16_t) {
    // Hologram and Scavenge use the engine's ordinary discard-to-hand/exhaust
    // selectors. Their post-selection work is resumed on the owning frame.
    return false;
}

bool defect_effect(BattleContext &bc, Card &card, int target) {
    const double damage = card_base_damage(card);
    auto power = [&](PowerId id, VarId var) {bc.add_player_power(id, card_var(card, var));};
    auto draw = [&] {bc.draw_cards(card_var(card, VarId::CARDS));};
    auto attack = [&](int hits = 1) {return bc.attack_from_card(card, target, damage, hits);};
    auto block = [&] {bc.gain_block(card_block(card), true);};
    switch (card.id) {
        case CardId::ADAPTIVE_STRIKE: {
            attack(); Card copy = card; copy.uid = bc.require_card_uid(); card_modify_cost(copy, 0, true, 0);
            bc.add_card_to_discard(copy); bc.notify_card_generated(copy); return true;
        }
        case CardId::ALL_FOR_ONE: {
            attack(); std::uint16_t ids[MAX_PILE]; int count = 0;
            for (int i = 0; i < bc.discardCount; ++i) {
                const Card &c = bc.discard[i];
                if (card_cost(c) == 0 && card_def(c.id).cost >= 0 &&
                    (card_is_attack(c) || card_is_skill(c) || card_is_power(c))) ids[count++] = c.uid;
            }
            for (int i = 0; i < count; ++i) if (Card *c = bc.find_in_discard(ids[i])) {
                const Card copy = *c; bc.detach_card(copy.uid); bc.add_card_to_hand(copy);
            }
            return true;
        }
        case CardId::BALL_LIGHTNING: attack(); defect_channel(bc, OrbId::LIGHTNING); return true;
        case CardId::BARRAGE: attack(bc.defect.orbCount); return true;
        case CardId::BEAM_CELL: attack(); bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE_POWER)); return true;
        case CardId::BIASED_COGNITION: power(PowerId::FOCUS, VarId::FOCUS_POWER); power(PowerId::BIASED_COGNITION, VarId::BIASED_COGNITION_POWER); return true;
        case CardId::BOOST_AWAY: block(); generated(bc, CardId::DAZED); return true;
        case CardId::BOOT_SEQUENCE: case CardId::DEFEND_DEFECT: case CardId::LEAP: block(); return true;
        case CardId::BUFFER: power(PowerId::BUFFER, VarId::BUFFER_POWER); return true;
        case CardId::BULK_UP:
            defect_add_orb_slots(bc, -card_var(card, VarId::ORB_SLOTS));
            power(PowerId::STRENGTH, VarId::STRENGTH_POWER); power(PowerId::DEXTERITY, VarId::DEXTERITY_POWER); return true;
        case CardId::CAPACITOR: defect_add_orb_slots(bc, card_var(card, VarId::REPEAT)); return true;
        case CardId::CHAOS: for (int i = 0; i < card_var(card, VarId::REPEAT); ++i) defect_channel_random(bc); return true;
        case CardId::CHARGE_BATTERY: block(); power(PowerId::ENERGY_NEXT_TURN, VarId::ENERGY); return true;
        case CardId::CHILL: channels(bc, OrbId::FROST, bc.alive_monster_count()); return true;
        case CardId::CLAW: attack(); grow_claws(bc, card, card_var(card, VarId::INCREASE)); return true;
        case CardId::COLD_SNAP: attack(); defect_channel(bc, OrbId::FROST); return true;
        case CardId::COMPACT:
            block();
            for (int i = 0; i < bc.handCount; ++i) if (card_def(bc.hand[i].id).type == CardType::STATUS) {
                Card replacement = make_card(CardId::FUEL, card.upgraded, bc.require_card_uid());
                bc.hand[i] = replacement; bc.notify_card_generated(replacement);
            }
            return true;
        case CardId::COMPILE_DRIVER: attack(); bc.draw_cards(defect_unique_orbs(bc)); return true;
        case CardId::CONSUMING_SHADOW: channels(bc, OrbId::DARK, card_var(card, VarId::REPEAT)); power(PowerId::CONSUMING_SHADOW, VarId::CONSUMING_SHADOW_POWER); return true;
        case CardId::COOLANT: power(PowerId::COOLANT, VarId::COOLANT_POWER); return true;
        case CardId::COOLHEADED: defect_channel(bc, OrbId::FROST); draw(); return true;
        case CardId::CREATIVE_AI: power(PowerId::CREATIVE_AI, VarId::CREATIVE_AI); return true;
        case CardId::DARKNESS:
            defect_channel(bc, OrbId::DARK);
            for (int i = 0; i < bc.defect.orbCount; ++i) if (bc.defect.orbs[i].id == OrbId::DARK)
                for (int j = 0; j < (card.upgraded ? 2 : 1); ++j) defect_orb_passive(bc, i);
            return true;
        case CardId::DEFRAGMENT: power(PowerId::FOCUS, VarId::FOCUS_POWER); return true;
        case CardId::DOUBLE_ENERGY: bc.player.energy += bc.player.energy; return true;
        case CardId::DUALCAST: defect_evoke(bc, 0, false); defect_evoke(bc, 0, true); return true;
        case CardId::ECHO_FORM: power(PowerId::ECHO_FORM, VarId::ECHO_FORM); return true;
        case CardId::ENERGY_SURGE: bc.player.energy += card_var(card, VarId::ENERGY); return true;
        case CardId::FERAL: power(PowerId::FERAL, VarId::FERAL_POWER); return true;
        case CardId::FIGHT_THROUGH: block(); generated(bc, CardId::WOUND); generated(bc, CardId::WOUND); return true;
        case CardId::FLAK_CANNON: start_flak(bc, bc.activePlay); defect_resume_effect(bc, bc.activePlay); return true;
        case CardId::FOCUSED_STRIKE: attack(); power(PowerId::FOCUSED_STRIKE, VarId::FOCUS_POWER); return true;
        case CardId::FTL: attack(); if (bc.defect.finishedThisTurn < card_var(card, VarId::PLAY_MAX)) draw(); return true;
        case CardId::FUSION: defect_channel(bc, OrbId::PLASMA); return true;
        case CardId::GENETIC_ALGORITHM: block(); record_genetic_growth(bc, card, card_var(card, VarId::INCREASE)); return true;
        case CardId::GLACIER: block(); channels(bc, OrbId::FROST, 2); return true;
        case CardId::GLASSWORK: block(); defect_channel(bc, OrbId::GLASS); return true;
        case CardId::GO_FOR_THE_EYES:
            attack(); if (target >= 0 && target < bc.monsterCount && bc.monsters[target].intentType == 0)
                bc.apply_weak(target, card_var(card, VarId::WEAK_POWER)); return true;
        case CardId::GUNK_UP: attack(card_var(card, VarId::REPEAT)); generated(bc, CardId::SLIMED); return true;
        case CardId::HAILSTORM: power(PowerId::HAILSTORM, VarId::HAILSTORM_POWER); return true;
        case CardId::HELIX_DRILL: attack(std::max(0, bc.defect.energySpentThisTurn - effective_hand_cost(bc, card))); return true;
        case CardId::HIBERNATE: bc.add_player_power(PowerId::HIBERNATE, 1); channels(bc, OrbId::FROST, card_var(card, VarId::REPEAT)); return true;
        case CardId::HOLOGRAM:
            block(); bc.start_choice(ChoiceOp::DISCARD_TO_HAND, ChoicePile::DISCARD, 1, false, card, bc.card_will_exhaust(card)); return true;
        case CardId::HOTFIX: power(PowerId::HOTFIX, VarId::FOCUS_POWER); return true;
        case CardId::HYPERBEAM: bc.attack_all_from_card(card, damage); power(PowerId::HYPERBEAM_FOCUS_DOWN, VarId::FOCUS_POWER); return true;
        case CardId::ICE_LANCE: attack(); channels(bc, OrbId::FROST, card_var(card, VarId::REPEAT)); return true;
        case CardId::IGNITION: defect_channel(bc, OrbId::PLASMA); return true;
        case CardId::IMITATION_LEARNING:
            throw std::logic_error("Imitation Learning requires the native multiplayer-only teammate context");
        case CardId::ITERATION: power(PowerId::ITERATION, VarId::ITERATION_POWER); return true;
        case CardId::LIGHTNING_ROD: block(); power(PowerId::LIGHTNING_ROD, VarId::LIGHTNING_ROD_POWER); return true;
        case CardId::LOOP: power(PowerId::LOOP, VarId::LOOP); return true;
        case CardId::MACHINE_LEARNING: power(PowerId::MACHINE_LEARNING, VarId::CARDS); return true;
        case CardId::METEOR_STRIKE: attack(); channels(bc, OrbId::PLASMA, 3); return true;
        case CardId::MODDED:
            defect_add_orb_slots(bc, card_var(card, VarId::REPEAT)); bc.activePlay.defect.stage = 1;
            draw(); defect_resume_effect(bc, bc.activePlay); return true;
        case CardId::MOMENTUM_STRIKE: attack(); card_modify_cost(card, 0, true, 0); return true;
        case CardId::MULTI_CAST: {
            const int count = bc.xCost + (card.upgraded ? 1 : 0);
            for (int i = 0; i < count; ++i) defect_evoke(bc, 0, i + 1 == count);
            return true;
        }
        case CardId::NULL_CARD: attack(); bc.apply_weak(target, card_var(card, VarId::WEAK_POWER)); defect_channel(bc, OrbId::DARK); return true;
        case CardId::ONE_FOR_ALL: power(PowerId::ONE_FOR_ALL, VarId::ONE_FOR_ALL_POWER); return true;
        case CardId::OVERCLOCK:
            bc.activePlay.defect.stage = 1; draw(); defect_resume_effect(bc, bc.activePlay); return true;
        case CardId::QUADCAST: for (int i = 0, n = card_var(card, VarId::REPEAT); i < n; ++i) defect_evoke(bc, 0, i + 1 == n); return true;
        case CardId::RAINBOW: defect_channel(bc, OrbId::LIGHTNING); defect_channel(bc, OrbId::FROST); defect_channel(bc, OrbId::DARK); return true;
        case CardId::REBOOT: {
            if (bc.drawCount + bc.handCount + bc.discardCount > MAX_PILE) throw std::overflow_error("Reboot exceeds draw storage");
            for (int i = 0; i < bc.handCount; ++i) bc.draw[bc.drawCount++] = bc.hand[i];
            bc.handCount = 0; bc.activePlay.defect.stage = 1;
            bc.shuffle_discard_into_draw(true); defect_resume_effect(bc, bc.activePlay); return true;
        }
        case CardId::REFRACT: attack(2); channels(bc, OrbId::GLASS, card_var(card, VarId::REPEAT)); return true;
        case CardId::ROCKET_PUNCH: attack(); draw(); return true;
        case CardId::SCAVENGE:
            bc.activePlay.defect.stage = 1;
            bc.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, 1, false, card, bc.card_will_exhaust(card));
            defect_resume_effect(bc, bc.activePlay); return true;
        case CardId::SCRAPE:
            attack(); bc.activePlay.defect.stage = 1; bc.activePlay.defect.drawnCount = 0;
            bc.activePlay.defect.drawDepth = bc.defect.drawDepth + 1;
            draw(); defect_resume_effect(bc, bc.activePlay); return true;
        case CardId::SHADOW_SHIELD: block(); defect_channel(bc, OrbId::DARK); return true;
        case CardId::SHATTER: {
            bc.attack_all_from_card(card, damage); const int count = bc.defect.orbCount;
            for (int i = 0; i < count; ++i) {defect_evoke(bc, 0, false); defect_evoke(bc, 0, true);} return true;
        }
        case CardId::SIGNAL_BOOST: power(PowerId::SIGNAL_BOOST, VarId::SIGNAL_BOOST_POWER); return true;
        case CardId::SKIM: draw(); return true;
        case CardId::SMOKESTACK: power(PowerId::SMOKESTACK, VarId::SMOKESTACK_POWER); return true;
        case CardId::SPINNER: if (card.upgraded) defect_channel(bc, OrbId::GLASS); power(PowerId::SPINNER, VarId::SPINNER_POWER); return true;
        case CardId::STORM: power(PowerId::STORM, VarId::STORM_POWER); return true;
        case CardId::STRIKE_DEFECT: attack(); return true;
        case CardId::SUBROUTINE: bc.add_player_power(PowerId::SUBROUTINE, 1); return true;
        case CardId::SUNDER: {
            const bool wasAlive = target >= 0 && target < bc.monsterCount && bc.monsters[target].alive && bc.monsters[target].hp > 0;
            attack(); if (wasAlive && (!bc.monsters[target].alive || bc.monsters[target].hp <= 0)) bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        }
        case CardId::SUPERCRITICAL: bc.player.energy += card_var(card, VarId::ENERGY); return true;
        case CardId::SWEEPING_BEAM: bc.attack_all_from_card(card, damage); draw(); return true;
        case CardId::SYNCHRONIZE:
            bc.add_player_power(PowerId::SYNCHRONIZE, card_var(card, VarId::CALCULATION_BASE) +
                card_var(card, VarId::CALCULATION_EXTRA) * defect_unique_orbs(bc)); return true;
        case CardId::SYNTHESIS: attack(); bc.add_player_power(PowerId::FREE_POWER, 1); return true;
        case CardId::TEMPEST: channels(bc, OrbId::LIGHTNING, bc.xCost + (card.upgraded ? 1 : 0)); return true;
        case CardId::TESLA_COIL:
            attack(); for (int i = 0; i < bc.defect.orbCount; ++i) if (bc.defect.orbs[i].id == OrbId::LIGHTNING)
                for (int j = 0; j < (card.upgraded ? 2 : 1); ++j) defect_orb_passive(bc, i, target);
            return true;
        case CardId::THUNDER: power(PowerId::THUNDER, VarId::THUNDER_POWER); return true;
        case CardId::TRASH_TO_TREASURE: bc.add_player_power(PowerId::TRASH_TO_TREASURE, 1); return true;
        case CardId::TURBO: bc.player.energy += card_var(card, VarId::ENERGY); generated(bc, CardId::VOID); return true;
        case CardId::UPROAR: {
            attack(2); Card candidates[MAX_PILE]; int n = 0;
            for (int i = 0; i < bc.drawCount; ++i) if (card_is_attack(bc.draw[i]) && !card_has(bc.draw[i], CF_UNPLAYABLE)) candidates[n++] = bc.draw[i];
            if (!n) for (int i = 0; i < bc.drawCount; ++i) if (card_is_attack(bc.draw[i])) candidates[n++] = bc.draw[i];
            std::stable_sort(candidates, candidates + n, native_card_less); bc.shuffleRng.shuffle(candidates, n);
            if (n) {bc.activePlay.defect.stage = 1; bc.auto_play_cards(candidates, 1);}
            return true;
        }
        case CardId::VOLTAIC: channels(bc, OrbId::LIGHTNING, bc.defect.lightningChanneled); return true;
        case CardId::WHITE_NOISE: {
            Card c = defect_random_power(bc);
            if (c.id != CardId::INVALID) {card_modify_cost(c, 0, true, 2); bc.add_card_to_hand(c); bc.notify_card_generated(c);} return true;
        }
        case CardId::ZAP: defect_channel(bc, OrbId::LIGHTNING); return true;
        default: return false;
    }
}

}  // namespace sts2
