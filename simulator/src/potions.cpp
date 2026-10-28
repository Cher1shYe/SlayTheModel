#include "sts2/battle.h"
#include "sts2/relics.h"

namespace sts2 {
#include "sts2/cards_generated.inc"
#include "sts2/potions_generated.inc"

const PotionDef &potion_def(PotionId id) {
    const int i = static_cast<int>(id);
    if (i <= 0 || i >= static_cast<int>(PotionId::COUNT)) return POTION_DEFS[0];
    return POTION_DEFS[i];
}

const char *potion_name(PotionId id) {
    const PotionDef &d = potion_def(id);
    return d.name ? d.name : "Unknown";
}

namespace {

struct CardPool {
    CardId ids[192];
    int n = 0;
};

void collect_type(BattleContext &bc, CardType type, CardPool &pool, bool colorless_only = false) {
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.type != type) continue;
        if (d.rarity == Rarity::SPECIAL || d.rarity == Rarity::BASIC) continue;
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        const bool colorless = i > static_cast<int>(CardId::WHIRLWIND) &&
                               i < static_cast<int>(CardId::BECKON);
        if (colorless_only && !colorless) continue;
        pool.ids[pool.n++] = static_cast<CardId>(i);
    }
    (void) bc;
}

int deal_cards(BattleContext &bc, Card *out, int want, CardType type, bool colorless_only) {
    CardPool pool;
    collect_type(bc, type, pool, colorless_only);
    int n = 0;
    for (int k = 0; k < want && pool.n > 0; ++k) {
        const int idx = bc.rng.next_int(0, pool.n - 1);
        out[n++] = make_card(pool.ids[idx], false, bc.nextUid++);
        pool.ids[idx] = pool.ids[--pool.n];
    }
    return n;
}

void offer(BattleContext &bc, const Card *cards, int n, bool free) {
    if (n <= 0) return;
    Card dummy{};
    dummy.uid = 0xFFFF;
    bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, free);
    if (bc.pending.op != ChoiceOp::NONE) bc.pending.hasSource = false;
}

void hand_choice(BattleContext &bc, ChoiceOp op, int remaining, bool optional) {
    if (bc.handCount == 0) return;
    Card dummy{};
    dummy.uid = 0xFFFF;
    bc.start_choice(op, ChoicePile::HAND, remaining, optional, dummy, false);
    if (bc.pending.op != ChoiceOp::NONE) bc.pending.hasSource = false;
}

void apply_damage_all(BattleContext &bc, int amount) {
    for (int i = 0; i < bc.monsterCount; ++i) {
        if (!bc.monsters[i].alive) continue;
        int dmg = amount;
        if (bc.monsters[i].vulnerable > 0) dmg = dmg * 3 / 2;
        bc.damage_monster(i, dmg);
    }
}

void apply_damage_one(BattleContext &bc, int target, int amount) {
    if (target < 0 || target >= bc.monsterCount || !bc.monsters[target].alive) return;
    bc.damage_monster(target, amount);
}

}  // namespace

bool BattleContext::can_use_potion(int idx) const {
    if (idx < 0 || idx >= potionCount) return false;
    const PotionDef &d = potion_def(static_cast<PotionId>(potions[idx]));
    return d.usage != PotionUsage::AUTOMATIC;
}

void BattleContext::add_potion(PotionId id) {
    if (potionCount >= std::min(potionSlots, MAX_POTIONS)) return;
    potions[potionCount++] = static_cast<int>(id);
}

// PotionFactory.CreateRandomPotionInCombat: 10% rare / 25% uncommon / 65% common
// over the character + shared pools, combat-generatable potions only.
PotionId BattleContext::gain_random_combat_potion() {
    if (potionCount >= std::min(potionSlots, MAX_POTIONS)) return PotionId::INVALID;
    const float roll = potionRng.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                        : roll <= 0.35f ? Rarity::UNCOMMON
                                        : Rarity::COMMON;
    int pool[64];
    int n = 0;
    for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
        const PotionDef &d = POTION_DEFS[i];
        if (!d.ironclad || !d.combatGen || d.rarity != want) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    const PotionId chosen = static_cast<PotionId>(pool[potionRng.next_int(0, n - 1)]);
    add_potion(chosen);
    return chosen;
}

bool BattleContext::try_fairy_revive() {
    for (int i = 0; i < potionCount; ++i) {
        if (static_cast<PotionId>(potions[i]) != PotionId::FAIRY_IN_ABOTTLE) continue;
        for (int j = i; j + 1 < potionCount; ++j) potions[j] = potions[j + 1];
        --potionCount;
        player.hp = std::max(1, player.maxHp * 30 / 100);
        outcome = Outcome::UNDECIDED;
        return true;
    }
    return false;
}

void BattleContext::apply_potion(PotionId id, int target) {
    if (outcome != Outcome::UNDECIDED) return;
    switch (id) {
        case PotionId::ATTACK_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::ATTACK, false);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::BLOCK_POTION:
            player.block += 12;
            break;
        case PotionId::BLOOD_POTION:
            player.hp = std::min(player.maxHp, player.hp + player.maxHp * 20 / 100);
            break;
        case PotionId::COLORLESS_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::SKILL, true);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::DEXTERITY_POTION:
            player.dexterity += 2;
            break;
        case PotionId::ENERGY_POTION:
            player.energy += 2;
            break;
        case PotionId::EXPLOSIVE_AMPOULE:
            apply_damage_all(*this, 10);
            break;
        case PotionId::FIRE_POTION:
            apply_damage_one(*this, target, 20);
            break;
        case PotionId::FLEX_POTION:
            player.tempStrength += 5;
            player.strength += 5;
            break;
        case PotionId::POWER_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::POWER, false);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SKILL_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::SKILL, false);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SPEED_POTION:
            player.tempDexterity += 5;
            player.dexterity += 5;
            break;
        case PotionId::STRENGTH_POTION:
            player.strength += 2;
            break;
        case PotionId::SWIFT_POTION:
            draw_cards(3);
            break;
        case PotionId::VULNERABLE_POTION:
            apply_vulnerable(target, 3);
            break;
        case PotionId::WEAK_POTION:
            apply_weak(target, 3);
            break;
        case PotionId::ASHWATER:
            hand_choice(*this, ChoiceOp::EXHAUST, handCount, true);
            break;
        case PotionId::BLESSING_OF_THE_FORGE:
            for (int i = 0; i < handCount; ++i) {
                if (!hand[i].upgraded) upgrade_card(hand[i]);
            }
            break;
        case PotionId::CLARITY:
            draw_cards(1);
            break;
        case PotionId::CURE_ALL:
            player.energy += 1;
            draw_cards(2);
            break;
        case PotionId::DUPLICATOR:
            add_player_power(PowerId::DUPLICATION, 1);
            break;
        case PotionId::FORTIFIER:
            player.block *= 2;
            break;
        case PotionId::FYSH_OIL:
            player.strength += 1;
            player.dexterity += 1;
            break;
        case PotionId::GAMBLERS_BREW: {
            hand_choice(*this, ChoiceOp::DISCARD_ANY, handCount, true);
            break;
        }
        case PotionId::HEART_OF_IRON:
            add_player_power(PowerId::PLATING, 7);
            break;
        case PotionId::LIQUID_BRONZE:
            add_player_power(PowerId::THORNS, 3);
            break;
        case PotionId::POTION_OF_BINDING:
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive) continue;
                apply_weak(i, 1);
                apply_vulnerable(i, 1);
            }
            break;
        case PotionId::POWDERED_DEMISE:
            apply_damage_one(*this, target, 9);  // ponytail: immediate damage, no delayed power
            break;
        case PotionId::RADIANT_TINCTURE:
            player.energy += 1;
            break;
        case PotionId::REGEN_POTION:
            add_player_power(PowerId::REGEN, 5);
            break;
        case PotionId::STABLE_SERUM:
            add_player_power(PowerId::RETAIN_HAND, 2);
            break;
        case PotionId::TOUCH_OF_INSANITY:
            hand_choice(*this, ChoiceOp::MAKE_FREE, 1, false);
            break;
        case PotionId::BEETLE_JUICE:
            if (target >= 0 && target < monsterCount) {
                monsters[target].power[static_cast<int>(PowerId::SHRINK)] += 4;
            }
            break;
        case PotionId::BOTTLED_POTENTIAL:
            rng.shuffle(draw, drawCount);
            draw_cards(5);
            break;
        case PotionId::COSMIC_CONCOCTION: {
            Card cards[3];
            for (int i = 0; i < 3; ++i) cards[i] = random_colorless_card();
            for (int i = 0; i < 3; ++i) upgrade_card(cards[i]);
            offer(*this, cards, 3, true);
            break;
        }
        case PotionId::DISTILLED_CHAOS:
            for (int i = 0; i < 3 && drawCount > 0 && outcome == Outcome::UNDECIDED; ++i) {
                Card c = draw[--drawCount];
                auto_play_random(c, false);
            }
            break;
        case PotionId::DROPLET_OF_PRECOGNITION: {
            Card dummy{};
            dummy.uid = 0xFFFF;
            start_draw_choice(dummy, false, -1, -1, 3);
            if (pending.op != ChoiceOp::NONE) pending.hasSource = false;
            break;
        }
        case PotionId::ENTROPIC_BREW: {
            CardPool pool;
            for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
                const PotionDef &d = POTION_DEFS[i];
                if (!d.ironclad || !d.combatGen) continue;
                pool.ids[pool.n++] = static_cast<CardId>(i);
            }
            while (potionCount < std::min(potionSlots, MAX_POTIONS) && pool.n > 0) {
                const int k = rng.next_int(0, pool.n - 1);
                potions[potionCount++] = static_cast<int>(pool.ids[k]);
            }
            break;
        }
        case PotionId::FAIRY_IN_ABOTTLE:
            break;  // automatic
        case PotionId::FRUIT_JUICE:
            player.maxHp += 5;
            player.hp += 5;
            break;
        case PotionId::GHOST_IN_AJAR:
            add_player_power(PowerId::BUFFER, 1);
            break;
        case PotionId::GIGANTIFICATION_POTION:
            add_player_power(PowerId::GIGANTIFICATION, 1);
            break;
        case PotionId::LIQUID_MEMORIES:
            if (discardCount > 0) {
                Card dummy{};
                dummy.uid = 0xFFFF;
                start_choice(ChoiceOp::DISCARD_TO_HAND, ChoicePile::DISCARD, 1, false, dummy, false);
                if (pending.op != ChoiceOp::NONE) pending.hasSource = false;
            }
            break;
        case PotionId::LUCKY_TONIC:
            add_player_power(PowerId::BUFFER, 1);
            break;
        case PotionId::MAZALETHS_GIFT:
            add_player_power(PowerId::RITUAL, 1);
            break;
        case PotionId::OROBIC_ACID: {
            const CardType types[3] = {CardType::ATTACK, CardType::SKILL, CardType::POWER};
            for (CardType t : types) {
                Card c = random_card_of_type(t, true);
                c.costForTurn = 0;
                add_card_to_hand(c);
            }
            break;
        }
        case PotionId::SHACKLING_POTION:
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive || monsters[i].strength <= 0) continue;
                const int loss = std::min(monsters[i].strength, 7);
                monsters[i].strength -= loss;
                monsters[i].tempStrengthLoss += loss;
            }
            break;
        case PotionId::SHIP_IN_ABOTTLE:
            player.block += 10;
            add_player_power(PowerId::BLOCK_NEXT_TURN, 10);
            break;
        case PotionId::SNECKO_OIL:
            draw_cards(7);
            for (int i = 0; i < handCount; ++i) {
                hand[i].costForTurn = static_cast<std::int8_t>(rng.next_int(0, 3));
            }
            break;
        case PotionId::SOLDIERS_STEW:
            for (int i = 0; i < handCount; ++i) {
                if (card_is_strike(hand[i])) ++hand[i].bonusReplay;
            }
            for (int i = 0; i < drawCount; ++i) {
                if (card_is_strike(draw[i])) ++draw[i].bonusReplay;
            }
            for (int i = 0; i < discardCount; ++i) {
                if (card_is_strike(discard[i])) ++discard[i].bonusReplay;
            }
            break;
        case PotionId::FOUL_POTION:
            for (int i = 0; i < monsterCount; ++i) {
                if (monsters[i].alive) damage_monster(i, 12);
            }
            damage_player(12, true);
            break;
        case PotionId::GLOWWATER_POTION: {
            Card held[MAX_HAND];
            const int n = handCount;
            for (int i = 0; i < n; ++i) held[i] = hand[i];
            handCount = 0;
            for (int i = 0; i < n; ++i) move_to_exhaust(held[i]);
            draw_cards(10);
            break;
        }
        case PotionId::POTION_SHAPED_ROCK:
            apply_damage_one(*this, target, 15);
            break;
        default:
            break;
    }
    check_outcome();
}

void BattleContext::use_potion(int idx, int target) {
    if (!can_use_potion(idx)) return;
    const PotionId id = static_cast<PotionId>(potions[idx]);
    for (int j = idx; j + 1 < potionCount; ++j) potions[j] = potions[j + 1];
    --potionCount;
    apply_potion(id, target);
    relics_potion_used(*this);
}

}  // namespace sts2
