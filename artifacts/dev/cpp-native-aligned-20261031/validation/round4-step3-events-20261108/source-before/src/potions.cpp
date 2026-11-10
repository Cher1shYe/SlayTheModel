#include "sts2/battle.h"
#include "sts2/relics.h"
#include "sts2/potion_slots.h"

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

#include "sts2/native_potion_pool.inc"

struct GeneratedCardPool {
    CardId ids[192];
    int n = 0;
};

enum class CardPath { IRONCLAD, COLORLESS };

// Potion card generation uses Character.CardPool for the typed potions and the
// whole ColorlessCardPool for ColorlessPotion (no type restriction there).
void collect_cards(CardPath pool_kind, CardType type, GeneratedCardPool &pool) {
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (!card_native_available(static_cast<CardId>(i))) continue;
        const bool wanted_pool =
            pool_kind == CardPath::IRONCLAD ? d.pool == CardPool::IRONCLAD
                                            : d.pool == CardPool::COLORLESS;
        if (!wanted_pool) continue;
        if (pool_kind != CardPath::COLORLESS && d.type != type) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                       CF_CANNOT_GENERATE_IN_COMBAT)) {
            continue;
        }
        pool.ids[pool.n++] = static_cast<CardId>(i);
    }
}

int deal_cards(BattleContext &bc, Card *out, int want, CardType type, CardPath pool_kind) {
    GeneratedCardPool pool;
    collect_cards(pool_kind, type, pool);
    int n = 0;
    for (int k = 0; k < want && pool.n > 0; ++k) {
        const int idx = bc.cardGenerationRng.next_int(0, pool.n - 1);
        out[n++] = make_card(pool.ids[idx], false, bc.require_card_uid());
        pool.ids[idx] = pool.ids[--pool.n];
    }
    return n;
}

void offer(BattleContext &bc, const Card *cards, int n, bool free) {
    if (n <= 0) return;
    Card dummy{};
    dummy.uid = 0xFFFF;
    bc.start_offer(ChoiceOp::OFFER_TO_HAND, cards, n, dummy, false, free);
    if (bc.pending.op != ChoiceOp::NONE) {
        bc.pending.hasSource = false;
        // AttackPotion/SkillPotion/PowerPotion/ColorlessPotion use
        // FromChooseACardScreen(canSkip: true).
        bc.pending.optional = true;
    }
}

void hand_choice(BattleContext &bc, ChoiceOp op, int remaining, bool optional) {
    if (bc.handCount == 0) return;
    Card dummy{};
    dummy.uid = 0xFFFF;
    bc.start_choice(op, ChoicePile::HAND, remaining, optional, dummy, false);
    if (bc.pending.op != ChoiceOp::NONE) bc.pending.hasSource = false;
}

void apply_damage_all(BattleContext &bc, int amount) {
    // Potion damage is Unpowered: no strength/vulnerable modifiers.
    for (int i = 0; i < bc.monsterCount; ++i) {
        if (!bc.monsters[i].alive) continue;
        bc.damage_monster(i, amount);
    }
}

void apply_damage_one(BattleContext &bc, int target, int amount) {
    if (target < 0 || target >= bc.monsterCount || !bc.monsters[target].alive) return;
    bc.damage_monster(target, amount);
}

}  // namespace

bool BattleContext::can_use_potion(int idx) const {
    if (idx < 0 || idx >= potionSlots || !potions[idx]) return false;
    const PotionDef &d = potion_def(static_cast<PotionId>(potions[idx]));
    return d.usage != PotionUsage::AUTOMATIC;
}

void BattleContext::add_potion(PotionId id) {
    battle_try_procure_potion(*this, id);
}

// PotionFactory.CreateRandomPotionOutOfCombat: 10% rare / 25% uncommon / 65%
// common over the character + shared pools, without the combat-only filter.
PotionId random_potion_out_of_combat(Rng &rng) {
    const float roll = rng.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                        : roll <= 0.35f ? Rarity::UNCOMMON
                                        : Rarity::COMMON;
    int pool[static_cast<int>(PotionId::COUNT)];
    int n = 0;
    for (PotionId id : NATIVE_IRONCLAD_POTIONS) {
        const int i = static_cast<int>(id);
        const PotionDef &d = POTION_DEFS[i];
        if (!d.ironclad || d.rarity != want) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    return static_cast<PotionId>(pool[rng.next_int(0, n - 1)]);
}

int random_potions_out_of_combat(Rng &rng, PotionId *out, int count) {
    if (out == nullptr || count <= 0) return 0;
    bool used[static_cast<int>(PotionId::COUNT)]{};
    int made = 0;
    for (int k = 0; k < count; ++k) {
        const float roll = rng.next_float();
        const Rarity want = roll <= 0.1f ? Rarity::RARE
                            : roll <= 0.35f ? Rarity::UNCOMMON
                                            : Rarity::COMMON;
        int pool[static_cast<int>(PotionId::COUNT)];
        int n = 0;
        for (PotionId id : NATIVE_IRONCLAD_POTIONS) {
            const int i = static_cast<int>(id);
            const PotionDef &d = POTION_DEFS[i];
            if (!d.ironclad || d.rarity != want || used[i]) continue;
            pool[n++] = i;
        }
        if (n == 0) break;
        const int selected = pool[rng.next_int(0, n - 1)];
        used[selected] = true;
        out[made++] = static_cast<PotionId>(selected);
    }
    return made;
}

// PotionFactory.CreateRandomPotionInCombat: 10% rare / 25% uncommon / 65% common
// over the character + shared pools, combat-generatable potions only.
PotionId BattleContext::gain_random_combat_potion() {
    if (relic_has(*this, RelicId::SOZU)) return PotionId::INVALID;
    if (potionCount >= std::min(potionSlots, MAX_POTIONS)) return PotionId::INVALID;
    const float roll = potionRng.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                        : roll <= 0.35f ? Rarity::UNCOMMON
                                        : Rarity::COMMON;
    int pool[static_cast<int>(PotionId::COUNT)];
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
    for (int i = 0; i < potionSlots; ++i) {
        if (static_cast<PotionId>(potions[i]) != PotionId::FAIRY_IN_ABOTTLE) continue;
        potion_remove_at(potions, potionSlots, potionCount, i);
        player.hp = std::max(1, player.maxHp * 30 / 100);
        relics_current_hp_changed(*this);
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
            const int n = deal_cards(*this, cards, 3, CardType::ATTACK, CardPath::IRONCLAD);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::BLOCK_POTION:
            // CreatureCmd.GainBlock still runs block-gained hooks (Juggernaut)
            // but the amount is Unpowered (no Dexterity).
            gain_block(12, false, false);
            break;
        case PotionId::BLOOD_POTION:
            heal_hp(player.maxHp * 20 / 100);
            break;
        case PotionId::COLORLESS_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::SKILL, CardPath::COLORLESS);
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
            add_temp_strength(5);
            break;
        case PotionId::POWER_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::POWER, CardPath::IRONCLAD);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SKILL_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardType::SKILL, CardPath::IRONCLAD);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SPEED_POTION:
            add_temp_dexterity(5);
            break;
        case PotionId::STRENGTH_POTION:
            add_player_power(PowerId::STRENGTH, 2);
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
            // Clarity.cs: Draw 1 now, then ClarityPower 3 (+1 hand draw per
            // turn for the next three turns).
            draw_cards(1);
            add_player_power(PowerId::CLARITY, 3);
            break;
        case PotionId::CURE_ALL:
            player.energy += 1;
            draw_cards(2);
            break;
        case PotionId::DUPLICATOR:
            add_player_power(PowerId::DUPLICATION, 1);
            break;
        case PotionId::FORTIFIER:
            // Fortifier.cs: GainBlock(Block * 2, Unpowered) -> triple.
            gain_block(player.block * 2, false, false);
            break;
        case PotionId::FYSH_OIL:
            add_player_power(PowerId::STRENGTH, 1);
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
            if (target >= 0 && target < monsterCount && monsters[target].alive) {
                add_monster_power(target, PowerId::DEMISE, 9);
            }
            break;
        case PotionId::RADIANT_TINCTURE:
            // RadiantTincture.cs: +1 energy now and RadiancePower 3 (+1 at the
            // next three energy resets).
            player.energy += 1;
            add_player_power(PowerId::RADIANCE, 3);
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
            // PowerCmd.Apply: Artifact intercepts the Shrink debuff.
            if (target >= 0 && target < monsterCount) {
                add_monster_power(target, PowerId::SHRINK, 4);
            }
            break;
        case PotionId::BOTTLED_POTENTIAL: {
            // BottledPotential.cs: hand -> draw, shuffle, then draw 5.
            for (int i = 0; i < handCount; ++i) {
                if (drawCount < MAX_PILE) draw[drawCount++] = hand[i];
                else move_to_discard(hand[i]);
            }
            handCount = 0;
            knownTopCount = 0;  // the whole pile was just shuffled
            shuffleRng.shuffle(draw, drawCount);
            draw_cards(5);
            break;
        }
        case PotionId::COSMIC_CONCOCTION: {
            // CosmicConcoction.cs: three distinct upgraded colorless cards are
            // added to hand directly (no choice screen).
            CardId picked[3];
            int n = 0;
            for (int guard = 0; guard < 64 && n < 3; ++guard) {
                Card c = random_colorless_card();
                bool dup = false;
                for (int j = 0; j < n; ++j) dup = dup || picked[j] == c.id;
                if (dup) continue;
                picked[n++] = c.id;
                upgrade_card(c);
                add_card_to_hand(c);
            }
            break;
        }
        case PotionId::DISTILLED_CHAOS:
            auto_play_from_draw(3, false);
            break;
        case PotionId::DROPLET_OF_PRECOGNITION: {
            Card dummy{};
            dummy.uid = 0xFFFF;
            start_draw_choice(dummy, false, -1, -1);
            if (pending.op != ChoiceOp::NONE) pending.hasSource = false;
            break;
        }
        case PotionId::ENTROPIC_BREW: {
            // EntropicBrew.cs uses CreateRandomPotionOutOfCombat (CombatPotion
            // Generation RNG, no CanBeGeneratedInCombat filter) and stops when
            // TryToProcure fails (Sozu, full belt).
            while (potionCount < std::min(potionSlots, MAX_POTIONS)) {
                const PotionId next = random_potion_out_of_combat(potionRng);
                if (next == PotionId::INVALID) break;
                const int before = potionCount;
                add_potion(next);
                if (potionCount == before) break;
            }
            break;
        }
        case PotionId::FAIRY_IN_ABOTTLE:
            break;  // automatic
        case PotionId::FRUIT_JUICE:
            player.maxHp += 5;
            heal_hp(5);
            break;
        case PotionId::GHOST_IN_AJAR:
            // GhostInAJar.cs applies IntangiblePower 1, not Buffer.
            add_player_power(PowerId::INTANGIBLE, 1);
            break;
        case PotionId::GIGANTIFICATION_POTION:
            add_player_power(PowerId::GIGANTIFICATION, 1);
            break;
        case PotionId::LIQUID_MEMORIES:
            if (discardCount > 0) {
                Card dummy{};
                dummy.uid = 0xFFFF;
                start_choice(ChoiceOp::DISCARD_TO_HAND, ChoicePile::DISCARD, 1, false, dummy,
                             false, /*payload=*/1);
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
                Card c = random_card_of_type(t, false);
                card_set_turn_cost(c, 0);
                add_card_to_hand(c);
            }
            break;
        }
        case PotionId::SHACKLING_POTION:
            // ShacklingPotionPower is -7 Strength with no floor: Strength may
            // go negative and is restored at the end of the enemy turn.
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive) continue;
                apply_strength_loss(i, 7);
            }
            break;
        case PotionId::SHIP_IN_ABOTTLE:
            gain_block(10, false, false);
            add_player_power(PowerId::BLOCK_NEXT_TURN, 10);
            break;
        case PotionId::SNECKO_OIL:
            draw_cards(7);
            for (int i = 0; i < handCount; ++i) {
                // SneckoOil excludes EnergyCost.CostsX cards: they stay X-cost.
                const CardDef &d = card_def(hand[i].id);
                if ((hand[i].upgraded ? d.costUp : d.cost) < 0) continue;
                card_set_turn_cost(hand[i], energyCostRng.next_int(0, 3));
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
            // FoulPotion damages every creature; the player pays 12 even when
            // the last enemy dies.  Players precede monsters in the target
            // list, so the cost resolves first.
            damage_player(12);
            for (int i = 0; i < monsterCount; ++i) {
                if (monsters[i].alive && outcome == Outcome::UNDECIDED) {
                    damage_monster(i, 12);
                }
            }
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
    if (potion_def(id).target == PotionTarget::ANY_ENEMY) face_surrounded_target(target);
    potion_remove_at(potions, potionSlots, potionCount, idx);
    apply_potion(id, target);
    relics_potion_used(*this);
}

}  // namespace sts2
