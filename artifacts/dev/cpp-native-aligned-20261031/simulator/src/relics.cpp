#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include "sts2/monsters.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/relic_persistent.h"
#include "sts2/relic_card_rewards.h"
#include "sts2/potion_slots.h"

namespace sts2 {
#include "sts2/cards_generated.inc"
#include "sts2/monsters_generated.inc"
#include "sts2/relics_generated.inc"

static const char *encounter_key(Encounter enc) {
    const int i = static_cast<int>(enc);
    if (i <= 0 || i >= static_cast<int>(Encounter::COUNT)) return "";
    return ENCOUNTER_DEFS[i].key ? ENCOUNTER_DEFS[i].key : "";
}

const RelicDef &relic_def(RelicId id) {
    const int i = static_cast<int>(id);
    if (i <= 0 || i >= static_cast<int>(RelicId::COUNT)) return RELIC_DEFS[0];
    return RELIC_DEFS[i];
}

const char *relic_name(RelicId id) {
    const RelicDef &d = relic_def(id);
    return d.name ? d.name : "Unknown";
}

bool relic_has(const BattleContext &bc, RelicId id) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (!bc.relicMelted[i] && static_cast<RelicId>(bc.relics[i]) == id) return true;
    }
    return false;
}

bool run_has_relic(const RunContext &rc, RelicId id) {
    for (int i = 0; i < rc.relicCount; ++i) {
        if (!rc.relicMelted[i] && static_cast<RelicId>(rc.relics[i]) == id) return true;
    }
    return false;
}

bool run_owns_relic(const RunContext &rc, RelicId id) {
    for (int i = 0; i < rc.relicCount; ++i)
        if (static_cast<RelicId>(rc.relics[i]) == id) return true;
    return false;
}

bool run_relic_active_at(const RunContext &rc, int index) {
    return index >= 0 && index < rc.relicCount && !rc.relicMelted[index];
}

bool relic_aux_persistent(RelicId id) {
    switch (id) {
        case RelicId::PEN_NIB:
        case RelicId::HAPPY_FLOWER:
        case RelicId::FAKE_HAPPY_FLOWER:
        case RelicId::NUNCHAKU:
        case RelicId::IRON_CLUB:
        case RelicId::JOSS_PAPER:
        case RelicId::TUNING_FORK:
        case RelicId::POLLINOUS_CORE:
        case RelicId::PUMPKIN_CANDLE:
        case RelicId::LIZARD_TAIL:
        case RelicId::SILKEN_TRESS:
        case RelicId::BONE_TEA:
        case RelicId::FAKE_VENERABLE_TEA_SET:
        case RelicId::BYRDPIP:
            return true;
        default:
            return false;
    }
}

int relic_aux(const BattleContext &bc, RelicId id) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (!bc.relicMelted[i] && static_cast<RelicId>(bc.relics[i]) == id) return bc.relicAux[i];
    }
    return 0;
}

void relic_aux_set(BattleContext &bc, RelicId id, int value) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (!bc.relicMelted[i] && static_cast<RelicId>(bc.relics[i]) == id) {
            bc.relicAux[i] = value;
            return;
        }
    }
}

bool relic_implemented(RelicId id) {
    if (id == RelicId::INVALID) return false;
    if (relic_def(id).pool == RelicPool::EVENT) return true;
    switch (id) {
        case RelicId::BURNING_BLOOD:
        case RelicId::CIRCLET:
        case RelicId::AMETHYST_AUBERGINE:
        case RelicId::ANCHOR:
        case RelicId::BAG_OF_PREPARATION:
        case RelicId::BLOOD_VIAL:
        case RelicId::BRONZE_SCALES:
        case RelicId::CENTENNIAL_PUZZLE:
        case RelicId::FESTIVE_POPPER:
        case RelicId::GORGET:
        case RelicId::HAPPY_FLOWER:
        case RelicId::LANTERN:
        case RelicId::MEAL_TICKET:
        case RelicId::ODDLY_SMOOTH_STONE:
        case RelicId::PENDULUM:
        case RelicId::PERMAFROST:
        case RelicId::POTION_BELT:
        case RelicId::RED_SKULL:
        case RelicId::REGAL_PILLOW:
        case RelicId::STRAWBERRY:
        case RelicId::STRIKE_DUMMY:
        case RelicId::TINY_MAILBOX:
        case RelicId::VAJRA:
        case RelicId::VENERABLE_TEA_SET:
        case RelicId::WAR_PAINT:
        case RelicId::WHETSTONE:
        case RelicId::BOOK_OF_FIVE_RINGS:
        case RelicId::AKABEKO:
        case RelicId::BAG_OF_MARBLES:
        case RelicId::BELLOWS:
        case RelicId::BOWLER_HAT:
        case RelicId::CANDELABRA:
        case RelicId::ETERNAL_FEATHER:
        case RelicId::GREMLIN_HORN:
        case RelicId::HORN_CLEAT:
        case RelicId::JOSS_PAPER:
        case RelicId::KUSARIGAMA:
        case RelicId::LETTER_OPENER:
        case RelicId::LUCKY_FYSH:
        case RelicId::MERCURY_HOURGLASS:
        case RelicId::MINIATURE_CANNON:
        case RelicId::NUNCHAKU:
        case RelicId::ORICHALCUM:
        case RelicId::ORNAMENTAL_FAN:
        case RelicId::PANTOGRAPH:
        case RelicId::PAPER_PHROG:
        case RelicId::PARRYING_SHIELD:
        case RelicId::PEAR:
        case RelicId::PEN_NIB:
        case RelicId::PETRIFIED_TOAD:
        case RelicId::PLANISPHERE:
        case RelicId::RED_MASK:
        case RelicId::REPTILE_TRINKET:
        case RelicId::RAZOR_TOOTH:
        case RelicId::SLING_OF_COURAGE:
        case RelicId::RIPPLE_BASIN:
        case RelicId::SELF_FORMING_CLAY:
        case RelicId::SPARKLING_ROUGE:
        case RelicId::STONE_CRACKER:
        case RelicId::TUNING_FORK:
        case RelicId::VAMBRACE:
        case RelicId::TWISTED_FUNNEL:
        case RelicId::ART_OF_WAR:
        case RelicId::BEATING_REMNANT:
        case RelicId::CAPTAINS_WHEEL:
        case RelicId::CHANDELIER:
        case RelicId::CHARONS_ASHES:
        case RelicId::DEMON_TONGUE:
        case RelicId::DRAGON_FRUIT:
        case RelicId::FROZEN_EGG:
        case RelicId::GHOST_SEED:
        case RelicId::GIRYA:
        case RelicId::SHOVEL:
        case RelicId::GAME_PIECE:
        case RelicId::ICE_CREAM:
        case RelicId::INTIMIDATING_HELMET:
        case RelicId::KUNAI:
        case RelicId::LIZARD_TAIL:
        case RelicId::MANGO:
        case RelicId::MEAT_ON_THE_BONE:
        case RelicId::MOLTEN_EGG:
        case RelicId::MUMMIFIED_HAND:
        case RelicId::OLD_COIN:
        case RelicId::POCKETWATCH:
        case RelicId::RAINBOW_RING:
        case RelicId::SHURIKEN:
        case RelicId::STONE_CALENDAR:
        case RelicId::STURDY_CLAMP:
        case RelicId::THE_COURIER:
        case RelicId::TOXIC_EGG:
        case RelicId::TUNGSTEN_ROD:
        case RelicId::UNCEASING_TOP:
        case RelicId::RUINED_HELMET:
        case RelicId::VEXING_PUZZLEBOX:
        case RelicId::WHITE_BEAST_STATUE:
        case RelicId::CLOAK_CLASP:
        case RelicId::BELT_BUCKLE:
        case RelicId::BREAD:
        case RelicId::BRIMSTONE:
        case RelicId::BURNING_STICKS:
        case RelicId::CAULDRON:
        case RelicId::CHEMICAL_X:
        case RelicId::DINGY_RUG:
        case RelicId::LAVA_LAMP:
        case RelicId::LEES_WAFFLE:
        case RelicId::MEMBERSHIP_CARD:
        case RelicId::RINGING_TRIANGLE:
        case RelicId::SCREAMING_FLAGON:
        case RelicId::THE_ABACUS:
        case RelicId::TOOLBOX:
            return true;
        default:
            return false;
    }
}

namespace {

int aux_index(BattleContext &bc, RelicId id) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (!bc.relicMelted[i] && static_cast<RelicId>(bc.relics[i]) == id) return i;
    }
    return -1;
}

void bump(BattleContext &bc, RelicId id, int delta) {
    const int i = aux_index(bc, id);
    if (i >= 0) bc.relicAux[i] += delta;
}

void set_aux(BattleContext &bc, RelicId id, int value) {
    const int i = aux_index(bc, id);
    if (i >= 0) bc.relicAux[i] = value;
}

// JossPaper.DrawIfThresholdMet: draw floor(count / 5), then count %= 5.
void joss_paper_draw(BattleContext &bc, int idx) {
    if (bc.relicAux[idx] < 5) return;
    bc.draw_cards(bc.relicAux[idx] / 5);
    bc.relicAux[idx] %= 5;
}

void damage_all(BattleContext &bc, int amount) {
    for (int i = 0; i < bc.monsterCount; ++i) {
        if (bc.monsters[i].alive) bc.damage_monster(i, amount);
    }
}

void gain_power(BattleContext &bc, PowerId power, int amount) {
    bc.add_player_power(power, amount);
}

void add_to_draw(BattleContext &bc, CardId id, int count) {
    for (int k = 0; k < count && bc.drawCount < MAX_PILE; ++k) {
        const int pos = bc.cardGenerationRng.next_int(0, bc.drawCount);
        for (int i = bc.drawCount; i > pos; --i) bc.draw[i] = bc.draw[i - 1];
        bc.draw[pos] = make_card(id, false, bc.require_card_uid());
        ++bc.drawCount;
    }
}

}  // namespace

void relics_combat_start(BattleContext &bc) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (bc.relicMelted[i]) continue;
        const RelicId id = static_cast<RelicId>(bc.relics[i]);
        if (!relic_aux_persistent(id)) bc.relicAux[i] = 0;
        switch (id) {
            case RelicId::ANCHOR:
                // applied in relics_turn_start after the turn-1 block clear
                break;
            case RelicId::BRONZE_SCALES:
                gain_power(bc, PowerId::THORNS, 3);
                break;
            case RelicId::GORGET:
                gain_power(bc, PowerId::PLATING, 4);
                break;
            case RelicId::VAJRA:
                bc.add_player_power(PowerId::STRENGTH, 1);
                break;
            case RelicId::ODDLY_SMOOTH_STONE:
                bc.player.dexterity += 1;
                break;
            case RelicId::BAG_OF_MARBLES:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) bc.apply_vulnerable(m, 1);
                }
                break;
            case RelicId::RED_MASK:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) bc.apply_weak(m, 1);
                }
                break;
            case RelicId::FESTIVE_POPPER:
                damage_all(bc, 9);
                break;
            case RelicId::AKABEKO:
                gain_power(bc, PowerId::VIGOR, 8);
                break;
            case RelicId::PETRIFIED_TOAD:
                bc.add_potion(PotionId::POTION_SHAPED_ROCK);
                break;
            case RelicId::SLING_OF_COURAGE:
                if (std::strstr(encounter_key(bc.encounter), "ELITE") != nullptr) {
                    bc.add_player_power(PowerId::STRENGTH, 2);
                }
                break;
            case RelicId::BELT_BUCKLE:
                if (bc.potionCount == 0) {
                    bc.player.dexterity += 2;
                    bc.relicAux[i] = 1;
                }
                break;
            case RelicId::RINGING_TRIANGLE:
                gain_power(bc, PowerId::RETAIN_HAND, 1);
                break;
            case RelicId::TWISTED_FUNNEL:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) {
                        bc.monsters[m].power[static_cast<int>(PowerId::POISON)] += 4;
                    }
                }
                break;
            case RelicId::SWORD_OF_JADE:
                bc.add_player_power(PowerId::STRENGTH, 3);
                break;
            case RelicId::PHILOSOPHERS_STONE:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) bc.monsters[m].strength += 1;
                }
                break;
            case RelicId::BLESSED_ANTLER:
                add_to_draw(bc, CardId::DAZED, 3);
                break;
            case RelicId::ROYAL_POISON:
                bc.damage_player(4, true);
                break;
            case RelicId::DELICATE_FROND:
                potion_delicate_frond_before_combat(bc);
                break;
            case RelicId::STONE_CRACKER: {
                // Every combat: StableShuffle eligible draw cards, then take two.
                int candidates[MAX_PILE], count = 0;
                for (int d = 0; d < bc.drawCount; ++d)
                    if (card_upgradable(bc.draw[d])) candidates[count++] = d;
                // Native Draw.Cards stores top first; this engine stores top last.
                std::reverse(candidates, candidates + count);
                native_sort_card_indices(bc.draw, candidates, count);
                bc.cardSelectionRng.shuffle(candidates, count);
                if (bc.player.hp > 0)
                    for (int d = 0; d < std::min(2, count); ++d)
                        bc.upgrade_card(bc.draw[candidates[d]]);
                break;
            }
            default:
                break;
        }
    }
}

int relics_energy_for_turn(BattleContext &bc, int base) {
    int energy = base;
    if (relic_has(bc, RelicId::LANTERN) && bc.turn == 1) energy += 1;
    if (relic_has(bc, RelicId::VERY_HOT_COCOA) && bc.turn == 1) energy += 4;
    if (relic_has(bc, RelicId::CANDELABRA) && bc.turn == 2) energy += 2;
    if (relic_has(bc, RelicId::CHANDELIER) && bc.turn == 3) energy += 3;
    if (relic_has(bc, RelicId::BREAD)) {
        energy += 1;
        if (bc.turn == 1) energy -= 2;
    }
    if (bc.turn == 1) energy += bc.turn1Energy;
    if (relic_has(bc, RelicId::HAPPY_FLOWER)) {
        bump(bc, RelicId::HAPPY_FLOWER, 1);
        if (relic_aux(bc, RelicId::HAPPY_FLOWER) % 3 == 0) energy += 1;
    }
    if (relic_has(bc, RelicId::FAKE_HAPPY_FLOWER)) {
        bump(bc, RelicId::FAKE_HAPPY_FLOWER, 1);
        if (relic_aux(bc, RelicId::FAKE_HAPPY_FLOWER) % 5 == 0) energy += 1;
    }
    if (relic_has(bc, RelicId::ART_OF_WAR) && bc.turn > 1 && bc.attacksPlayedLastTurn == 0) {
        energy += 1;
    }
    if (relic_has(bc, RelicId::ICE_CREAM) && bc.turn > 1) energy += bc.player.energy;
    if (relic_has(bc, RelicId::PAELS_FLESH) && bc.turn >= 3) energy += 1;
    if (relic_has(bc, RelicId::PAELS_TEARS) && relic_aux(bc, RelicId::PAELS_TEARS) > 0) {
        energy += 2;
        set_aux(bc, RelicId::PAELS_TEARS, 0);
    }
    if (relic_has(bc, RelicId::SEAL_OF_GOLD) && bc.gold >= 3) {
        bc.gold -= 3;
        energy += 1;
    }
    return std::max(0, energy);
}

int relics_modify_draw(BattleContext &bc, int base) {
    int draw = base;
    if (relic_has(bc, RelicId::BAG_OF_PREPARATION) && bc.turn == 1) draw += 2;
    if (relic_has(bc, RelicId::BIG_MUSHROOM) && bc.turn == 1) draw -= 2;
    if (relic_has(bc, RelicId::POCKETWATCH) && bc.turn > 1 && bc.cardsPlayedLastTurn <= 3) draw += 3;
    if (relic_has(bc, RelicId::FIDDLE)) draw += 2;
    if (relic_has(bc, RelicId::PAELS_BLOOD)) draw += 1;
    if (relic_has(bc, RelicId::SNECKO_EYE)) draw += 2;
    if (relic_has(bc, RelicId::BOOMING_CONCH) && bc.turn == 1 &&
        std::strstr(encounter_key(bc.encounter), "ELITE") != nullptr) {
        draw += 2;
    }
    if (relic_has(bc, RelicId::POLLINOUS_CORE) &&
        relic_aux(bc, RelicId::POLLINOUS_CORE) == 4) {
        draw += 2;
        set_aux(bc, RelicId::POLLINOUS_CORE, 0);
    }
    return draw;
}

void relics_turn_start(BattleContext &bc) {
    bc.player.power[static_cast<int>(PowerId::DIAMOND_DIADEM)] = 0;
    set_aux(bc, RelicId::MUSIC_BOX, 0);
    // PollinousCore.BeforeSideTurnStart counts player turns across combats.
    if (relic_has(bc, RelicId::POLLINOUS_CORE)) bump(bc, RelicId::POLLINOUS_CORE, 1);
    if (relic_has(bc, RelicId::ANCHOR) && bc.turn == 1) bc.gain_block(10, false, false);
    if (relic_has(bc, RelicId::FAKE_ANCHOR) && bc.turn == 1) bc.gain_block(4, false, false);
    if (relic_has(bc, RelicId::FAKE_BLOOD_VIAL) && bc.turn == 1) {
        bc.heal_hp(1);
    }
    if (relic_has(bc, RelicId::SAI)) bc.gain_block(7, false, false);
    if (relic_has(bc, RelicId::MR_STRUGGLES)) damage_all(bc, bc.turn);
    if (relic_has(bc, RelicId::TOASTY_MITTENS)) {
        if (bc.drawCount == 0) bc.shuffle_discard_into_draw();
        if (bc.drawCount > 0) {
            int idx = bc.drawCount - 1;
            if (bc.turn == 1) {
                for (int i = bc.drawCount - 1; i >= 0; --i) {
                    if (!card_has(bc.draw[i], CF_INNATE)) { idx = i; break; }
                }
            }
            Card c = bc.draw[idx];
            bc.remove_draw_at(idx);
            bc.move_to_exhaust(c);
        }
        bc.add_player_power(PowerId::STRENGTH, 1);
    }
    if (relic_has(bc, RelicId::PAELS_LEGION) && relic_aux(bc, RelicId::PAELS_LEGION) > 0) {
        bump(bc, RelicId::PAELS_LEGION, -1);
    }
    // HistoryCourse.AfterPlayerTurnStartEarly: only the last non-dupe attack or
    // skill played on the previous round is replayed, as a fresh copy.
    if (relic_has(bc, RelicId::HISTORY_COURSE) && bc.turn > 1 && bc.hasLastPlayed &&
        bc.lastPlayedTurn == bc.turn - 1) {
        Card dupe = bc.lastPlayedCard;
        dupe.uid = bc.require_card_uid();
        bc.auto_play_dupe(dupe);
    }
    if (relic_has(bc, RelicId::BLOOD_VIAL) && bc.turn == 1) {
        bc.heal_hp(2);
    }
    if (relic_has(bc, RelicId::MERCURY_HOURGLASS)) damage_all(bc, 3);
    if (relic_has(bc, RelicId::BRIMSTONE)) {
        bc.add_player_power(PowerId::STRENGTH, 2);
        for (int m = 0; m < bc.monsterCount; ++m) {
            if (bc.monsters[m].alive) bc.monsters[m].strength += 1;
        }
    }
    if (relic_has(bc, RelicId::STONE_CALENDAR) && bc.turn == 7) damage_all(bc, 52);
    if (relic_has(bc, RelicId::HORN_CLEAT) && bc.turn == 2) bc.gain_block(14, false, false);
    if (relic_has(bc, RelicId::CAPTAINS_WHEEL) && bc.turn == 3) bc.gain_block(18, false, false);
    if (relic_has(bc, RelicId::SPARKLING_ROUGE) && bc.turn == 3) {
        bc.add_player_power(PowerId::STRENGTH, 1);
        bc.player.dexterity += 1;
    }
    const int clay = aux_index(bc, RelicId::SELF_FORMING_CLAY);
    if (clay >= 0 && bc.relicAux[clay] > 0) {
        bc.gain_block(bc.relicAux[clay], false, false);
        bc.relicAux[clay] = 0;
    }
    set_aux(bc, RelicId::DEMON_TONGUE, 0);
    relics_current_hp_changed(bc);
}

void relics_hand_drawn(BattleContext &bc) {
    if (relic_has(bc, RelicId::RADIANT_PEARL) && bc.turn == 1) {
        bc.add_card_to_hand(make_card(CardId::LUMINESCE, false, bc.require_card_uid()));
    }
    if (relic_has(bc, RelicId::JEWELED_MASK) && bc.turn == 1) {
        int idx = -1;
        for (int i = 0; i < bc.drawCount; ++i) {
            if (card_def(bc.draw[i].id).type != CardType::POWER) continue;
            idx = i;
            break;
        }
        if (idx >= 0) {
            Card c = bc.draw[idx];
            bc.remove_draw_at(idx);
            card_set_turn_cost(c, 0);
            bc.add_card_to_hand(c);
        }
    }
    if (relic_has(bc, RelicId::CROSSBOW)) {
        Card c = bc.random_card_of_type(CardType::ATTACK, false);
        card_set_turn_cost(c, 0);
        bc.add_card_to_hand(c);
    }
    if (relic_has(bc, RelicId::CHOICES_PARADOX) && bc.turn == 1) {
        Card cards[5];
        CardId picked[5]{};
        int n = 0;
        while (n < 5) {
            cards[n] = bc.random_character_card_excluding(picked, n);
            picked[n] = cards[n].id;
            cards[n].retainThisCombat = true;
            ++n;
        }
        Card dummy{};
        dummy.uid = 0xFFFF;
        bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, false);
        if (bc.pending.op != ChoiceOp::NONE) bc.pending.hasSource = false;
    }
    if (relic_has(bc, RelicId::WHISPERING_EARRING) && bc.turn == 1) {
        int guard = 0;
        while (bc.handCount > 0 && guard++ < 13 && bc.outcome == Outcome::UNDECIDED) {
            Card c = bc.hand[0];
            for (int i = 0; i + 1 < bc.handCount; ++i) bc.hand[i] = bc.hand[i + 1];
            --bc.handCount;
            bc.auto_play_random(c, false);
        }
    }
    if (relic_has(bc, RelicId::BELLOWS) && bc.turn == 1) {
        for (int i = 0; i < bc.handCount; ++i) {
            if (!bc.hand[i].upgraded) bc.upgrade_card(bc.hand[i]);
        }
    }
    if (relic_has(bc, RelicId::VEXING_PUZZLEBOX) && bc.turn == 1) {
        if (relic_aux(bc, RelicId::VEXING_PUZZLEBOX) == 0) {
            set_aux(bc, RelicId::VEXING_PUZZLEBOX, 1);
            Card c = bc.random_character_card_excluding(nullptr, 0);
            c.freeCombat = true;
            bc.add_card_to_hand(c);
        }
    }
    if (relic_has(bc, RelicId::TOOLBOX) && bc.turn == 1 &&
        relic_aux(bc, RelicId::TOOLBOX) == 0) {
        set_aux(bc, RelicId::TOOLBOX, 1);
        Card cards[3];
        CardId picked[3]{};
        int n = 0;
        for (int k = 0; k < 3; ++k) {
            cards[n] = bc.random_colorless_card_excluding(picked, n);
            picked[n] = cards[n].id;
            ++n;
        }
        Card dummy{};
        dummy.uid = 0xFFFF;
        bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, false);
        if (bc.pending.op != ChoiceOp::NONE) {
            bc.pending.hasSource = false;
            bc.pending.optional = true;
        }
    }
}

void relics_card_about_to_play(BattleContext &bc, const Card &card) {
    if (!card_is_attack(card)) return;
    if (relic_has(bc, RelicId::PEN_NIB)) {
        bump(bc, RelicId::PEN_NIB, 1);
        if (relic_aux(bc, RelicId::PEN_NIB) >= 10) set_aux(bc, RelicId::PEN_NIB, 100);
    }
}

int relics_damage_additive(const BattleContext &bc, const Card &card) {
    int out = 0;
    if (card_is_strike(card) && relic_has(bc, RelicId::STRIKE_DUMMY)) out += 3;
    if (card_is_strike(card) && relic_has(bc, RelicId::FAKE_STRIKE_DUMMY)) out += 1;
    if (card.upgraded && card_is_attack(card) && relic_has(bc, RelicId::MINIATURE_CANNON)) out += 3;
    return out;
}

int relics_damage_multiplier(const BattleContext &bc, const Card &card) {
    int out = 1;
    if (card_is_attack(card) && relic_aux(bc, RelicId::PEN_NIB) == 100) out *= 2;
    return out;
}

int relics_modify_damage(BattleContext &bc, int dmg, int target, const Card *card) {
    (void) target;
    if (card == nullptr) return dmg;
    // Kept for callers that still use the combined entry point; the canonical
    // path is calc_player_damage(..., &card), which applies additive first.
    return (dmg + relics_damage_additive(bc, *card)) * relics_damage_multiplier(bc, *card);
}

int relics_modify_hp_loss(BattleContext &bc, int amount) {
    int out = amount;
    if (relic_has(bc, RelicId::TUNGSTEN_ROD)) out = std::max(0, out - 1);
    if (relic_has(bc, RelicId::BEATING_REMNANT)) {
        out = std::min(out, std::max(0, 20 - bc.hpLostThisTurn));
    }
    return out;
}

void relics_damage_received(BattleContext &bc, int amount) {
    if (amount <= 0) return;
    if (relic_has(bc, RelicId::CENTENNIAL_PUZZLE) &&
        relic_aux(bc, RelicId::CENTENNIAL_PUZZLE) == 0) {
        set_aux(bc, RelicId::CENTENNIAL_PUZZLE, 1);
        bc.draw_cards(3);
    }
    if (relic_has(bc, RelicId::SELF_FORMING_CLAY)) {
        // SelfFormingClayPower stacks per unblocked hit (Counter).
        bump(bc, RelicId::SELF_FORMING_CLAY, 3);
    }
    if (relic_has(bc, RelicId::DEMON_TONGUE) && !bc.inMonsterTurn &&
        relic_aux(bc, RelicId::DEMON_TONGUE) == 0) {
        set_aux(bc, RelicId::DEMON_TONGUE, 1);
        bc.heal_hp(amount);
    }
}

bool relics_try_revive(BattleContext &bc) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (bc.relicMelted[i] || static_cast<RelicId>(bc.relics[i]) != RelicId::LIZARD_TAIL || bc.relicAux[i]) continue;
        bc.relicAux[i] = 1;
        bc.player.hp = std::max(1, bc.player.maxHp / 2);
        relics_current_hp_changed(bc);
        return true;
    }
    return false;
}

int relics_modify_block_gain(BattleContext &bc, int amount, bool fromCard) {
    if (!fromCard || amount <= 0) return amount;
    int out = amount;
    // Vambrace doubles every block gain of the card that first gains block;
    // the state becomes 2 (used) at that card's AfterCardPlayed.
    if (relic_has(bc, RelicId::VAMBRACE) && relic_aux(bc, RelicId::VAMBRACE) != 2) {
        if (relic_aux(bc, RelicId::VAMBRACE) == 0) set_aux(bc, RelicId::VAMBRACE, 1);
        out *= 2;
    }
    if (relic_has(bc, RelicId::PAELS_LEGION) && relic_aux(bc, RelicId::PAELS_LEGION) <= 0) {
        set_aux(bc, RelicId::PAELS_LEGION, 2);
        out *= 2;
    }
    return out;
}

void relics_strength_gain(BattleContext &bc, int amount) {
    if (amount <= 0) return;
    if (relic_has(bc, RelicId::RUINED_HELMET) && relic_aux(bc, RelicId::RUINED_HELMET) == 0) {
        set_aux(bc, RelicId::RUINED_HELMET, 1);
        bc.player.strength += amount;
    }
}

void relics_card_played(BattleContext &bc, const Card &card) {
    // Vambrace.AfterCardPlayed: the triggering card's doubling window ends.
    if (relic_has(bc, RelicId::VAMBRACE) && relic_aux(bc, RelicId::VAMBRACE) == 1) {
        set_aux(bc, RelicId::VAMBRACE, 2);
    }
    if ((card_is_attack(card) || card_is_skill(card)) && !bc.activePlay.dupe) {
        bc.lastPlayedCard = card;
        bc.hasLastPlayed = true;
        bc.lastPlayedTurn = bc.turn;
    }
    if (card_is_attack(card)) {
        if (relic_has(bc, RelicId::DAUGHTER_OF_THE_WIND)) bc.gain_block(1, false, false);
        if (relic_has(bc, RelicId::MUSIC_BOX) &&
            relic_aux(bc, RelicId::MUSIC_BOX) == 0) {
            set_aux(bc, RelicId::MUSIC_BOX, 1);
            Card copy = card;
            copy.uid = bc.require_card_uid();
            copy.etherealThisCombat = true;
            bc.add_card_to_hand(copy);
        }
        if (relic_has(bc, RelicId::NUNCHAKU)) {
            // Nunchaku.AttacksPlayed is a [SavedProperty]: the counter spans
            // combats and every 10th attack grants 1 energy.
            bump(bc, RelicId::NUNCHAKU, 1);
            if (relic_aux(bc, RelicId::NUNCHAKU) % 10 == 0) bc.player.energy += 1;
        }
        if (bc.attacksPlayedThisTurn % 3 == 0) {
            if (relic_has(bc, RelicId::KUNAI)) bc.player.dexterity += 1;
            if (relic_has(bc, RelicId::SHURIKEN)) bc.add_player_power(PowerId::STRENGTH, 1);
            if (relic_has(bc, RelicId::ORNAMENTAL_FAN)) bc.gain_block(4, false, false);
            if (relic_has(bc, RelicId::KUSARIGAMA)) bc.attack_random_monster(6, 1, false);
        }
        set_aux(bc, RelicId::PEN_NIB, relic_aux(bc, RelicId::PEN_NIB) == 100 ? 0
                                                                            : relic_aux(bc, RelicId::PEN_NIB));
    }
    if (card_is_skill(card)) {
        if (relic_has(bc, RelicId::LETTER_OPENER) && bc.skillsPlayedThisTurn % 3 == 0) {
            damage_all(bc, 5);
        }
        if (relic_has(bc, RelicId::TUNING_FORK)) {
            // TuningFork.SkillsPlayed is a [SavedProperty]: count spans combats
            // and is reduced by the threshold rather than reset.
            bump(bc, RelicId::TUNING_FORK, 1);
            if (relic_aux(bc, RelicId::TUNING_FORK) >= 10) {
                bc.gain_block(7, false, false);
                bump(bc, RelicId::TUNING_FORK, -10);
            }
        }
    }
    if (card_is_power(card)) {
        if (relic_has(bc, RelicId::PERMAFROST) && relic_aux(bc, RelicId::PERMAFROST) == 0) {
            set_aux(bc, RelicId::PERMAFROST, 1);
            bc.gain_block(6, false, false);
        }
        if (relic_has(bc, RelicId::GAME_PIECE)) bc.draw_cards(1);
        if (relic_has(bc, RelicId::LOST_WISP)) damage_all(bc, 8);
        if (relic_has(bc, RelicId::MUMMIFIED_HAND) && bc.handCount > 0) {
            // MummifiedHand: only cards that actually cost energy/stars are
            // candidates (includeGlobalModifiers:false), with a fallback to any.
            int candidates[MAX_HAND];
            int n = 0;
            for (int i = 0; i < bc.handCount; ++i) {
                if (card_cost(bc.hand[i]) > 0) candidates[n++] = i;
            }
            if (n > 0) {
                const int idx = candidates[bc.cardSelectionRng.next_int(0, n - 1)];
                card_set_turn_cost(bc.hand[idx], 0);
            } else {
                // The reference consumes the fallback NextItem roll, but keeps
                // the first query result (null). It must not turn X-cost cards
                // into fixed-cost cards.
                (void) bc.cardSelectionRng.next_int(0, bc.handCount - 1);
            }
        }
    }
    if (relic_has(bc, RelicId::IRON_CLUB)) {
        // IronClub.CardsPlayed is a [SavedProperty]: every 4th card across the
        // whole run draws 1.
        bump(bc, RelicId::IRON_CLUB, 1);
        if (relic_aux(bc, RelicId::IRON_CLUB) % 4 == 0) bc.draw_cards(1);
    }
    if (relic_has(bc, RelicId::RAINBOW_RING)) {
        int flags = relic_aux(bc, RelicId::RAINBOW_RING);
        if (flags < 8) {
            if (card_is_attack(card)) flags |= 1;
            if (card_is_skill(card)) flags |= 2;
            if (card_is_power(card)) flags |= 4;
            if (flags == 7) {
                bc.add_player_power(PowerId::STRENGTH, 1);
                bc.player.dexterity += 1;
                flags = 8;
            }
            set_aux(bc, RelicId::RAINBOW_RING, flags);
        }
    }
    if (relic_has(bc, RelicId::UNCEASING_TOP) && bc.handCount == 0) bc.draw_cards(1);
}

void relics_monster_died(BattleContext &bc) {
    if (relic_has(bc, RelicId::GREMLIN_HORN)) {
        bc.player.energy += 1;
        bc.draw_cards(1);
    }
}

void relics_exhausted(BattleContext &bc, const Card &card, bool causedByEthereal) {
    if (relic_has(bc, RelicId::CHARONS_ASHES)) damage_all(bc, 3);
    if (relic_has(bc, RelicId::FORGOTTEN_SOUL)) bc.attack_random_monster(1, 1, false);
    if (relic_has(bc, RelicId::JOSS_PAPER)) {
        const int i = aux_index(bc, RelicId::JOSS_PAPER);
        if (i >= 0) {
            if (causedByEthereal) {
                // EtherealCount is not saved and settles at turn end.
                ++bc.relicAux2[i];
            } else {
                ++bc.relicAux[i];
                joss_paper_draw(bc, i);
            }
        }
    }
    if (card_is_skill(card) && relic_has(bc, RelicId::BURNING_STICKS) &&
        relic_aux(bc, RelicId::BURNING_STICKS) == 0) {
        set_aux(bc, RelicId::BURNING_STICKS, 1);
        Card copy = card;
        copy.uid = bc.require_card_uid();
        bc.add_card_to_hand(copy);
    }
}

void relics_shuffled(BattleContext &bc) {
    if (relic_has(bc, RelicId::PENDULUM)) bc.draw_cards(1);
    if (relic_has(bc, RelicId::THE_ABACUS)) bc.gain_block(6, false, false);
    // Biiig Hug: after each shuffle, a Soot is added to the draw pile.
    if (relic_has(bc, RelicId::BIIIG_HUG)) add_to_draw(bc, CardId::SOOT, 1);
}

void relics_turn_end(BattleContext &bc) {
    if (relic_has(bc, RelicId::ORICHALCUM) && bc.player.block == 0) bc.gain_block(6, false, false);
    if (relic_has(bc, RelicId::FAKE_ORICHALCUM) && bc.player.block == 0) bc.gain_block(3, false, false);
    if (relic_has(bc, RelicId::DIAMOND_DIADEM) && bc.cardsPlayedThisTurn <= 2) {
        bc.player.power[static_cast<int>(PowerId::DIAMOND_DIADEM)] = 1;
    }
    if (relic_has(bc, RelicId::PAELS_TEARS)) {
        set_aux(bc, RelicId::PAELS_TEARS, bc.player.energy > 0 ? 1 : 0);
    }
    if (relic_has(bc, RelicId::RIPPLE_BASIN) && bc.attacksPlayedThisTurn == 0) {
        bc.gain_block(4, false, false);
    }
    if (relic_has(bc, RelicId::PARRYING_SHIELD) && bc.player.block >= 10) {
        bc.attack_random_monster(6, 1, false);
    }
    if (relic_has(bc, RelicId::CLOAK_CLASP)) bc.gain_block(bc.handCount, false, false);
    if (relic_has(bc, RelicId::SCREAMING_FLAGON) && bc.handCount == 0) {
        damage_all(bc, 20);
    }
}

void relics_after_turn(BattleContext &bc) {
    bc.attacksPlayedLastTurn = bc.attacksPlayedThisTurn;
    bc.cardsPlayedLastTurn = bc.cardsPlayedThisTurn;
    set_aux(bc, RelicId::RAINBOW_RING, 0);
}

void relics_ethereal_turn_end(BattleContext &bc) {
    // JossPaper.AfterTurnEnd: ethereal exhausts settle only now.
    const int i = aux_index(bc, RelicId::JOSS_PAPER);
    if (i < 0) return;
    bc.relicAux[i] += bc.relicAux2[i];
    bc.relicAux2[i] = 0;
    joss_paper_draw(bc, i);
}

void relics_potion_obtained(BattleContext &bc) {
    const int i = aux_index(bc, RelicId::BELT_BUCKLE);
    if (i >= 0 && bc.relicAux[i] != 0) {
        bc.player.dexterity -= 2;
        bc.relicAux[i] = 0;
    }
}

void relics_potion_used(BattleContext &bc) {
    const int i = aux_index(bc, RelicId::BELT_BUCKLE);
    if (i >= 0 && bc.potionCount == 0 && bc.relicAux[i] == 0) {
        bc.player.dexterity += 2;
        bc.relicAux[i] = 1;
    }
    if (relic_has(bc, RelicId::REPTILE_TRINKET)) {
        bc.add_temp_strength(3);
    }
}

int relics_block_retain(const BattleContext &bc) {
    return relic_has(bc, RelicId::STURDY_CLAMP) ? 10 : 0;
}

bool relics_keep_energy(const BattleContext &bc) {
    (void) bc;
    return false;
}

// ---------------------------------------------------------------- run layer

namespace {

bool reward_pool_card(CardId id, bool colorless) {
    if (!card_native_available(id)) return false;
    const CardDef &d = card_def(id);
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) {
        return false;
    }
    return colorless ? d.pool == CardPool::COLORLESS
                     : d.pool == CardPool::IRONCLAD;
}

CardId pick_card(Rng &rng, Rarity want, bool colorless = false) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (reward_pool_card(id, colorless) && card_def(id).rarity == want) pool[n++] = id;
    }
    if (n == 0) return CardId::STRIKE_IRONCLAD;
    native_sort_card_ids(pool, n);
    return pool[rng.next_int(0, n - 1)];
}

CardId pick_card_type(Rng &rng, CardType type) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (!reward_pool_card(id, false)) continue;
        if (card_def(id).type != type) continue;
        pool[n++] = id;
    }
    if (n == 0) return CardId::STRIKE_IRONCLAD;
    native_sort_card_ids(pool, n);
    return pool[rng.next_int(0, n - 1)];
}

void lose_relic_max_hp(RunContext &rc, int amount) {
    // Native damage/death prevention occurs before the maximum is clamped.
    const int newMax = rc.maxHp - amount;
    if (newMax < rc.hp) run_take_noncombat_damage(rc, rc.hp - newMax);
    rc.maxHp = std::max(1, newMax);
    rc.hp = std::min(rc.hp, rc.maxHp);
}

void add_deck_card(RunContext &rc, CardId id, bool upgraded = false) {
    rc.add_card_to_deck(rc.make_run_card(id, upgraded));
}

void add_random_deck_card(RunContext &rc, Rarity want, bool upgraded = false,
                          bool colorless = false) {
    add_deck_card(rc, pick_card(rc.runRng[RNG_NICHE], want, colorless), upgraded);
}

void upgrade_random_cards(RunContext &rc, int n, int cardType = -1) {
    int candidates[MAX_DECK],count=0;
    for(int i=0;i<rc.deckCount;++i)
        if(card_upgradable(rc.deck[i]) && (cardType<0 || static_cast<int>(card_def(rc.deck[i].id).type)==cardType))
            candidates[count++]=i;
    native_sort_card_indices(rc,candidates,count);
    rc.runRng[RNG_NICHE].shuffle(candidates,count);
    // CardCmd.Upgrade is suppressed for a dead owner, after selection RNG.
    if(rc.hp>0)for(int i=0;i<std::min(n,count);++i)card_apply_upgrade(rc.deck[candidates[i]]);
}

void remove_random_cards(RunContext &rc, int n) {
    for (int k = 0; k < n && rc.deckCount > 0; ++k) {
        const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
        for (int i = idx; i + 1 < rc.deckCount; ++i) rc.deck[i] = rc.deck[i + 1];
        --rc.deckCount;
    }
}

void transform_random_cards(RunContext &rc, int n, bool upgrade, bool basic_only) {
    int done = 0;
    for (int pass = 0; pass < 400 && done < n && rc.deckCount > 0; ++pass) {
        const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
        const Card &originalCard = rc.deck[idx];
        const CardDef &original = card_def(originalCard.id);
        if (basic_only && original.rarity != Rarity::BASIC) continue;

        CardPool wantedPool = original.pool;
        if (original.rarity == Rarity::ANCIENT || original.rarity == Rarity::EVENT ||
            original.rarity == Rarity::TOKEN) {
            wantedPool = CardPool::COLORLESS;
        }
        CardId pool[static_cast<int>(CardId::COUNT)];
        int pn = 0;
        for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
            const CardDef &d = CARD_DEFS[i];
            if (!card_native_available(d.id)) continue;
            if (d.pool != wantedPool) continue;
            if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
                d.rarity != Rarity::RARE) {
                continue;
            }
            if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
            if (static_cast<CardId>(i) == originalCard.id) continue;
            pool[pn++] = static_cast<CardId>(i);
        }
        if (pn == 0) continue;
        native_sort_card_ids(pool, pn);
        const std::uint16_t uid = originalCard.uid;
        rc.deck[idx] =
            make_card(pool[rc.runRng[RNG_NICHE].next_int(0, pn - 1)], upgrade, uid);
        ++done;
    }
}

void add_random_potion(RunContext &rc) {
    for (int guard = 0; guard < 32 && rc.potionCount < rc.potionSlots; ++guard) {
        const int k = rc.runRng[RNG_NICHE].next_int(1, static_cast<int>(PotionId::COUNT) - 1);
        const PotionDef &d = potion_def(static_cast<PotionId>(k));
        if (d.ironclad) {
            rc.add_potion(static_cast<PotionId>(k));
            return;
        }
    }
}

void fill_potions(RunContext &rc) {
    int guard = 0;
    while (rc.potionCount < rc.potionSlots && guard++ < 32) {
        const int k = rc.runRng[RNG_NICHE].next_int(1, static_cast<int>(PotionId::COUNT) - 1);
        const PotionDef &d = potion_def(static_cast<PotionId>(k));
        if (d.ironclad) rc.add_potion(static_cast<PotionId>(k));
        else break;
    }
}

}  // namespace

bool run_relic_allowed(const RunContext &rc, RelicId id) {
    // RelicModel.IsBeforeAct3TreasureChest for a single-player run.
    switch (id) {
        case RelicId::AMETHYST_AUBERGINE:
        case RelicId::BOOK_OF_FIVE_RINGS:
        case RelicId::BOWLER_HAT:
        case RelicId::DRAGON_FRUIT:
        case RelicId::FROZEN_EGG:
        case RelicId::GIRYA:
        case RelicId::JUZU_BRACELET:
        case RelicId::LASTING_CANDY:
        case RelicId::LUCKY_FYSH:
        case RelicId::MEAL_TICKET:
        case RelicId::MOLTEN_EGG:
        case RelicId::OLD_COIN:
        case RelicId::PLANISPHERE:
        case RelicId::SHOVEL:
        case RelicId::TOXIC_EGG:
        case RelicId::WHITE_BEAST_STATUE:
        case RelicId::WHITE_STAR:
            return rc.floor < 41;
        default:
            return true;
    }
}

RelicId run_random_relic(Rng &rng, RunContext &rc) {
    const float roll = rng.next_float();
    const Rarity rarity = roll < 0.5f ? Rarity::COMMON : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
    return rc.pull_relic(rarity);
}

void run_gain_gold(RunContext &rc, int amount) {
    if (amount <= 0) return;
    if (run_has_relic(rc, RelicId::ECTOPLASM)) return;
    const int bonus = run_has_relic(rc, RelicId::BOWLER_HAT) ? amount / 5 : 0;
    rc.gold += amount + bonus;
    if (run_has_relic(rc, RelicId::DRAGON_FRUIT)) {
        // Bowler Hat performs a separate bonus-gold gain and fires the hook again.
        const int gains = 1 + (bonus > 0 ? 1 : 0);
        rc.maxHp += gains;
        rc.hp += gains;
    }
}

int run_energy_bonus(const RunContext &rc) {
    static const RelicId energyRelics[] = {
        RelicId::ECTOPLASM, RelicId::BLESSED_ANTLER, RelicId::BLOOD_SOAKED_ROSE,
        RelicId::PHILOSOPHERS_STONE, RelicId::PRISMATIC_GEM,
        RelicId::SPIKED_GAUNTLETS, RelicId::VELVET_CHOKER, RelicId::WHISPERING_EARRING,
        RelicId::SOZU,
    };
    int bonus = 0;
    for (RelicId id : energyRelics) {
        if (run_has_relic(rc, id)) ++bonus;
    }
    for (int i = 0; i < rc.relicCount; ++i) {
        if (!rc.relicMelted[i] && rc.relics[i] == static_cast<int>(RelicId::PUMPKIN_CANDLE) &&
            rc.relicAux[i] == rc.act) ++bonus;
    }
    return bonus;
}

int run_turn1_energy(const RunContext &rc) {
    return rc.nextCombatEnergy + (rc.teaSetPending ? 2 : 0);
}

void run_take_noncombat_damage(RunContext &rc, int amount) {
    if (run_has_relic(rc, RelicId::TUNGSTEN_ROD)) amount = std::max(0, amount - 1);
    rc.hp = std::max(0, rc.hp - amount);
    if (rc.hp) return;
    // Fairy's ShouldDie runs before LizardTail's ShouldDieLate.
    for (int i = 0; i < rc.potionSlots; ++i) {
        if (rc.potions[i] != static_cast<int>(PotionId::FAIRY_IN_ABOTTLE)) continue;
        potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount, i);
        rc.hp = std::max(1, rc.maxHp * 30 / 100);
        return;
    }
    for (int i = 0; i < rc.relicCount; ++i) {
        if (rc.relicMelted[i] || rc.relics[i] != static_cast<int>(RelicId::LIZARD_TAIL) || rc.relicAux[i]) continue;
        rc.relicAux[i] = 1;
        rc.hp = std::max(1, rc.maxHp / 2);
        return;
    }
    rc.won = false;
    rc.screen = RunScreen::RUN_OVER;
}

void relics_on_obtain(RunContext &rc, RelicId id) {
    switch (id) {
        case RelicId::SILKEN_TRESS: rc.gold=0; break;
        case RelicId::GOLDEN_COMPASS: rc.apply_golden_compass(); break;
        // shared / normal pool
        case RelicId::STRAWBERRY: rc.maxHp += 7; rc.hp += 7; break;
        case RelicId::PEAR: rc.maxHp += 10; rc.hp += 10; break;
        case RelicId::MANGO: rc.maxHp += 14; rc.hp += 14; break;
        case RelicId::LEES_WAFFLE: rc.maxHp += 7; rc.hp = rc.maxHp; break;
        case RelicId::OLD_COIN: run_gain_gold(rc, 300); break;
        case RelicId::POTION_BELT: rc.potionSlots = std::min(MAX_POTIONS, rc.potionSlots + 2); break;
        case RelicId::CAULDRON: rc.queue_potion_rewards(5); break;
        case RelicId::WAR_PAINT:
        case RelicId::WHETSTONE: {
            const CardType want = id == RelicId::WAR_PAINT ? CardType::SKILL : CardType::ATTACK;
            upgrade_random_cards(rc,2,static_cast<int>(want));
            break;
        }

        // event / ancient relics
        case RelicId::ALCHEMICAL_COFFER:
            potion_alchemical_coffer_on_obtain(rc);
            break;
        case RelicId::ARCANE_SCROLL: {
            Card candidates[1];
            if (make_relic_card_reward_candidates(rc, id, candidates, 1) != 1 ||
                !rc.add_card_to_deck(candidates[0]))
                throw std::logic_error("Arcane Scroll reward cannot be obtained");
            break;
        }
        case RelicId::ARCHAIC_TOOTH: {
            // Transcendence: the starter card becomes its ancient card
            // (Ironclad: Bash -> Break), preserving upgrade state.
            for (int i = 0; i < rc.deckCount; ++i) {
                if (rc.deck[i].id != CardId::BASH) continue;
                rc.deck[i].id = CardId::BREAK;
                break;
            }
            break;
        }
        case RelicId::ASTROLABE: begin_deck_relic_choice(rc, 8, 3); break;
        case RelicId::BEAUTIFUL_BRACELET: {
            int candidates[MAX_DECK], count = 0;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::SWIFT)) candidates[count++] = i;
            // TakeRandom shuffles the filtered list once, then takes four.
            rc.runRng[RNG_NICHE].shuffle(candidates, count);
            for (int i = 0; i < std::min(4, count); ++i)
                card_apply_enchantment(rc.deck[candidates[i]], EnchantmentId::SWIFT, 2);
            break;
        }
        case RelicId::BIG_MUSHROOM: rc.maxHp += 20; rc.hp += 20; break;
        case RelicId::BONE_TEA:
            for (int i = 0; i < rc.relicCount; ++i)
                if (!rc.relicMelted[i] && rc.relics[i] == static_cast<int>(id)) rc.relicAux[i] = 1;
            break;
        case RelicId::BYRDPIP: relic_persistent_on_obtain(rc, id); break;
        case RelicId::BLOOD_SOAKED_ROSE: add_deck_card(rc, CardId::ENTHRALLED); break;
        case RelicId::BIIIG_HUG: begin_deck_relic_choice(rc, 6, 4); break;
        case RelicId::CALLING_BELL:
            add_deck_card(rc, CardId::CURSE_OF_THE_BELL);
            rc.queue_relic_reward(Rarity::COMMON);
            rc.queue_relic_reward(Rarity::UNCOMMON);
            rc.queue_relic_reward(Rarity::RARE);
            break;
        case RelicId::CHOSEN_CHEESE: break;  // applied at combat end
        case RelicId::CLAWS: begin_card_grid(rc, 3); break;
        case RelicId::PAELS_GROWTH: begin_card_grid(rc, 4); break;
        case RelicId::CURSED_PEARL:
            add_deck_card(rc, CardId::GREED);
            run_gain_gold(rc, 333);
            break;
        case RelicId::DISTINGUISHED_CAPE: {
            // Native draws two distinct generatable curses in ordinal ID order.
            CardId curses[] = {CardId::CLUMSY, CardId::DEBT, CardId::DECAY, CardId::DOUBT,
                               CardId::GUILTY, CardId::INJURY, CardId::NORMALITY,
                               CardId::REGRET, CardId::SHAME, CardId::WRITHE};
            int remaining = static_cast<int>(sizeof(curses) / sizeof(curses[0]));
            for (int i = 0; i < 2; ++i) {
                const int picked = rc.runRng[RNG_NICHE].next_int(0, remaining - 1);
                add_deck_card(rc, curses[picked]);
                for (int j = picked; j + 1 < remaining; ++j) curses[j] = curses[j + 1];
                --remaining;
            }
            for (int i = 0; i < 3; ++i) add_deck_card(rc, CardId::APPARITION);
            break;
        }
        case RelicId::DUSTY_TOME:
            if (!obtain_dusty_tome_card(rc, rc.preparedDustyTomeCard))
                throw std::logic_error("Dusty Tome has no valid prepared ancient card");
            break;
        case RelicId::EMBER_TEA: rc.emberTeaCombats = 5; break;
        case RelicId::EMPTY_CAGE: begin_deck_relic_choice(rc, 6, 2); break;
        case RelicId::FAKE_LEES_WAFFLE: rc.hp = std::min(rc.maxHp, rc.hp + rc.maxHp / 10); break;
        case RelicId::FAKE_MANGO: rc.maxHp += 3; rc.hp += 3; break;
        case RelicId::FRAGRANT_MUSHROOM: {
            run_take_noncombat_damage(rc, 15);
            upgrade_random_cards(rc,2);
            break;
        }
        case RelicId::FUR_COAT: rc.furCoatCombats = 7; break;
        case RelicId::GLASS_EYE:
            rc.queue_card_reward(Rarity::COMMON, false);
            rc.queue_card_reward(Rarity::COMMON, false);
            rc.queue_card_reward(Rarity::UNCOMMON, false);
            rc.queue_card_reward(Rarity::UNCOMMON, false);
            rc.queue_card_reward(Rarity::RARE, false);
            break;
        case RelicId::GOLDEN_PEARL: run_gain_gold(rc, 150); break;
        case RelicId::JEWELRY_BOX: add_deck_card(rc, CardId::APOTHEOSIS); break;
        case RelicId::LARGE_CAPSULE:
            rc.largeCapsuleRelicsRemaining = 2;
            rc.largeCapsuleCardsPending = true;
            relics_resume_lifecycle(rc);
            break;
        case RelicId::LEAD_PAPERWEIGHT:
            if (!begin_relic_card_choice(rc, id))
                throw std::logic_error("Lead Paperweight choice cannot begin");
            break;
        case RelicId::LEAFY_POULTICE:
            lose_relic_max_hp(rc, 12);
            if (!transform_first_basic_strike_and_defend(rc))
                throw std::logic_error("Leafy Poultice deck capacity exceeded");
            break;
        case RelicId::LOOMING_FRUIT: rc.maxHp += 31; rc.hp += 31; break;
        case RelicId::LOST_COFFER:
            rc.queue_card_reward(Rarity::COMMON, true);
            rc.queue_potion_rewards(1);
            break;
        case RelicId::MASSIVE_SCROLL: add_random_deck_card(rc, Rarity::UNCOMMON, false, true); break;
        case RelicId::NEOWS_TORMENT: add_deck_card(rc, CardId::NEOWS_FURY); break;
        case RelicId::NEW_LEAF: begin_deck_relic_choice(rc, 7, 1); break;
        case RelicId::NUTRITIOUS_OYSTER: rc.maxHp += 11; rc.hp += 11; break;
        case RelicId::PAELS_HORN:
            for (int i = 0; i < 2; ++i) add_deck_card(rc, CardId::RELAX);
            break;
        case RelicId::PANDORAS_BOX:
            if(!transform_basic_strikes_and_defends(rc))throw std::logic_error("Pandora deck capacity exceeded");
            break;
        case RelicId::POMANDER: begin_deck_relic_choice(rc,9,1); break;
        case RelicId::PAELS_TOOTH: begin_deck_relic_choice(rc,10,5); break;
        case RelicId::PRECARIOUS_SHEARS:
            begin_deck_relic_choice(rc, 6, 2, 16);
            break;
        case RelicId::PRECISE_SCISSORS: begin_deck_relic_choice(rc, 6, 1); break;
        case RelicId::PRESERVED_FOG:
            begin_deck_relic_choice(rc, 6, 3, 0, CardId::FOLLY);
            break;
        case RelicId::PUMPKIN_CANDLE:
            for (int i = 0; i < rc.relicCount; ++i)
                if (rc.relics[i] == static_cast<int>(id)) rc.relicAux[i] = rc.act;
            break;
        case RelicId::SAND_CASTLE: upgrade_random_cards(rc, 6); break;
        case RelicId::SCROLL_BOXES:
            rc.gold = 0;
            begin_card_grid(rc, 5);
            break;
        case RelicId::SEA_GLASS:
            if (!begin_relic_card_choice(rc, id))
                throw std::logic_error("Sea Glass choice cannot begin");
            break;
        case RelicId::SERE_TALON:
            lose_relic_max_hp(rc, 9);
            for (int i = 0; i < 3; ++i) add_deck_card(rc, CardId::WISH);
            break;
        case RelicId::SIGNET_RING: run_gain_gold(rc, 999); break;
        case RelicId::SILVER_CRUCIBLE: rc.silverCrucibleUses = 3; break;
        case RelicId::SMALL_CAPSULE:
            if (!rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]))
                throw std::logic_error("Small Capsule reward storage exhausted");
            rc.deferredCustomRewards = true;
            break;
        case RelicId::STORYBOOK: add_deck_card(rc, CardId::BRIGHTEST_FLAME); break;
        case RelicId::TANXS_WHISTLE: add_deck_card(rc, CardId::WHISTLE); break;
        case RelicId::TEA_OF_DISCOURTESY: rc.nextCombatDazed = 2; break;
        case RelicId::TOUCH_OF_OROBAS: {
            for (int i = 0; i < rc.relicCount; ++i) {
                const auto starter = static_cast<RelicId>(rc.relics[i]);
                if (relic_raw_rarity(starter) != static_cast<int>(RelicRawRarity::STARTER)) continue;
                // Native chooses the first Starter, including an already refined
                // starter (which falls back to Circlet), and obtains the fresh
                // replacement at that same position. Sibling counters must not move.
                RelicId replacement = RelicId::CIRCLET;
                switch (starter) {
                    case RelicId::BURNING_BLOOD: replacement = RelicId::BLACK_BLOOD; break;
                    case RelicId::RING_OF_THE_SNAKE: replacement = RelicId::RING_OF_THE_DRAKE; break;
                    case RelicId::DIVINE_RIGHT: replacement = RelicId::DIVINE_DESTINY; break;
                    case RelicId::BOUND_PHYLACTERY: replacement = RelicId::PHYLACTERY_UNBOUND; break;
                    case RelicId::CRACKED_CORE: replacement = RelicId::INFUSED_CORE; break;
                    default: break;
                }
                if (!rc.replace_starter_relic(i, replacement))
                    throw std::logic_error("Touch of Orobas starter replacement failed");
                break;
            }
            break;
        }
        case RelicId::TOY_BOX:
            for (int i = 0; i < 5; ++i)
                if (!rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS], false, true))
                    throw std::logic_error("Toy Box reward storage exhausted");
            rc.deferredCustomRewards = true;
            rc.toyBoxCombats = 0;
            break;
        case RelicId::VERY_HOT_COCOA: break;  // first turn of every combat
        case RelicId::WONGOS_MYSTERY_TICKET: rc.wongoCombats = 0; break;
        case RelicId::YUMMY_COOKIE: begin_deck_relic_choice(rc,9,4); break;
        default:
            break;
    }
}

void relics_combat_end(RunContext &rc, bool victory, bool boss) {
    if (!victory) return;
    if(rc.hp>0 && run_has_relic(rc,RelicId::PAELS_TOOTH) && rc.paelsToothCount>0) {
        const int copies=run_has_relic(rc,RelicId::BING_BONG)?2:1;
        if(rc.deckCount>MAX_DECK-copies)throw std::overflow_error("Pael's Tooth return exceeds deck capacity");
        const int picked=rc.playerRng[PRNG_REWARDS].next_int(0,rc.paelsToothCount-1);
        Card card=rc.paelsToothCards[picked];
        // Native reconstructs a new CardModel from the saved card record.
        card.uid=rc.allocate_card_uid();
        if(card_upgradable(card))card_apply_upgrade(card);
        // Remove the saved record only after the native add-to-deck hooks run.
        if(!rc.add_card_to_deck(card))throw std::logic_error("Pael's Tooth return failed");
        for(int i=picked;i+1<rc.paelsToothCount;++i)rc.paelsToothCards[i]=rc.paelsToothCards[i+1];
        rc.paelsToothCards[--rc.paelsToothCount]=Card{};
    }
    if (rc.combatIsElite && run_has_relic(rc, RelicId::SWORD_OF_STONE)) {
        ++rc.swordOfStoneWins;
        if (rc.swordOfStoneWins >= 5) {
            for (int i = 0; i < rc.relicCount; ++i) {
                if (rc.relicMelted[i] || rc.relics[i] != static_cast<int>(RelicId::SWORD_OF_STONE)) continue;
                rc.relics[i] = static_cast<int>(RelicId::SWORD_OF_JADE);
                rc.relicAux[i] = 0;
                // RelicCmd.Replace obtains a fresh, non-wax model.
                rc.relicWax[i] = rc.relicMelted[i] = false;
                break;
            }
        }
    }
    // Native dispatches every AfterCombatVictoryEarly hook before the ordinary
    // victory hooks. Meat checks the HP threshold before Burning/Black Blood.
    if (rc.hp > 0 && run_has_relic(rc, RelicId::MEAT_ON_THE_BONE) && rc.hp <= rc.maxHp / 2) {
        rc.hp = std::min(rc.maxHp, rc.hp + 12);
    }
    if (rc.hp > 0) {
        int heal = 0;
        if (run_has_relic(rc, RelicId::BLACK_BLOOD)) heal = 12;
        else if (run_has_relic(rc, RelicId::BURNING_BLOOD)) heal = 6;
        rc.hp = std::min(rc.maxHp, rc.hp + heal);
    }
    // Pantograph heals on entering the Boss room (run.cpp), not after victory.
    if ((!boss || rc.act < MAX_ACTS - 1) && run_has_relic(rc, RelicId::AMETHYST_AUBERGINE)) {
        run_gain_gold(rc, 10);
    }
    if (run_has_relic(rc, RelicId::CHOSEN_CHEESE)) {
        rc.maxHp += 1;
        rc.hp += 1;
    }
    if (rc.wongoCombats >= 0 && rc.wongoCombats < 5 &&
        run_has_relic(rc, RelicId::WONGOS_MYSTERY_TICKET)) {
        ++rc.wongoCombats;
    }
}

}  // namespace sts2
