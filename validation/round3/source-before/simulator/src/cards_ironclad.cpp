#include "sts2/effects.h"
#include "sts2/relics.h"

namespace sts2 {

static void block_card(BattleContext &bc, Card &card) {
    int b = card_block(card);
    if (card_is_defend(card) && bc.player_power(PowerId::FASTEN) > 0) {
        b += bc.player_power(PowerId::FASTEN);
    }
    bc.gain_block(b, true);
}

static bool hit(BattleContext &bc, Card &card, int target, double base, int hits = 1) {
    return bc.attack_from_card(card, target, base, hits);
}

static void hit_all(BattleContext &bc, Card &card, double base, int hits = 1) {
    bc.attack_all_from_card(card, base, hits);
}

static void exhaust_random_from_hand(BattleContext &bc) {
    if (bc.handCount == 0) return;
    const int idx = bc.cardSelectionRng.next_int(0, bc.handCount - 1);
    Card c = bc.hand[idx];
    for (int i = idx; i + 1 < bc.handCount; ++i) bc.hand[i] = bc.hand[i + 1];
    --bc.handCount;
    bc.move_to_exhaust(c);
}

static void return_next_turn(BattleContext &bc, const Card &card) {
    bc.queue_return_next_turn(card);
}

bool ironclad_effect(BattleContext &bc, Card &card, int target) {
    const double dmg = card_base_damage(card);
    const int magic = card_var(card, VarId::POWER);

    switch (card.id) {
        case CardId::STRIKE_IRONCLAD:
            hit(bc, card, target, dmg);
            return true;
        case CardId::DEFEND_IRONCLAD:
            block_card(bc, card);
            return true;
        case CardId::ENTRENCH:
            // Entrench.cs: GainBlock(owner.Block, Unpowered | Move).
            bc.gain_block(bc.player.block, true, false);
            return true;
        case CardId::BASH:
            hit(bc, card, target, dmg);
            bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE));
            return true;

        // ---- common ----
        case CardId::ANGER: {
            hit(bc, card, target, dmg);
            // Native CreateClone preserves mutable card fields, including
            // enchantment status and cost modifiers. Only entity identity is new.
            Card copy = card;
            copy.uid = bc.require_card_uid();
            bc.add_card_to_discard(copy);
            return true;
        }
        case CardId::ARMAMENTS:
            block_card(bc, card);
            if (card.upgraded) {
                for (int i = 0; i < bc.handCount; ++i) {
                    if (!bc.hand[i].upgraded) bc.upgrade_card(bc.hand[i]);
                }
            } else if (bc.handCount > 0) {
                bc.start_choice(ChoiceOp::UPGRADE, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            }
            return true;
        case CardId::BLOOD_WALL:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            if (bc.outcome == Outcome::UNDECIDED) block_card(bc, card);
            return true;
        case CardId::BLOODLETTING:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::BODY_SLAM:
            hit(bc, card, target, bc.player.block);
            return true;
        case CardId::BREAKTHROUGH:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            if (bc.outcome == Outcome::UNDECIDED) hit_all(bc, card, dmg);
            return true;
        case CardId::CINDER:
            hit(bc, card, target, dmg);
            exhaust_random_from_hand(bc);
            return true;
        case CardId::HAVOC:
            bc.auto_play_from_draw(1, true);
            return true;
        case CardId::HEADBUTT:
            hit(bc, card, target, dmg);
            if (bc.discardCount > 0) {
                bc.start_choice(ChoiceOp::RETURN_DISCARD_TOP, ChoicePile::DISCARD, 1, false,
                                card, bc.card_will_exhaust(card));
            }
            return true;
        case CardId::IRON_WAVE:
            block_card(bc, card);
            hit(bc, card, target, dmg);
            return true;
        case CardId::MOLTEN_FIST: {
            hit(bc, card, target, dmg);
            if (target >= 0 && target < bc.monsterCount && bc.monsters[target].alive) {
                const int v = bc.monsters[target].vulnerable;
                if (v > 0) bc.apply_vulnerable(target, v);
            }
            return true;
        }
        case CardId::PERFECTED_STRIKE: {
            int strikes = 0;
            const Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount,
                                  bc.exhaustCount, bc.playCount};
            for (int p = 0; p < 5; ++p) {
                for (int i = 0; i < counts[p]; ++i) strikes += card_is_strike(piles[p][i]) ? 1 : 0;
            }
            hit(bc, card, target, card_var(card, VarId::CALC_BASE) +
                                   card_var(card, VarId::EXTRA_DAMAGE) * strikes);
            return true;
        }
        case CardId::POMMEL_STRIKE:
            hit(bc, card, target, dmg);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::SETUP_STRIKE_CARD:
            hit(bc, card, target, dmg);
            bc.add_temp_strength(card_var(card, VarId::STRENGTH));
            return true;
        case CardId::SHRUG_IT_OFF:
            block_card(bc, card);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::SWORD_BOOMERANG: {
            // Each hit rolls its own random target; damage modifiers apply once
            // per hit (the attack path already applies strength/vulnerable).
            int b = dmg;
            if (bc.player_power(PowerId::VIGOR) > 0) {
                b += bc.player_power(PowerId::VIGOR);
                bc.add_player_power(PowerId::VIGOR, -bc.player_power(PowerId::VIGOR));
            }
            for (int i = 0; i < card_var(card, VarId::REPEAT); ++i) {
                const int t = bc.random_alive_monster();
                if (t < 0) break;
                bc.damage_monster(t, bc.calc_player_damage(b, t, true, &card), true, true);
            }
            return true;
        }
        case CardId::THUNDERCLAP: {
            const int before[MAX_MONSTERS] = {};
            (void) before;
            hit_all(bc, card, dmg);
            for (int i = 0; i < bc.monsterCount; ++i) {
                if (bc.monsters[i].alive) bc.apply_vulnerable(i, card_var(card, VarId::VULNERABLE));
            }
            return true;
        }
        case CardId::TREMBLE:
            bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE));
            return true;
        case CardId::TRUE_GRIT:
            block_card(bc, card);
            if (bc.handCount == 0) return true;
            if (card.upgraded) {
                bc.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            } else {
                const int idx = bc.cardSelectionRng.next_int(0, bc.handCount - 1);
                Card c = bc.hand[idx];
                for (int i = idx; i < bc.handCount - 1; ++i) bc.hand[i] = bc.hand[i + 1];
                --bc.handCount;
                bc.move_to_exhaust(c);
            }
            return true;
        case CardId::TWIN_STRIKE:
            hit(bc, card, target, dmg, 2);
            return true;

        // ---- uncommon ----
        case CardId::ASHEN_STRIKE:
            hit(bc, card, target, card_var(card, VarId::CALC_BASE) +
                                   card_var(card, VarId::EXTRA_DAMAGE) * bc.exhaustCount);
            return true;
        case CardId::BATTLE_TRANCE:
            bc.draw_cards(card_var(card, VarId::CARDS));
            bc.add_player_power(PowerId::NO_DRAW, 1);
            return true;
        case CardId::BLUDGEON:
            hit(bc, card, target, dmg);
            return true;
        case CardId::BULLY:
            hit(bc, card, target, card_var(card, VarId::CALC_BASE) +
                                   card_var(card, VarId::EXTRA_DAMAGE) *
                                       (target >= 0 && target < bc.monsterCount
                                            ? bc.monsters[target].vulnerable : 0));
            return true;
        case CardId::BURNING_PACT:
            if (bc.handCount > 0) {
                bc.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            } else {
                bc.draw_cards(card_var(card, VarId::CARDS));
            }
            return true;
        case CardId::DEMONIC_SHIELD:
            return true;  // multiplayer-only in single player
        case CardId::DISMANTLE: {
            const bool vuln = target >= 0 && target < bc.monsterCount &&
                              bc.monsters[target].vulnerable > 0;
            hit(bc, card, target, dmg, vuln ? 2 : 1);
            return true;
        }
        case CardId::DOMINATE: {
            const int vuln = target >= 0 && target < bc.monsterCount
                                 ? bc.monsters[target].vulnerable : 0;
            if (vuln > 0) bc.add_player_power(PowerId::STRENGTH,
                                              card_var(card, VarId::STRENGTH_PER_VULNERABLE) * vuln);
            return true;
        }
        case CardId::DRUM_OF_BATTLE_CARD:
            bc.draw_cards(card_var(card, VarId::CARDS));
            bc.add_player_power(PowerId::DRUM_OF_BATTLE, 1);
            return true;
        case CardId::EVIL_EYE:
            block_card(bc, card);
            if (bc.exhaustedThisTurn > 0) block_card(bc, card);
            return true;
        case CardId::EXPECT_A_FIGHT: {
            bc.gain_block(card_var(card, VarId::CALC_BASE) +
                          card_var(card, VarId::CALC_EXTRA) * std::max(0, bc.player.strength), true);
            return true;
        }
        case CardId::FEEL_NO_PAIN_CARD:
            bc.add_player_power(PowerId::FEEL_NO_PAIN, magic);
            return true;
        case CardId::FIGHT_ME:
            hit(bc, card, target, dmg, 2);
            bc.add_player_power(PowerId::STRENGTH, card_var(card, VarId::STRENGTH));
            if (target >= 0 && target < bc.monsterCount && bc.monsters[target].alive) {
                bc.add_monster_power(target, PowerId::STRENGTH, card_var(card, VarId::ENEMY_STRENGTH));
            }
            return true;
        case CardId::FLAME_BARRIER_CARD:
            block_card(bc, card);
            bc.add_player_power(PowerId::FLAME_BARRIER, card_var(card, VarId::DAMAGE_BACK));
            return true;
        case CardId::FORGOTTEN_RITUAL:
            if (bc.exhaustedThisTurn > 0) bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::GRAPPLE:
            hit(bc, card, target, dmg);
            if (target >= 0 && target < bc.monsterCount) {
                bc.add_monster_power(target, PowerId::GRAPPLE, card_var(card, VarId::GRAPPLE_POWER));
            }
            return true;
        case CardId::HEMOKINESIS:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            if (bc.outcome == Outcome::UNDECIDED) hit(bc, card, target, dmg);
            return true;
        case CardId::HOWL_FROM_BEYOND:
            hit_all(bc, card, dmg);
            return true;
        case CardId::INFERNAL_BLADE:
            bc.add_random_card_to_hand(CardType::ATTACK, true);
            return true;
        case CardId::INFERNO_CARD:
            bc.add_player_power(PowerId::INFERNO, card_var(card, VarId::INFERNO_POWER));
            return true;
        case CardId::INFLAME:
            bc.add_player_power(PowerId::STRENGTH, card_var(card, VarId::STRENGTH));
            return true;
        case CardId::JUGGLING_CARD:
            bc.add_player_power(PowerId::JUGGLING, 1);
            return true;
        case CardId::PILLAGE:
            hit(bc, card, target, dmg);
            while (bc.handCount < MAX_HAND) {
                const int before = bc.handCount;
                bc.draw_cards(1);
                if (bc.handCount == before) break;
                if (!card_is_attack(bc.hand[bc.handCount - 1])) break;
            }
            return true;
        case CardId::RAGE_CARD:
            bc.add_player_power(PowerId::RAGE, magic);
            return true;
        case CardId::RAMPAGE:
            hit(bc, card, target, dmg);
            card.bonusDamage += card_var(card, VarId::INCREASE);
            return true;
        case CardId::RUPTURE_CARD:
            bc.add_player_power(PowerId::RUPTURE, card_var(card, VarId::STRENGTH));
            return true;
        case CardId::SECOND_WIND: {
            const int per = card_var(card, VarId::BLOCK);
            for (int i = bc.handCount - 1; i >= 0; --i) {
                if (!card_is_attack(bc.hand[i])) {
                    Card c = bc.hand[i];
                    for (int j = i; j < bc.handCount - 1; ++j) bc.hand[j] = bc.hand[j + 1];
                    --bc.handCount;
                    bc.move_to_exhaust(c);
                    // SecondWind.cs: BlockVar with cardPlay ("Move"), i.e.
                    // powered block from a card: NoBlock must stop it.
                    bc.gain_block(per, true);
                }
            }
            return true;
        }
        case CardId::SPITE:
            hit(bc, card, target, dmg);
            if (bc.player.tookUnblockedDamageThisTurn) bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::STAMPEDE_CARD:
            bc.add_player_power(PowerId::STAMPEDE, 1);
            return true;
        case CardId::STOMP:
            hit_all(bc, card, dmg);
            return true;
        case CardId::STONE_ARMOR:
            bc.add_player_power(PowerId::PLATING, card_var(card, VarId::PLATING));
            return true;
        case CardId::TAUNT:
            block_card(bc, card);
            bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE));
            return true;
        case CardId::UNRELENTING:
            hit(bc, card, target, dmg);
            bc.add_player_power(PowerId::FREE_ATTACK, 1);
            return true;
        case CardId::UPPERCUT:
            hit(bc, card, target, dmg);
            bc.apply_weak(target, magic);
            bc.apply_vulnerable(target, magic);
            return true;
        case CardId::VICIOUS_CARD:
            bc.add_player_power(PowerId::VICIOUS, card_var(card, VarId::CARDS));
            return true;
        case CardId::WHIRLWIND:
            // Whirlwind.cs builds one WithHitCount(X) AttackCommand, so Vigor
            // applies once for the whole command, not once per hit.
            if (bc.xCost > 0) hit_all(bc, card, dmg, bc.xCost);
            return true;

        // ---- rare ----
        case CardId::AGGRESSION_CARD:
            bc.add_player_power(PowerId::AGGRESSION, 1);
            return true;
        case CardId::BARRICADE_CARD:
            bc.add_player_power(PowerId::BARRICADE, 1);
            return true;
        case CardId::BRAND:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            if (bc.outcome != Outcome::UNDECIDED) return true;
            if (bc.handCount == 0) {
                bc.add_player_power(PowerId::STRENGTH, card_var(card, VarId::STRENGTH));
            } else {
                bc.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            }
            return true;
        case CardId::CASCADE: {
            int count = bc.xCost;
            if (card.upgraded) ++count;
            bc.auto_play_from_draw(count, false);
            return true;
        }
        case CardId::COLOSSUS_CARD:
            block_card(bc, card);
            bc.add_player_power(PowerId::COLOSSUS, card_var(card, VarId::COLOSSUS));
            return true;
        case CardId::CONFLAGRATION:
            hit_all(bc, card, card_var(card, VarId::CALC_BASE) +
                                card_var(card, VarId::EXTRA_DAMAGE) * bc.attacksPlayedThisTurn);
            return true;
        case CardId::CRIMSON_MANTLE:
            bc.add_player_power(PowerId::CRIMSON_MANTLE, card_var(card, VarId::CRIMSON_MANTLE_POWER));
            return true;
        case CardId::CRUELTY_CARD:
            bc.add_player_power(PowerId::CRUELTY, card_var(card, VarId::CRUELTY_POWER));
            return true;
        case CardId::DARK_EMBRACE_CARD:
            bc.add_player_power(PowerId::DARK_EMBRACE, 1);
            return true;
        case CardId::DEMON_FORM_CARD:
            bc.add_player_power(PowerId::DEMON_FORM, card_var(card, VarId::STRENGTH));
            return true;
        case CardId::FEED: {
            const bool fatal_eligible = bc.can_trigger_fatal(target);
            const bool killed = hit(bc, card, target, dmg);
            if (fatal_eligible && killed) {
                bc.player.maxHp += card_var(card, VarId::MAX_HP);
                bc.player.hp += card_var(card, VarId::MAX_HP);
            }
            return true;
        }
        case CardId::FIEND_FIRE: {
            // FiendFire.cs: snapshot Hand.Cards.ToList() first, then exhaust
            // exactly those cards.  Cards drawn by exhaust hooks (Dark Embrace)
            // stay in hand and are never part of this snapshot.
            Card snapshot[MAX_HAND];
            int count = 0;
            for (int i = 0; i < bc.handCount; ++i) snapshot[count++] = bc.hand[i];
            for (int i = 0; i < count; ++i) {
                for (int j = 0; j < bc.handCount; ++j) {
                    if (bc.hand[j].uid != snapshot[i].uid) continue;
                    Card c = bc.hand[j];
                    for (int k = j; k + 1 < bc.handCount; ++k) bc.hand[k] = bc.hand[k + 1];
                    --bc.handCount;
                    bc.move_to_exhaust(c);
                    break;
                }
                if (bc.outcome != Outcome::UNDECIDED) break;
            }
            // One AttackCommand with HitCount(cardCount): Vigor applies once.
            if (count > 0 && bc.outcome == Outcome::UNDECIDED) {
                hit(bc, card, target, dmg, count);
            }
            return true;
        }
        case CardId::HELLRAISER_CARD:
            bc.add_player_power(PowerId::HELLRAISER, 1);
            return true;
        case CardId::IMPERVIOUS:
            block_card(bc, card);
            return true;
        case CardId::JUGGERNAUT_CARD:
            bc.add_player_power(PowerId::JUGGERNAUT, card_var(card, VarId::JUGGERNAUT_POWER));
            return true;
        case CardId::MANGLE:
            hit(bc, card, target, dmg);
            if (target >= 0 && target < bc.monsterCount && bc.monsters[target].alive) {
                // ManglePower: temporary strength loss, restored at the end of
                // the affected monster's turn.  Store the amount to give back.
                bc.apply_strength_loss(target, card_var(card, VarId::STRENGTH_LOSS));
            }
            return true;
        case CardId::OFFERING:
            bc.damage_player(card_var(card, VarId::HP_LOSS), true);
            bc.player.energy += card_var(card, VarId::ENERGY);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::ONE_TWO_PUNCH_CARD:
            bc.add_player_power(PowerId::ONE_TWO_PUNCH, card_var(card, VarId::ATTACKS));
            return true;
        case CardId::PACTS_END:
            hit_all(bc, card, dmg);
            return true;
        case CardId::PRIMAL_FORCE: {
            for (int i = 0; i < bc.handCount; ++i) {
                if (card_is_attack(bc.hand[i])) {
                    const std::uint16_t uid = bc.hand[i].uid;
                    bc.hand[i] = make_card(CardId::GIANT_ROCK, card.upgraded, uid);
                }
            }
            return true;
        }
        case CardId::PYRE:
            bc.add_player_power(PowerId::PYRE, card_var(card, VarId::ENERGY));
            return true;
        case CardId::STOKE: {
            const int count = bc.handCount;
            // Exhaust the hand that existed at play time. Exhaust hooks can
            // draw or generate new cards, which must not join this effect.
            std::uint16_t initial[MAX_HAND];
            for (int i = 0; i < count; ++i) initial[i] = bc.hand[i].uid;
            for (int i = 0; i < count && bc.outcome == Outcome::UNDECIDED; ++i) {
                for (int j = 0; j < bc.handCount; ++j) {
                    if (bc.hand[j].uid != initial[i]) continue;
                    Card c = bc.hand[j];
                    for (int k = j; k + 1 < bc.handCount; ++k) bc.hand[k] = bc.hand[k + 1];
                    --bc.handCount;
                    bc.move_to_exhaust(c);
                    break;
                }
            }
            if (bc.outcome == Outcome::UNDECIDED) {
                Card generated[MAX_HAND];
                for (int i = 0; i < count; ++i) {
                    generated[i] = bc.random_character_card_excluding(nullptr, 0);
                    if (card.upgraded) bc.upgrade_card(generated[i]);
                }
                for (int i = 0; i < count; ++i) bc.add_card_to_hand(generated[i]);
            }
            return true;
        }
        case CardId::TANK_CARD:
            return true;  // multiplayer-only in single player
        case CardId::TEAR_ASUNDER: {
            const int hits = 1 + bc.unblockedHitsThisCombat;
            hit(bc, card, target, dmg, hits);
            return true;
        }
        case CardId::THRASH: {
            hit(bc, card, target, dmg, 2);
            int attacks[MAX_HAND];
            int count = 0;
            for (int i = 0; i < bc.handCount; ++i) {
                if (card_is_attack(bc.hand[i])) attacks[count++] = i;
            }
            if (count > 0) {
                const int idx = attacks[bc.cardSelectionRng.next_int(0, count - 1)];
                Card c = bc.hand[idx];
                // Calculate while c is still in Hand and before exhaust hooks.
                const double growth = bc.thrash_damage_growth(c);
                card.bonusDamage += growth;
                for (int i = idx; i < bc.handCount - 1; ++i) bc.hand[i] = bc.hand[i + 1];
                --bc.handCount;
                bc.move_to_exhaust(c);
            }
            return true;
        }
        case CardId::UNMOVABLE:
            bc.add_player_power(PowerId::UNMOVABLE, 1);
            return true;
        case CardId::BREAK:
            hit(bc, card, target, dmg);
            bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE));
            return true;
        case CardId::CORRUPTION_CARD:
            bc.add_player_power(PowerId::CORRUPTION, 1);
            return true;

        default:
            return false;
    }
}

}  // namespace sts2
