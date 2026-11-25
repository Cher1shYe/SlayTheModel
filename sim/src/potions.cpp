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

PotionTarget potion_target(PotionId id, bool inCombat) {
    const PotionDef &d = potion_def(id);
    return inCombat ? d.combatTarget : d.target;
}

namespace {

#include "sts2/native_potion_pool.inc"

// Attack/Skill/Power potions use the character pool; ColorlessPotion the whole colorless pool.
int deal_cards(BattleContext &bc, Card *out, int want, CardPool pool, int type) {
    CardId options[static_cast<int>(CardId::COUNT)];
    const int n = bc.combat_card_options(pool, options, type);
    return bc.distinct_for_combat(options, n, want, out);
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

int hittable_enemies(const BattleContext &bc, int *out) {
    int order[MAX_MONSTERS], n = 0;
    const int total = bc.enemy_order(order);
    for (int k = 0; k < total; ++k)
        if (bc.monsters[order[k]].alive && !bc.monsters[order[k]].reviving) out[n++] = order[k];
    return n;
}

void apply_damage_all(BattleContext &bc, int amount) {
    // Potion damage is Unpowered. Targets are HittableEnemies at use time: enemies summoned
    // by a death during this damage are not hit.
    int targets[MAX_MONSTERS];
    const int n = hittable_enemies(bc, targets);
    for (int k = 0; k < n; ++k) if (bc.monsters[targets[k]].alive) bc.damage_monster(targets[k], amount);
}

void apply_damage_one(BattleContext &bc, int target, int amount) {
    if (target < 0 || target >= bc.monsterCount || !bc.monsters[target].alive) return;
    bc.damage_monster(target, amount);
}

}  // namespace

bool BattleContext::can_use_potion(int idx) const {
    if (idx < 0 || idx >= potionSlots || !potions[idx] || potion_action_queued(idx) ||
        outcome != Outcome::UNDECIDED || player.hp <= 0) return false;
    const PotionDef &d = potion_def(static_cast<PotionId>(potions[idx]));
    return d.usage == PotionUsage::ANY_TIME ||
        (d.usage == PotionUsage::COMBAT_ONLY && pending.op == ChoiceOp::NONE && !inMonsterTurn);
}

bool BattleContext::potion_action_queued(int idx) const {
    for (int i = 0; i < queuedPotionActionCount; ++i)
        if (queuedPotionActions[i].hand == idx) return true;
    return false;
}

void BattleContext::drain_potion_actions() {
    if (outcome != Outcome::UNDECIDED) { queuedPotionActionCount = 0; return; }
    while (queuedPotionActionCount && pending.op == ChoiceOp::NONE &&
           !activePlay.active && !inMonsterTurn) {
        const Action next = queuedPotionActions[0];
        for (int i = 1; i < queuedPotionActionCount; ++i)
            queuedPotionActions[i - 1] = queuedPotionActions[i];
        queuedPotionActions[--queuedPotionActionCount] = Action{};
        step_action(next);
        settle_forced_choices();
        if (outcome != Outcome::UNDECIDED) { queuedPotionActionCount = 0; break; }
    }
}

void BattleContext::add_potion(PotionId id) {
    battle_try_procure_potion(*this, id);
}

// PotionFactory.CreateRandomPotionOutOfCombat: 10% rare / 25% uncommon / 65%
// common over the character + shared pools, without the combat-only filter.
PotionId random_potion_out_of_combat(Rng &rng, std::uint64_t epochs) {
    const float roll = rng.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                        : roll <= 0.35f ? Rarity::UNCOMMON
                                        : Rarity::COMMON;
    int pool[static_cast<int>(PotionId::COUNT)];
    int n = 0;
    for (PotionId id : NATIVE_IRONCLAD_POTIONS) {
        const int i = static_cast<int>(id);
        const PotionDef &d = POTION_DEFS[i];
        if (!d.ironclad || d.rarity != want || !potion_epoch_unlocked(epochs, id)) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    return static_cast<PotionId>(pool[rng.next_int(0, n - 1)]);
}

int random_potions_out_of_combat(Rng &rng, PotionId *out, int count, std::uint64_t epochs) {
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
            if (!d.ironclad || d.rarity != want || used[i] || !potion_epoch_unlocked(epochs, id)) continue;
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
    // Alchemize: the potion is created (and the RNG consumed) before TryToProcure can fail.
    const float roll = potionRng.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                        : roll <= 0.35f ? Rarity::UNCOMMON
                                        : Rarity::COMMON;
    int pool[static_cast<int>(PotionId::COUNT)];
    int n = 0;
    for (PotionId id : NATIVE_IRONCLAD_POTIONS) {
        const int i = static_cast<int>(id);
        const PotionDef &d = POTION_DEFS[i];
        if (!d.ironclad || !d.combatGen || d.rarity != want || !potion_epoch_unlocked(revealedEpochs, id)) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    const PotionId chosen = static_cast<PotionId>(pool[potionRng.next_int(0, n - 1)]);
    if (relic_has(*this, RelicId::SOZU) || potionCount >= std::min(potionSlots, MAX_POTIONS)) return PotionId::INVALID;
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
        // AfterPreventingDeath -> OnUseWrapper: a real potion use (Hook.AfterPotionUsed:
        // Belt Buckle, Reptile Trinket).
        relics_potion_used(*this);
        return true;
    }
    return false;
}

void BattleContext::apply_potion(PotionId id, int target) {
    if (outcome != Outcome::UNDECIDED) return;
    switch (id) {
        case PotionId::AMBERGRIS:
            heal_hp(player.maxHp / 2);
            add_player_power(PowerId::AMBERGRIS, 1);
            break;
        case PotionId::ATTACK_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, characterPool, static_cast<int>(CardType::ATTACK));
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
            const int n = deal_cards(*this, cards, 3, CardPool::COLORLESS, -1);
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::DEXTERITY_POTION:
            add_player_power(PowerId::DEXTERITY, 2);
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
            player.power[static_cast<int>(PowerId::FLEX_POTION)] += 5;
            break;
        case PotionId::POWER_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, characterPool, static_cast<int>(CardType::POWER));
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SKILL_POTION: {
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, characterPool, static_cast<int>(CardType::SKILL));
            offer(*this, cards, n, true);
            break;
        }
        case PotionId::SPEED_POTION:
            add_temp_dexterity(5);
            player.power[static_cast<int>(PowerId::SPEED_POTION)] += 5;
            break;
        case PotionId::STRENGTH_POTION:
            add_player_power(PowerId::STRENGTH, 2);
            break;
        case PotionId::SWIFT_POTION:
            draw_cards(3);
            break;
        case PotionId::VULNERABLE_POTION:
            apply_vulnerable(target, 3, false);
            break;
        case PotionId::WEAK_POTION:
            apply_weak(target, 3, false);
            break;
        case PotionId::ASHWATER:
            hand_choice(*this, ChoiceOp::EXHAUST, handCount, true);
            break;
        case PotionId::BLESSING_OF_THE_FORGE:
            for (int i = 0; i < handCount; ++i) {
                if (card_upgradable(hand[i])) upgrade_card(hand[i]);   // curses and statuses stay as they are
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
            add_player_power(PowerId::DEXTERITY, 1);
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
        case PotionId::POTION_OF_BINDING: {
            int targets[MAX_MONSTERS];
            const int n = hittable_enemies(*this, targets);
            for (int k = 0; k < n; ++k) apply_weak(targets[k], 1, false);
            for (int k = 0; k < n; ++k) apply_vulnerable(targets[k], 1, false);
            break;
        }
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
            // CardPileCmd.Shuffle merges the discard pile too and runs the shuffle hooks.
            shuffle_discard_into_draw(true);
            if (pending.op != ChoiceOp::NONE) pendingDrawRemainder += 5;  // Stratagem chooses first
            else draw_cards(5);
            break;
        }
        case PotionId::COSMIC_CONCOCTION: {
            // CosmicConcoction.cs: three distinct upgraded colorless cards are
            // added to hand directly (no choice screen).
            Card cards[3];
            const int n = deal_cards(*this, cards, 3, CardPool::COLORLESS, -1);
            for (int k = 0; k < n; ++k) {
                upgrade_card(cards[k]);
                add_card_to_hand(cards[k]);
                notify_card_generated(cards[k]);
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
                const PotionId next = random_potion_out_of_combat(potionRng, revealedEpochs);
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
                Card c;
                if (deal_cards(*this, &c, 1, characterPool, static_cast<int>(t)) != 1) continue;
                card_modify_cost(c, 0, true, 2 | 4 | 8);  // SetToFreeThisTurn
                add_card_to_hand(c);
                notify_card_generated(c);
            }
            break;
        }
        case PotionId::SHACKLING_POTION:
            // ShacklingPotionPower is -7 Strength with no floor: Strength may
            // go negative and is restored at the end of the enemy turn.
        {
            int targets[MAX_MONSTERS];
            const int n = hittable_enemies(*this, targets);
            for (int k = 0; k < n; ++k) apply_strength_loss(targets[k], 7, false);
            break;
        }
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
                // EnergyCost.SetThisTurnOrUntilPlayed: expires at turn end or on play.
                card_modify_cost(hand[i], energyCostRng.next_int(0, 3), true, 2 | 4);
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
            // PlayerCombatState.AllCards also covers the exhaust pile and cards set aside.
            for (int i = 0; i < exhaustCount; ++i) {
                if (card_is_strike(exhaust[i])) ++exhaust[i].bonusReplay;
            }
            for (int i = 0; i < playCount; ++i) {
                if (card_is_strike(playPile[i])) ++playPile[i].bonusReplay;
            }
            for (int i = 0; i < returnNextTurnCount; ++i) {
                if (card_is_strike(returnNextTurn[i])) ++returnNextTurn[i].bonusReplay;
            }
            break;
        case PotionId::FOUL_POTION:
            // FoulPotion damages every creature; the player pays 12 even when
            // the last enemy dies.  Players precede monsters in the target
            // list, so the cost resolves first.
        {
            int targets[MAX_MONSTERS];
            const int n = hittable_enemies(*this, targets);
            damage_player(12);
            for (int k = 0; k < n; ++k) {
                if (monsters[targets[k]].alive && outcome == Outcome::UNDECIDED) damage_monster(targets[k], 12);
            }
            break;
        }
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
    if (player.hp > 0) relics_potion_used(*this);  // OnUseWrapper: AfterPotionUsed needs a living owner
    relics_check_empty_hand(*this);
}

}  // namespace sts2
