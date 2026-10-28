#include "sts2/relics.h"
#include "sts2/monsters.h"

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
        if (static_cast<RelicId>(bc.relics[i]) == id) return true;
    }
    return false;
}

bool run_has_relic(const RunContext &rc, RelicId id) {
    for (int i = 0; i < rc.relicCount; ++i) {
        if (static_cast<RelicId>(rc.relics[i]) == id) return true;
    }
    return false;
}

int relic_aux(const BattleContext &bc, RelicId id) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (static_cast<RelicId>(bc.relics[i]) == id) return bc.relicAux[i];
    }
    return 0;
}

void relic_aux_set(BattleContext &bc, RelicId id, int value) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (static_cast<RelicId>(bc.relics[i]) == id) {
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
        if (static_cast<RelicId>(bc.relics[i]) == id) return i;
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
        const int pos = bc.rng.next_int(0, bc.drawCount);
        for (int i = bc.drawCount; i > pos; --i) bc.draw[i] = bc.draw[i - 1];
        bc.draw[pos] = make_card(id, false, bc.nextUid++);
        ++bc.drawCount;
    }
}

void fill_combat_potions(BattleContext &bc) {
    int guard = 0;
    while (bc.potionCount < bc.potionSlots && guard++ < 32) {
        const int k = bc.rng.next_int(1, static_cast<int>(PotionId::COUNT) - 1);
        const PotionDef &d = potion_def(static_cast<PotionId>(k));
        if (d.ironclad) bc.add_potion(static_cast<PotionId>(k));
        else break;
    }
}

}  // namespace

void relics_combat_start(BattleContext &bc) {
    for (int i = 0; i < bc.relicCount; ++i) {
        const RelicId id = static_cast<RelicId>(bc.relics[i]);
        bc.relicAux[i] = 0;
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
                bc.player.strength += 1;
                break;
            case RelicId::ODDLY_SMOOTH_STONE:
                bc.player.dexterity += 1;
                break;
            case RelicId::BAG_OF_MARBLES:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) bc.monsters[m].vulnerable += 1;
                }
                break;
            case RelicId::RED_MASK:
                for (int m = 0; m < bc.monsterCount; ++m) {
                    if (bc.monsters[m].alive) bc.monsters[m].weak += 1;
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
                    bc.player.strength += 2;
                }
                break;
            case RelicId::BELT_BUCKLE:
                if (bc.potionCount == 0) bc.player.dexterity += 2;
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
                bc.player.strength += 3;
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
                bc.lose_hp(4, false);
                break;
            case RelicId::DELICATE_FROND:
                fill_combat_potions(bc);
                break;
            case RelicId::STONE_CRACKER:
                if (std::strstr(encounter_key(bc.encounter), "BOSS") != nullptr) {
                    int n = 0;
                    for (int d = 0; d < bc.drawCount && n < 3; ++d) {
                        if (bc.draw[d].upgraded) continue;
                        bc.upgrade_card(bc.draw[d]);
                        ++n;
                    }
                }
                break;
            default:
                break;
        }
    }
}

int relics_energy_for_turn(BattleContext &bc, int base) {
    int energy = base;
    if (relic_has(bc, RelicId::LANTERN) && bc.turn == 1) energy += 1;
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
    if (relic_has(bc, RelicId::SEAL_OF_GOLD) && bc.gold >= 5) {
        bc.gold -= 5;
        energy += 1;
    }
    return std::max(0, energy);
}

int relics_modify_draw(BattleContext &bc, int base) {
    int draw = base;
    if (relic_has(bc, RelicId::BAG_OF_PREPARATION) && bc.turn == 1) draw += 2;
    if (relic_has(bc, RelicId::POCKETWATCH) && bc.turn > 1 && bc.cardsPlayedLastTurn <= 3) draw += 3;
    if (relic_has(bc, RelicId::FIDDLE)) draw += 2;
    if (relic_has(bc, RelicId::PAELS_BLOOD)) draw += 1;
    if (relic_has(bc, RelicId::SNECKO_EYE)) draw += 2;
    if (relic_has(bc, RelicId::BOOMING_CONCH) && bc.turn == 1 &&
        std::strstr(encounter_key(bc.encounter), "ELITE") != nullptr) {
        draw += 2;
    }
    if (relic_has(bc, RelicId::POLLINOUS_CORE) && bc.turn % 4 == 0) draw += 2;
    return draw;
}

void relics_turn_start(BattleContext &bc) {
    bc.player.power[static_cast<int>(PowerId::DIAMOND_DIADEM)] = 0;
    set_aux(bc, RelicId::MUSIC_BOX, 0);
    if (relic_has(bc, RelicId::ANCHOR) && bc.turn == 1) bc.player.block += 10;
    if (relic_has(bc, RelicId::FAKE_ANCHOR) && bc.turn == 1) bc.player.block += 4;
    if (relic_has(bc, RelicId::FAKE_BLOOD_VIAL) && bc.turn == 1) {
        bc.player.hp = std::min(bc.player.maxHp, bc.player.hp + 1);
    }
    if (relic_has(bc, RelicId::SAI)) bc.player.block += 7;
    if (relic_has(bc, RelicId::MR_STRUGGLES)) damage_all(bc, bc.turn);
    if (relic_has(bc, RelicId::TOASTY_MITTENS)) {
        if (bc.drawCount == 0) bc.shuffle_discard_into_draw();
        if (bc.drawCount > 0) {
            Card c = bc.draw[--bc.drawCount];
            bc.move_to_exhaust(c);
        }
        bc.player.strength += 1;
    }
    if (relic_has(bc, RelicId::PAELS_LEGION) && relic_aux(bc, RelicId::PAELS_LEGION) > 0) {
        bump(bc, RelicId::PAELS_LEGION, -1);
    }
    if (relic_has(bc, RelicId::HISTORY_COURSE) && bc.turn > 1 && bc.hasLastPlayed) {
        bc.auto_play_random(bc.lastPlayedCard, false);
    }
    if (relic_has(bc, RelicId::BLOOD_VIAL) && bc.turn == 1) {
        bc.player.hp = std::min(bc.player.maxHp, bc.player.hp + 2);
    }
    if (relic_has(bc, RelicId::MERCURY_HOURGLASS)) damage_all(bc, 3);
    if (relic_has(bc, RelicId::BRIMSTONE)) {
        bc.player.strength += 2;
        for (int m = 0; m < bc.monsterCount; ++m) {
            if (bc.monsters[m].alive) bc.monsters[m].strength += 1;
        }
    }
    if (relic_has(bc, RelicId::STONE_CALENDAR) && bc.turn == 7) damage_all(bc, 52);
    if (relic_has(bc, RelicId::HORN_CLEAT) && bc.turn == 2) bc.player.block += 14;
    if (relic_has(bc, RelicId::CAPTAINS_WHEEL) && bc.turn == 3) bc.player.block = 18;
    if (relic_has(bc, RelicId::SPARKLING_ROUGE) && bc.turn == 3) {
        bc.player.strength += 1;
        bc.player.dexterity += 1;
    }
    const int clay = aux_index(bc, RelicId::SELF_FORMING_CLAY);
    if (clay >= 0 && bc.relicAux[clay] > 0) {
        bc.player.block += bc.relicAux[clay];
        bc.relicAux[clay] = 0;
    }
    set_aux(bc, RelicId::DEMON_TONGUE, 0);
    if (relic_has(bc, RelicId::RED_SKULL)) {
        const bool low = bc.player.hp * 2 <= bc.player.maxHp;
        const bool active = relic_aux(bc, RelicId::RED_SKULL) > 0;
        if (low && !active) {
            bc.player.strength += 3;
            set_aux(bc, RelicId::RED_SKULL, 1);
        } else if (!low && active) {
            bc.player.strength -= 3;
            set_aux(bc, RelicId::RED_SKULL, 0);
        }
    }
}

void relics_hand_drawn(BattleContext &bc) {
    if (relic_has(bc, RelicId::RADIANT_PEARL) && bc.turn == 1) {
        bc.add_card_to_hand(make_card(CardId::LUMINESCE, false, bc.nextUid++));
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
            for (int i = idx; i + 1 < bc.drawCount; ++i) bc.draw[i] = bc.draw[i + 1];
            --bc.drawCount;
            c.costForTurn = 0;
            bc.add_card_to_hand(c);
        }
    }
    if (relic_has(bc, RelicId::CROSSBOW)) {
        Card c = bc.random_card_of_type(CardType::ATTACK, true);
        c.costForTurn = 0;
        bc.add_card_to_hand(c);
    }
    if ((relic_has(bc, RelicId::SNECKO_EYE) || relic_has(bc, RelicId::FAKE_SNECKO_EYE))) {
        for (int i = 0; i < bc.handCount; ++i) {
            if (bc.hand[i].costForTurn >= 0) {
                bc.hand[i].costForTurn = static_cast<std::int8_t>(bc.rng.next_int(0, 3));
            }
        }
    }
    if (relic_has(bc, RelicId::CHOICES_PARADOX) && bc.turn == 1) {
        Card cards[5];
        CardId picked[5]{};
        int n = 0;
        int guard = 0;
        while (n < 3 && guard++ < 60) {
            const CardId id = bc.random_card_of_type(
                static_cast<CardType>(bc.rng.next_int(0, 2)), true).id;
            bool dup = false;
            for (int i = 0; i < n; ++i) dup = dup || picked[i] == id;
            if (dup) continue;
            picked[n] = id;
            cards[n] = make_card(id, false, bc.nextUid++);
            cards[n].costForTurn = 0;
            ++n;
        }
        Card dummy{};
        dummy.uid = 0xFFFF;
        bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, true);
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
            bc.add_random_card_to_hand(CardType::ATTACK, true);
        }
    }
    if (relic_has(bc, RelicId::TOOLBOX) && bc.turn == 1 &&
        relic_aux(bc, RelicId::TOOLBOX) == 0) {
        set_aux(bc, RelicId::TOOLBOX, 1);
        Card cards[3];
        int n = 0;
        for (int k = 0; k < 3; ++k) {
            cards[n] = bc.random_colorless_card();
            cards[n].costForTurn = 0;
            ++n;
        }
        Card dummy{};
        dummy.uid = 0xFFFF;
        bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, true);
        if (bc.pending.op != ChoiceOp::NONE) bc.pending.hasSource = false;
    }
}

void relics_card_about_to_play(BattleContext &bc, const Card &card) {
    if (!card_is_attack(card)) return;
    if (relic_has(bc, RelicId::PEN_NIB)) {
        bump(bc, RelicId::PEN_NIB, 1);
        if (relic_aux(bc, RelicId::PEN_NIB) >= 10) set_aux(bc, RelicId::PEN_NIB, 100);
    }
}

int relics_modify_damage(BattleContext &bc, int dmg, int target, const Card *card) {
    (void) target;
    int out = dmg;
    if (card != nullptr && card_is_strike(*card) && relic_has(bc, RelicId::STRIKE_DUMMY)) out += 3;
    if (card != nullptr && card->upgraded && card_is_attack(*card) &&
        relic_has(bc, RelicId::MINIATURE_CANNON)) {
        out += 3;
    }
    if (card != nullptr && card_is_attack(*card) && relic_aux(bc, RelicId::PEN_NIB) == 100) {
        out *= 2;
    }
    if (card != nullptr && card_is_attack(*card) && relic_has(bc, RelicId::THE_BOOT) &&
        out > 0 && out < 5) {
        out = 5;
    }
    return out;
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
        set_aux(bc, RelicId::SELF_FORMING_CLAY, 3);
    }
    if (relic_has(bc, RelicId::DEMON_TONGUE) && !bc.inMonsterTurn &&
        relic_aux(bc, RelicId::DEMON_TONGUE) == 0) {
        set_aux(bc, RelicId::DEMON_TONGUE, 1);
        bc.player.hp = std::min(bc.player.maxHp, bc.player.hp + amount);
    }
}

bool relics_try_revive(BattleContext &bc) {
    for (int i = 0; i < bc.relicCount; ++i) {
        if (static_cast<RelicId>(bc.relics[i]) != RelicId::LIZARD_TAIL) continue;
        for (int j = i; j + 1 < bc.relicCount; ++j) {
            bc.relics[j] = bc.relics[j + 1];
            bc.relicAux[j] = bc.relicAux[j + 1];
        }
        --bc.relicCount;
        bc.player.hp = std::max(1, bc.player.maxHp / 2);
        return true;
    }
    return false;
}

int relics_modify_block_gain(BattleContext &bc, int amount, bool fromCard) {
    if (!fromCard || amount <= 0) return amount;
    if (relic_has(bc, RelicId::VAMBRACE) && relic_aux(bc, RelicId::VAMBRACE) == 0) {
        set_aux(bc, RelicId::VAMBRACE, 1);
        return amount * 2;
    }
    if (relic_has(bc, RelicId::PAELS_LEGION) && relic_aux(bc, RelicId::PAELS_LEGION) <= 0) {
        set_aux(bc, RelicId::PAELS_LEGION, 2);
        return amount * 2;
    }
    return amount;
}

void relics_strength_gain(BattleContext &bc, int amount) {
    if (amount <= 0) return;
    if (relic_has(bc, RelicId::RUINED_HELMET) && relic_aux(bc, RelicId::RUINED_HELMET) == 0) {
        set_aux(bc, RelicId::RUINED_HELMET, 1);
        bc.player.strength += amount;
    }
}

void relics_card_played(BattleContext &bc, const Card &card) {
    if (card_is_attack(card) || card_is_skill(card)) {
        bc.lastPlayedCard = card;
        bc.hasLastPlayed = true;
    }
    if (card_is_attack(card)) {
        if (relic_has(bc, RelicId::DAUGHTER_OF_THE_WIND)) bc.player.block += 1;
        if (relic_has(bc, RelicId::MUSIC_BOX) &&
            relic_aux(bc, RelicId::MUSIC_BOX) == 0) {
            set_aux(bc, RelicId::MUSIC_BOX, 1);
            Card copy = card;
            copy.uid = bc.nextUid++;
            copy.etherealThisCombat = true;
            bc.add_card_to_hand(copy);
        }
        if (relic_has(bc, RelicId::NUNCHAKU) && bc.attacksPlayedThisCombat % 10 == 0) {
            bc.player.energy += 1;
        }
        if (bc.attacksPlayedThisTurn % 3 == 0) {
            if (relic_has(bc, RelicId::KUNAI)) bc.player.dexterity += 1;
            if (relic_has(bc, RelicId::SHURIKEN)) bc.player.strength += 1;
            if (relic_has(bc, RelicId::ORNAMENTAL_FAN)) bc.player.block += 4;
            if (relic_has(bc, RelicId::KUSARIGAMA)) bc.attack_random_monster(6);
        }
        set_aux(bc, RelicId::PEN_NIB, relic_aux(bc, RelicId::PEN_NIB) == 100 ? 0
                                                                            : relic_aux(bc, RelicId::PEN_NIB));
    }
    if (card_is_skill(card)) {
        if (relic_has(bc, RelicId::LETTER_OPENER) && bc.skillsPlayedThisTurn % 3 == 0) {
            damage_all(bc, 5);
        }
        if (relic_has(bc, RelicId::TUNING_FORK) && bc.skillsPlayedThisCombat % 10 == 0) {
            bc.player.block += 7;
        }
    }
    if (card_is_power(card)) {
        if (relic_has(bc, RelicId::PERMAFROST) && relic_aux(bc, RelicId::PERMAFROST) == 0) {
            set_aux(bc, RelicId::PERMAFROST, 1);
            bc.player.block += 6;
        }
        if (relic_has(bc, RelicId::GAME_PIECE)) bc.draw_cards(1);
        if (relic_has(bc, RelicId::LOST_WISP)) damage_all(bc, 8);
        if (relic_has(bc, RelicId::MUMMIFIED_HAND) && bc.handCount > 0) {
            const int idx = bc.rng.next_int(0, bc.handCount - 1);
            bc.hand[idx].costForTurn = 0;
        }
    }
    if (relic_has(bc, RelicId::IRON_CLUB) && bc.cardsPlayedThisCombat % 4 == 0) {
        bc.draw_cards(1);
    }
    if (relic_has(bc, RelicId::INTIMIDATING_HELMET) && card_cost(card) >= 2) {
        bc.player.block += 4;
    }
    if (relic_has(bc, RelicId::RAINBOW_RING)) {
        int flags = relic_aux(bc, RelicId::RAINBOW_RING);
        if (flags < 8) {
            if (card_is_attack(card)) flags |= 1;
            if (card_is_skill(card)) flags |= 2;
            if (card_is_power(card)) flags |= 4;
            if (flags == 7) {
                bc.player.strength += 1;
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

void relics_exhausted(BattleContext &bc, const Card &card) {
    if (relic_has(bc, RelicId::CHARONS_ASHES)) damage_all(bc, 3);
    if (relic_has(bc, RelicId::FORGOTTEN_SOUL)) bc.attack_random_monster(1);
    if (relic_has(bc, RelicId::JOSS_PAPER)) {
        bump(bc, RelicId::JOSS_PAPER, 1);
        if (relic_aux(bc, RelicId::JOSS_PAPER) % 5 == 0) bc.draw_cards(1);
    }
    if (card_is_skill(card) && relic_has(bc, RelicId::BURNING_STICKS) &&
        relic_aux(bc, RelicId::BURNING_STICKS) == 0) {
        set_aux(bc, RelicId::BURNING_STICKS, 1);
        Card copy = card;
        copy.uid = bc.nextUid++;
        bc.add_card_to_hand(copy);
    }
}

void relics_shuffled(BattleContext &bc) {
    if (relic_has(bc, RelicId::PENDULUM)) bc.draw_cards(1);
    if (relic_has(bc, RelicId::THE_ABACUS)) bc.player.block += 6;
    // Biiig Hug: after each shuffle, a Soot is added to the draw pile.
    if (relic_has(bc, RelicId::BIIIG_HUG)) add_to_draw(bc, CardId::SOOT, 1);
}

void relics_turn_end(BattleContext &bc) {
    if (relic_has(bc, RelicId::ORICHALCUM) && bc.player.block == 0) bc.player.block += 6;
    if (relic_has(bc, RelicId::FAKE_ORICHALCUM) && bc.player.block == 0) bc.player.block += 3;
    if (relic_has(bc, RelicId::DIAMOND_DIADEM) && bc.cardsPlayedThisTurn <= 2) {
        bc.player.power[static_cast<int>(PowerId::DIAMOND_DIADEM)] = 1;
    }
    if (relic_has(bc, RelicId::PAELS_TEARS)) {
        set_aux(bc, RelicId::PAELS_TEARS, bc.player.energy > 0 ? 1 : 0);
    }
    if (relic_has(bc, RelicId::RIPPLE_BASIN) && bc.attacksPlayedThisTurn == 0) {
        bc.player.block += 4;
    }
    if (relic_has(bc, RelicId::PARRYING_SHIELD) && bc.player.block >= 10) {
        bc.attack_random_monster(6);
    }
    if (relic_has(bc, RelicId::CLOAK_CLASP)) bc.player.block += bc.handCount;
    if (relic_has(bc, RelicId::SCREAMING_FLAGON) && bc.handCount == 0) {
        damage_all(bc, 20);
    }
}

void relics_after_turn(BattleContext &bc) {
    bc.attacksPlayedLastTurn = bc.attacksPlayedThisTurn;
    bc.cardsPlayedLastTurn = bc.cardsPlayedThisTurn;
    set_aux(bc, RelicId::RAINBOW_RING, 0);
}

void relics_potion_used(BattleContext &bc) {
    if (relic_has(bc, RelicId::REPTILE_TRINKET)) {
        bc.player.tempStrength += 3;
        bc.player.strength += 3;
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
    const CardDef &d = card_def(id);
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) {
        return false;
    }
    const int i = static_cast<int>(id);
    const bool is_colorless = i > static_cast<int>(CardId::WHIRLWIND) &&
                              i < static_cast<int>(CardId::BECKON);
    return colorless ? is_colorless : (i > 0 && i <= static_cast<int>(CardId::WHIRLWIND));
}

CardId pick_card(Rng &rng, Rarity want, bool colorless = false) {
    CardId pool[128];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (reward_pool_card(id, colorless) && card_def(id).rarity == want) pool[n++] = id;
    }
    if (n == 0) return CardId::STRIKE_IRONCLAD;
    return pool[rng.next_int(0, n - 1)];
}

CardId pick_card_type(Rng &rng, CardType type) {
    CardId pool[128];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (!reward_pool_card(id, false)) continue;
        if (card_def(id).type != type) continue;
        pool[n++] = id;
    }
    if (n == 0) return CardId::STRIKE_IRONCLAD;
    return pool[rng.next_int(0, n - 1)];
}

void add_deck_card(RunContext &rc, CardId id, bool upgraded = false) {
    rc.add_card_to_deck(rc.make_run_card(id, upgraded));
    ++rc.cardsAdded;
}

void add_random_deck_card(RunContext &rc, Rarity want, bool upgraded = false,
                          bool colorless = false) {
    add_deck_card(rc, pick_card(rc.runRng[RNG_NICHE], want, colorless), upgraded);
}

void upgrade_random_cards(RunContext &rc, int n) {
    int done = 0;
    for (int pass = 0; pass < 400 && done < n && rc.deckCount > 0; ++pass) {
        const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
        if (!card_upgradable(rc.deck[idx])) continue;
        rc.deck[idx].upgraded = true;
        ++done;
    }
}

void remove_random_cards(RunContext &rc, int n) {
    for (int k = 0; k < n && rc.deckCount > 0; ++k) {
        const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
        for (int i = idx; i + 1 < rc.deckCount; ++i) rc.deck[i] = rc.deck[i + 1];
        --rc.deckCount;
    }
}

void transform_random_cards(RunContext &rc, int n, bool upgrade, bool basic_only) {
    CardId pool[128];
    int pn = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type == CardType::STATUS || d.type == CardType::CURSE) continue;
        if (d.rarity == Rarity::SPECIAL || d.rarity == Rarity::BASIC) continue;
        if (d.flags & CF_MULTIPLAYER_ONLY) continue;
        pool[pn++] = static_cast<CardId>(i);
    }
    int done = 0;
    for (int pass = 0; pass < 400 && done < n && rc.deckCount > 0 && pn > 0; ++pass) {
        const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
        if (basic_only && card_def(rc.deck[idx].id).rarity != Rarity::BASIC) continue;
        const std::uint16_t uid = rc.deck[idx].uid;
        rc.deck[idx] = make_card(pool[rc.runRng[RNG_NICHE].next_int(0, pn - 1)], upgrade, uid);
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

RelicId run_random_relic(Rng &rng, const RunContext &rc) {
    int pools[4][160];
    int counts[4] = {0, 0, 0, 0};
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
        const RelicId id = static_cast<RelicId>(i);
        if (!relic_implemented(id)) continue;
        const RelicDef &d = relic_def(id);
        if (d.pool != RelicPool::SHARED && d.pool != RelicPool::IRONCLAD) continue;
        if (run_has_relic(rc, id)) continue;
        int slot = 3;
        if (d.rarity == Rarity::COMMON) slot = 0;
        else if (d.rarity == Rarity::UNCOMMON) slot = 1;
        else if (d.rarity == Rarity::RARE) slot = 2;
        if (counts[slot] < 160) pools[slot][counts[slot]++] = i;
    }
    const int weights[4] = {50, 33, 17, 8};
    int total = 0;
    for (int k = 0; k < 4; ++k) total += counts[k] > 0 ? weights[k] : 0;
    if (total <= 0) return RelicId::INVALID;
    int roll = rng.next_int(0, total - 1);
    for (int k = 0; k < 4; ++k) {
        if (counts[k] == 0) continue;
        roll -= weights[k];
        if (roll < 0) return static_cast<RelicId>(pools[k][rng.next_int(0, counts[k] - 1)]);
    }
    return RelicId::INVALID;
}

void run_gain_gold(RunContext &rc, int amount) {
    if (amount <= 0) return;
    if (run_has_relic(rc, RelicId::ECTOPLASM)) return;
    rc.gold += amount;
    if (run_has_relic(rc, RelicId::DRAGON_FRUIT)) {
        rc.maxHp += 1;
        rc.hp += 1;
    }
}

int run_energy_bonus(const RunContext &rc) {
    static const RelicId energyRelics[] = {
        RelicId::ECTOPLASM, RelicId::BLESSED_ANTLER, RelicId::BLOOD_SOAKED_ROSE,
        RelicId::PHILOSOPHERS_STONE, RelicId::PRISMATIC_GEM, RelicId::PUMPKIN_CANDLE,
        RelicId::SPIKED_GAUNTLETS, RelicId::VELVET_CHOKER, RelicId::WHISPERING_EARRING,
        RelicId::SOZU,
    };
    int bonus = 0;
    for (RelicId id : energyRelics) {
        if (run_has_relic(rc, id)) ++bonus;
    }
    return bonus;
}

int run_turn1_energy(const RunContext &rc) {
    return rc.nextCombatEnergy + (rc.teaSetPending ? 2 : 0);
}

void relics_on_obtain(RunContext &rc, RelicId id) {
    switch (id) {
        // shared / normal pool
        case RelicId::STRAWBERRY: rc.maxHp += 7; rc.hp += 7; break;
        case RelicId::PEAR: rc.maxHp += 10; rc.hp += 10; break;
        case RelicId::MANGO: rc.maxHp += 14; rc.hp += 14; break;
        case RelicId::LEES_WAFFLE: rc.maxHp += 7; rc.hp = rc.maxHp; break;
        case RelicId::OLD_COIN: run_gain_gold(rc, 300); break;
        case RelicId::POTION_BELT: rc.potionSlots = std::min(MAX_POTIONS, rc.potionSlots + 2); break;
        case RelicId::CAULDRON: fill_potions(rc); break;
        case RelicId::WAR_PAINT:
        case RelicId::WHETSTONE: {
            const CardType want = id == RelicId::WAR_PAINT ? CardType::SKILL : CardType::ATTACK;
            int done = 0;
            for (int pass = 0; pass < 400 && done < 2 && rc.deckCount > 0; ++pass) {
                const int idx = rc.runRng[RNG_NICHE].next_int(0, rc.deckCount - 1);
                if (card_def(rc.deck[idx].id).type != want || !card_upgradable(rc.deck[idx])) continue;
                rc.deck[idx].upgraded = true;
                ++done;
            }
            break;
        }

        // event / ancient relics
        case RelicId::ALCHEMICAL_COFFER:
            // +4 slots and four random potions (C# PotionSlots 4).
            rc.potionSlots = std::min(MAX_POTIONS, rc.potionSlots + 4);
            for (int i = 0; i < 4 && rc.potionCount < rc.potionSlots; ++i) {
                add_random_potion(rc);
            }
            break;
        case RelicId::ARCANE_SCROLL: add_random_deck_card(rc, Rarity::RARE); break;
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
        case RelicId::ASTROLABE: transform_random_cards(rc, 3, true, false); break;
        case RelicId::BIG_MUSHROOM: rc.maxHp += 20; rc.hp += 20; break;
        case RelicId::BIIIG_HUG: remove_random_cards(rc, 4); break;
        case RelicId::CALLING_BELL:
            for (int i = 0; i < 3; ++i) rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc));
            break;
        case RelicId::CHOSEN_CHEESE: break;  // applied at combat end
        case RelicId::CLAWS: transform_random_cards(rc, 6, false, false); break;
        case RelicId::CURSED_PEARL:
            add_deck_card(rc, CardId::GREED);
            run_gain_gold(rc, 333);
            break;
        case RelicId::DISTINGUISHED_CAPE:
            rc.maxHp = std::max(1, rc.maxHp - 9);
            rc.hp = std::min(rc.hp, rc.maxHp);
            for (int i = 0; i < 3; ++i) add_deck_card(rc, pick_card_type(rc.runRng[RNG_NICHE], CardType::SKILL));
            break;
        case RelicId::DUSTY_TOME: add_random_deck_card(rc, Rarity::RARE, true); break;
        case RelicId::EMBER_TEA: rc.emberTeaCombats = 5; break;
        case RelicId::EMPTY_CAGE: remove_random_cards(rc, 2); break;
        case RelicId::FAKE_LEES_WAFFLE: rc.hp = std::min(rc.maxHp, rc.hp + rc.maxHp / 10); break;
        case RelicId::FAKE_MANGO: rc.maxHp += 3; rc.hp += 3; break;
        case RelicId::FRAGRANT_MUSHROOM:
            rc.hp = std::max(1, rc.hp - 15);
            upgrade_random_cards(rc, 3);
            break;
        case RelicId::FUR_COAT: rc.furCoatCombats = 7; break;
        case RelicId::GLASS_EYE:
            add_random_deck_card(rc, Rarity::COMMON);
            add_random_deck_card(rc, Rarity::COMMON);
            add_random_deck_card(rc, Rarity::UNCOMMON);
            break;
        case RelicId::GOLDEN_PEARL: run_gain_gold(rc, 150); break;
        case RelicId::JEWELRY_BOX: add_random_deck_card(rc, Rarity::RARE); break;
        case RelicId::LARGE_CAPSULE:
            rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc));
            rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc));
            add_deck_card(rc, CardId::STRIKE_IRONCLAD);
            add_deck_card(rc, CardId::DEFEND_IRONCLAD);
            break;
        case RelicId::LEAD_PAPERWEIGHT: add_random_deck_card(rc, Rarity::UNCOMMON, false, true); break;
        case RelicId::LEAFY_POULTICE:
            rc.maxHp = std::max(1, rc.maxHp - 10);
            rc.hp = std::min(rc.hp, rc.maxHp);
            transform_random_cards(rc, 2, false, true);
            break;
        case RelicId::LOOMING_FRUIT: rc.maxHp += 31; rc.hp += 31; break;
        case RelicId::LOST_COFFER:
            add_random_deck_card(rc, Rarity::UNCOMMON);
            add_random_potion(rc);
            break;
        case RelicId::MASSIVE_SCROLL: add_random_deck_card(rc, Rarity::UNCOMMON, false, true); break;
        case RelicId::NEOWS_TORMENT: add_deck_card(rc, pick_card_type(rc.runRng[RNG_NICHE], CardType::ATTACK)); break;
        case RelicId::NEW_LEAF: transform_random_cards(rc, 1, false, false); break;
        case RelicId::NUTRITIOUS_OYSTER: rc.maxHp += 11; rc.hp += 11; break;
        case RelicId::PAELS_HORN:
            for (int i = 0; i < 2; ++i) add_deck_card(rc, CardId::RELAX);
            break;
        case RelicId::PANDORAS_BOX: transform_random_cards(rc, 99, false, true); break;
        case RelicId::POMANDER: upgrade_random_cards(rc, 1); break;
        case RelicId::PRECARIOUS_SHEARS:
            remove_random_cards(rc, 2);
            rc.hp = std::max(1, rc.hp - 13);
            break;
        case RelicId::PRECISE_SCISSORS: remove_random_cards(rc, 1); break;
        case RelicId::PRESERVED_FOG: remove_random_cards(rc, 5); break;
        case RelicId::SAND_CASTLE: upgrade_random_cards(rc, 6); break;
        case RelicId::SCROLL_BOXES:
            for (int i = 0; i < 3; ++i) add_random_deck_card(rc, Rarity::UNCOMMON);
            break;
        case RelicId::SEA_GLASS:
            for (int i = 0; i < 3; ++i) add_random_deck_card(rc, Rarity::UNCOMMON);
            break;
        case RelicId::SERE_TALON:
            for (int i = 0; i < 3; ++i) add_random_deck_card(rc, Rarity::RARE);
            break;
        case RelicId::SIGNET_RING: run_gain_gold(rc, 999); break;
        case RelicId::SILVER_CRUCIBLE: rc.silverCrucibleUses = 3; break;
        case RelicId::SMALL_CAPSULE: rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc)); break;
        case RelicId::STORYBOOK: add_deck_card(rc, CardId::BRIGHTEST_FLAME); break;
        case RelicId::TANXS_WHISTLE: add_random_deck_card(rc, Rarity::UNCOMMON, false, true); break;
        case RelicId::TEA_OF_DISCOURTESY: rc.nextCombatDazed = 2; break;
        case RelicId::TOUCH_OF_OROBAS: {
            for (int i = 0; i < rc.relicCount; ++i) {
                if (static_cast<RelicId>(rc.relics[i]) != RelicId::BURNING_BLOOD) continue;
                for (int j = i; j + 1 < rc.relicCount; ++j) rc.relics[j] = rc.relics[j + 1];
                --rc.relicCount;
                break;
            }
            rc.add_relic(RelicId::BLACK_BLOOD);
            break;
        }
        case RelicId::TOY_BOX:
            for (int i = 0; i < 4; ++i) rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc));
            rc.toyBoxCombats = 0;
            break;
        case RelicId::VERY_HOT_COCOA: rc.nextCombatEnergy += 4; break;
        case RelicId::WONGOS_MYSTERY_TICKET: rc.wongoCombats = 0; break;
        case RelicId::YUMMY_COOKIE: upgrade_random_cards(rc, 4); break;
        default:
            break;
    }
}

void relics_combat_end(RunContext &rc, bool victory, bool boss) {
    if (!victory) return;
    int heal = 0;
    if (run_has_relic(rc, RelicId::BLACK_BLOOD)) heal = 12;
    else if (run_has_relic(rc, RelicId::BURNING_BLOOD)) heal = 6;
    rc.hp = std::min(rc.maxHp, rc.hp + heal);
    if (run_has_relic(rc, RelicId::MEAT_ON_THE_BONE) && rc.hp * 2 <= rc.maxHp) {
        rc.hp = std::min(rc.maxHp, rc.hp + 12);
    }
    if (boss && run_has_relic(rc, RelicId::PANTOGRAPH)) {
        rc.hp = std::min(rc.maxHp, rc.hp + 25);
    }
    if (!boss && run_has_relic(rc, RelicId::AMETHYST_AUBERGINE)) {
        run_gain_gold(rc, 10);
    }
    if (run_has_relic(rc, RelicId::CHOSEN_CHEESE)) {
        rc.maxHp += 1;
        rc.hp += 1;
    }
    if (rc.wongoCombats >= 0 && run_has_relic(rc, RelicId::WONGOS_MYSTERY_TICKET)) {
        ++rc.wongoCombats;
        if (rc.wongoCombats % 5 == 0) {
            for (int i = 0; i < 3; ++i) rc.add_relic(run_random_relic(rc.runRng[RNG_NICHE], rc));
        }
    }
    if (run_has_relic(rc, RelicId::TOY_BOX)) {
        ++rc.toyBoxCombats;
        if (rc.toyBoxCombats % 3 == 0) {
            int candidates[MAX_RELICS];
            int n = 0;
            for (int i = 0; i < rc.relicCount; ++i) {
                const RelicId rid = static_cast<RelicId>(rc.relics[i]);
                if (rid == RelicId::TOY_BOX || rid == RelicId::BURNING_BLOOD ||
                    rid == RelicId::BLACK_BLOOD) continue;
                candidates[n++] = i;
            }
            if (n > 0) {
                const int drop = candidates[rc.runRng[RNG_NICHE].next_int(0, n - 1)];
                for (int j = drop; j + 1 < rc.relicCount; ++j) rc.relics[j] = rc.relics[j + 1];
                --rc.relicCount;
            }
        }
    }
}

}  // namespace sts2
