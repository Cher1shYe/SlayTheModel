#include "sts2/card_candidates.h"
#include "sts2/card_preview.h"
#include "sts2/effects.h"
#include "sts2/monsters.h"

namespace sts2 {
#include "sts2/cards_generated.inc"

namespace {

void random_ironclad_cards(BattleContext &bc, int count, bool upgraded, Card *out, int &outN) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    const int n = bc.combat_card_options(bc.characterPool, pool);
    outN = bc.distinct_for_combat(pool, n, count, out);
    if (upgraded) for (int k = 0; k < outN; ++k) bc.upgrade_card(out[k]);
}

void add_from_draw(BattleContext &bc, int idx) {
    Card c = bc.draw[idx];
    bc.remove_draw_at(idx);
    bc.add_card_to_hand(c);
}

void random_draw_auto_play(BattleContext &bc, int count) {
    for (int k = 0; k < count && bc.drawCount > 0 && bc.outcome == Outcome::UNDECIDED; ++k) {
        // Catastrophe prefers playable cards and stable-shuffles candidates on
        // the Shuffle stream, separately for every auto-play.
        int candidates[MAX_PILE];
        int n = 0;
        for (int i = bc.drawCount - 1; i >= 0; --i)   // native pile order: top first
            if (!card_has(bc.draw[i], CF_UNPLAYABLE)) candidates[n++] = i;
        if (n == 0)
            for (int i = bc.drawCount - 1; i >= 0; --i) candidates[n++] = i;
        native_sort_card_indices(bc.draw, candidates, n);
        bc.shuffleRng.shuffle(candidates, n);
        const int idx = candidates[0];
        Card c = bc.draw[idx];
        bc.remove_draw_at(idx);
        bc.auto_play_random(c, false);
    }
}

// Jackpot: character cards whose canonical cost is exactly 0 (X costs are negative here).
int zero_cost_pool(const BattleContext &bc, CardId *out) {
    CardId options[static_cast<int>(CardId::COUNT)];
    const int n = bc.combat_card_options(bc.characterPool, options);
    int kept = 0;
    for (int i = 0; i < n; ++i) if (card_def(options[i]).cost == 0) out[kept++] = options[i];
    return kept;
}

}  // namespace

// Shared with card_preview.cpp (Rend's CalculatedDamage preview); logic unchanged.
int rend_debuff_count(const Monster &m) {
    int n = 0;
    if (m.vulnerable > 0) ++n;
    if (m.weak > 0) ++n;
    if (m.strength < 0) ++n;
    // Rend counts native TypeForCurrentAmount == Debuff, excluding temporary
    // wrapper powers. Mangle/Dark Shackles can still contribute through the
    // resulting negative StrengthPower, which is a separate debuff.
    constexpr PowerId debuffs[] = {
        PowerId::POISON, PowerId::KNOCKDOWN, PowerId::SHRINK, PowerId::SLOW,
        PowerId::FRAIL, PowerId::NO_DRAW, PowerId::NO_BLOCK, PowerId::THE_GAMBIT,
        PowerId::DEMISE, PowerId::TANGLED, PowerId::SURROUNDED,
        PowerId::CHAINS_OF_BINDING, PowerId::DAMPEN, PowerId::PLOW,
        PowerId::HEX, PowerId::RINGING, PowerId::TENDER, PowerId::SMOGGY,
        PowerId::CONSTRICT, PowerId::SHRIEK, PowerId::IMBALANCED
    };
    for (PowerId id : debuffs) if (m.power[static_cast<int>(id)] != 0) ++n;
    return n;
}

bool colorless_effect(BattleContext &bc, Card &card, int target) {
    const double dmg = card_base_damage(card);

    switch (card.id) {
        case CardId::ABUNDANCE: {
            CardId pool[static_cast<int>(CardId::COUNT)];
            const int n = bc.combat_card_options(bc.characterPool, pool, static_cast<int>(CardType::POWER));
            Card offers[3];
            const int count = bc.distinct_for_combat(pool, n, 3, offers);
            for (int i = 0; i < count; ++i) bc.upgrade_card(offers[i]);
            if (count) {
                bc.start_offer(ChoiceOp::OFFER_TO_HAND, offers, count, card,
                               bc.card_will_exhaust(card), true);
                bc.pending.optional = false;  // native default canSkip=false
            }
            return true;
        }
        // ---- uncommon ----
        case CardId::AUTOMATION:
            bc.add_player_power(PowerId::AUTOMATION, 1,true);
            return true;
        case CardId::BELIEVE_IN_YOU:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::CATASTROPHE:
            random_draw_auto_play(bc, card_var(card, VarId::CARDS));
            return true;
        case CardId::COORDINATE_CARD:
            bc.add_player_power(PowerId::COORDINATE, card_var(card, VarId::STRENGTH),true);
            return true;
        case CardId::DARK_SHACKLES: {
            if (target < 0 || target >= bc.monsterCount) return true;
            // DarkShacklesPower (TemporaryStrengthPower, negative): a visible
            // debuff (Artifact blocks it entirely) that lowers Strength until
            // the enemy side's turn ends.
            const int before = bc.monster_power(target, PowerId::DARK_SHACKLES);
            bc.add_monster_power(target, PowerId::DARK_SHACKLES, card_var(card, VarId::STRENGTH_LOSS),true);
            const int applied = bc.monster_power(target, PowerId::DARK_SHACKLES) - before;
            if (applied) bc.add_monster_power(target, PowerId::STRENGTH, -applied,true);
            return true;
        }
        case CardId::DISCOVERY: {
            Card offers[MAX_HAND];
            int n = 0;
            random_ironclad_cards(bc, 3, false, offers, n);
            if (n == 0) return true;
            bc.start_offer(ChoiceOp::OFFER_TO_HAND, offers, n, card, bc.card_will_exhaust(card), true);
            bc.pending.optional = true;
            return true;
        }
        case CardId::EQUILIBRIUM:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::RETAIN_HAND, 1,true);
            return true;
        case CardId::FASTEN:
            bc.add_player_power(PowerId::FASTEN, card_var(card, VarId::EXTRA_BLOCK),true);
            return true;
        case CardId::FINESSE:
            bc.gain_block(card_block(card), true);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::FISTICUFFS: {
            // Fisticuffs.cs: GainBlock(sum of DamageResult.TotalDamage +
            // OverkillDamage), i.e. the actual result, including Vigor and
            // Intangible, not a precomputed estimate.
            double b = bc.enchant_card_damage(card, dmg);
            if (bc.player_power(PowerId::VIGOR) > 0) {
                b += bc.player_power(PowerId::VIGOR);
                bc.add_player_power(PowerId::VIGOR, -bc.player_power(PowerId::VIGOR),true);
            }
            const int hitDmg = bc.calc_player_damage(b, target, true, &card);
            const DamageDealt res = bc.damage_monster(target, hitDmg, true, true);
            bc.trigger_skittish(target, res.unblocked > 0);
            bc.gain_block(res.total + res.overkill, true);
            return true;
        }
        case CardId::FLASH_OF_STEEL:
            bc.attack_from_card(card, target, dmg);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::GANG_UP:
        case CardId::HUDDLE_UP:
        case CardId::INTERCEPT_CARD:
        case CardId::LIFT:
        case CardId::MIMIC:
        case CardId::RALLY:
        case CardId::TAG_TEAM:
        case CardId::KNOCKDOWN:
            return false;  // multiplayer behaviour; generic fallback applies
        case CardId::IMPATIENCE: {
            bool has_attack = false;
            for (int i = 0; i < bc.handCount; ++i) has_attack |= card_is_attack(bc.hand[i]);
            if (!has_attack) bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        }
        case CardId::JACK_OF_ALL_TRADES: {
            CardId options[static_cast<int>(CardId::COUNT)];
            int n = bc.combat_card_options(CardPool::COLORLESS, options);
            n = static_cast<int>(std::remove(options, options + n, CardId::JACK_OF_ALL_TRADES) - options);
            Card generated[MAX_HAND];
            const int made = bc.distinct_for_combat(options, n, std::min<int>(card_var(card, VarId::CARDS), MAX_HAND), generated);
            for (int k = 0; k < made; ++k) {
                bc.add_card_to_hand(generated[k]);
                bc.notify_card_generated(generated[k]);
            }
            return true;
        }
        case CardId::MIND_BLAST:
            bc.attack_from_card(card, target,
                                card_var(card, VarId::CALC_BASE) +
                                    card_var(card, VarId::EXTRA_DAMAGE) * bc.drawCount);
            return true;
        case CardId::OMNISLICE: {
            // Omnislice.cs: the splash base is the first target's actual
            // DamageResult.TotalDamage + OverkillDamage, dealt as Unpowered.
            double b = bc.enchant_card_damage(card, dmg);
            if (bc.player_power(PowerId::VIGOR) > 0) {
                b += bc.player_power(PowerId::VIGOR);
                bc.add_player_power(PowerId::VIGOR, -bc.player_power(PowerId::VIGOR),true);
            }
            const int hitDmg = bc.calc_player_damage(b, target, true, &card);
            const DamageDealt res = bc.damage_monster(target, hitDmg, true, true);
            bc.trigger_skittish(target, res.unblocked > 0);
            const int splash = res.total + res.overkill;
            // The splash is Unpowered, but ThornsPower reacts to any damage from Omnislice.
            int targets[MAX_MONSTERS];
            const int n = bc.living_enemies(targets);
            for (int k = 0; k < n && bc.outcome == Outcome::UNDECIDED; ++k) {
                const int i = targets[k];
                if (i == target || !bc.monsters[i].alive) continue;
                const int thorns = bc.monsters[i].power[static_cast<int>(PowerId::THORNS)];
                if (thorns > 0) bc.damage_player(thorns);
                if (bc.outcome == Outcome::UNDECIDED) bc.damage_monster(i, splash, true, false);
            }
            return true;
        }
        case CardId::PANACHE_CARD:
            bc.add_player_power(PowerId::PANACHE, card_var(card, VarId::PANACHE_DAMAGE),true);
            return true;
        case CardId::PANIC_BUTTON:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::NO_BLOCK, card_var(card, VarId::TURNS),true);
            return true;
        case CardId::PREP_TIME:
            bc.add_player_power(PowerId::PREP_TIME, card_var(card, VarId::PREP_TIME),true);
            return true;
        case CardId::PRODUCTION:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::PROLONG:
            if (bc.player.block > 0) bc.add_player_power(PowerId::BLOCK_NEXT_TURN, bc.player.block,true);
            return true;
        // Native applies EnergyNextTurnPower / DrawCardsNextTurnPower.
        case CardId::OUTMANEUVER:
            bc.add_player_power(PowerId::ENERGY_NEXT_TURN, card_var(card, VarId::ENERGY),true);
            return true;
        case CardId::RELAX:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::DRAW_CARDS_NEXT_TURN, card_var(card, VarId::CARDS),true);
            bc.add_player_power(PowerId::ENERGY_NEXT_TURN, card_var(card, VarId::ENERGY),true);
            return true;
        case CardId::BRIGHTEST_FLAME: {
            bc.player.energy += card_var(card, VarId::ENERGY);
            bc.draw_cards(card_var(card, VarId::CARDS));
            bc.lose_max_hp(card_var(card, VarId::MAX_HP), true);
            return true;
        }
        case CardId::PROWESS:
            bc.add_player_power(PowerId::STRENGTH, card_var(card, VarId::STRENGTH),true);
            bc.add_player_power(PowerId::DEXTERITY, card_var(card, VarId::DEXTERITY),true);
            return true;
        case CardId::PURITY:
            if (bc.handCount == 0) return true;
            bc.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND,
                            card_var(card, VarId::CARDS), true, card,
                            bc.card_will_exhaust(card));
            return true;
        case CardId::REND:
            bc.attack_from_card(
                card, target,
                card_var(card, VarId::CALC_BASE) +
                    card_var(card, VarId::EXTRA_DAMAGE) *
                        (target >= 0 && target < bc.monsterCount
                             ? rend_debuff_count(bc.monsters[target]) : 0));
            return true;
        case CardId::RESTLESSNESS:
            if (bc.handCount == 0) {
                bc.draw_cards(card_var(card, VarId::CARDS));
                bc.player.energy += card_var(card, VarId::ENERGY);
            }
            return true;
        case CardId::SCRAWL:
            if (MAX_HAND > bc.handCount) bc.draw_cards(MAX_HAND - bc.handCount);
            return true;
        case CardId::SECRET_TECHNIQUE:
            bc.start_draw_choice(card, bc.card_will_exhaust(card), static_cast<int>(CardType::SKILL), -1);
            return true;
        case CardId::SECRET_WEAPON:
            bc.start_draw_choice(card, bc.card_will_exhaust(card), static_cast<int>(CardType::ATTACK), -1);
            return true;
        case CardId::SEEKER_STRIKE:
            bc.attack_from_card(card, target, dmg);
            if (bc.outcome == Outcome::UNDECIDED && bc.drawCount > 0) {
                bc.start_draw_choice(card, bc.card_will_exhaust(card), -1,
                                     -1, card_var(card, VarId::CARDS));
            } else if (bc.drawCount > 1) {
                // StableShuffle still consumes the stream when the attack ended the combat.
                int order[MAX_PILE];
                for (int i = 0; i < bc.drawCount; ++i) order[i] = i;
                bc.cardSelectionRng.shuffle(order, bc.drawCount);
            }
            return true;
        case CardId::SHOCKWAVE:
        {
            int targets[MAX_MONSTERS];   // HittableEnemies
            const int n = bc.living_enemies(targets);
            for (int k = 0; k < n; ++k) {
                bc.apply_weak(targets[k], card_var(card, VarId::POWER));
                bc.apply_vulnerable(targets[k], card_var(card, VarId::POWER));
            }
            return true;
        }
        case CardId::SPLASH: {
            // Splash.OnPlay: Attacks from every unlocked character pool except
            // the player's own (kept only when it is the sole unlocked pool),
            // then GetDistinctForCombat(3) on CombatCardGeneration.
            constexpr CardPool order[] = {CardPool::IRONCLAD, CardPool::SILENT, CardPool::REGENT,
                                          CardPool::NECROBINDER, CardPool::DEFECT};
            CardPool pools[5];
            int poolN = 0;
            for (int i = 0; i < 5; ++i)
                if (bc.unlockedCharacterMask & (1u << i)) pools[poolN++] = order[i];
            if (poolN > 1) {
                int kept = 0;
                for (int i = 0; i < poolN; ++i) if (pools[i] != bc.characterPool) pools[kept++] = pools[i];
                poolN = kept;
            }
            CardId pool[static_cast<int>(CardId::COUNT)];
            int poolCount = 0;
            for (int p = 0; p < poolN; ++p)
                poolCount += bc.combat_card_options(pools[p], pool + poolCount, static_cast<int>(CardType::ATTACK));
            bc.cardGenerationRng.shuffle(pool, poolCount);
            Card offers[MAX_HAND];
            int n = 0;
            for (int k = 0; k < 3 && k < poolCount; ++k)
                offers[n++] = make_card(pool[k], card.upgraded, bc.require_card_uid());
            if (n == 0) return true;
            bc.start_offer(ChoiceOp::OFFER_TO_HAND, offers, n, card, bc.card_will_exhaust(card), true);
            bc.pending.optional = true;
            return true;
        }
        case CardId::STRATAGEM:
            bc.add_player_power(PowerId::STRATAGEM, 1,true);
            return true;
        case CardId::THE_BOMB_CARD:
            // TheBombPower is instanced: every copy keeps its own countdown and
            // damage instead of merging into one power stack.
            if (bc.bombCount < BattleContext::MAX_BOMBS) {
                bc.bombTurns[bc.bombCount] = card_var(card, VarId::TURNS);
                bc.bombDamage[bc.bombCount] = card_var(card, VarId::BOMB_DAMAGE);
                ++bc.bombCount;
            }
            return true;
        case CardId::THINKING_AHEAD:
            bc.draw_cards(card_var(card, VarId::CARDS));
            if (bc.handCount > 0) {
                bc.start_choice(ChoiceOp::PUT_HAND_TOP, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            }
            return true;
        case CardId::THRUMMING_HATCHET:
            // ThrummingHatchet.OnPlay only attacks; the card follows the normal
            // result pile (discard) and is recalled by BeforeHandDraw next round.
            bc.attack_from_card(card, target, dmg);
            return true;
        case CardId::VOLLEY:
            if (bc.xCost > 0) bc.attack_random_from_card(card, dmg, bc.xCost);
            return true;

        // ---- rare ----
        case CardId::ALCHEMIZE:
            bc.gain_random_combat_potion();
            return true;
        case CardId::APOTHEOSIS: {
            Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount,
                                  bc.exhaustCount, bc.playCount};
            for (int p = 0; p < 5; ++p) {
                for (int i = 0; i < counts[p]; ++i) {
                    // PlayerCombatState.AllCards, except the Apotheosis being played.
                    if (piles[p][i].uid != card.uid && card_upgradable(piles[p][i])) bc.upgrade_card(piles[p][i]);
                }
            }
            return true;
        }
        case CardId::APPARITION:
            bc.add_player_power(PowerId::INTANGIBLE,
                                card_var(card, VarId::INTANGIBLE_POWER),true);
            return true;
        case CardId::ANOINTED: {
            // TakeRandom shuffles all rare cards, then takes only free hand
            // slots. Cards beyond that limit must remain in the draw pile.
            std::uint16_t candidates[MAX_PILE];
            int n = 0;
            for (int i = bc.drawCount - 1; i >= 0; --i)   // native pile order: top first
                if (card_def(bc.draw[i].id).rarity == Rarity::RARE) candidates[n++] = bc.draw[i].uid;
            bc.cardSelectionRng.shuffle(candidates, n);
            const int take = std::min(n, MAX_HAND - bc.handCount);
            for (int k = 0; k < take; ++k) {
                for (int i = 0; i < bc.drawCount; ++i) {
                    if (bc.draw[i].uid != candidates[k]) continue;
                    add_from_draw(bc, i);
                    break;
                }
            }
            return true;
        }
        case CardId::CALTROPS:
            bc.add_player_power(PowerId::THORNS, card_var(card, VarId::THORNS_POWER),true);
            return true;
        case CardId::DISTRACTION: {
            CardId options[static_cast<int>(CardId::COUNT)];
            const int n = bc.combat_card_options(bc.characterPool, options, static_cast<int>(CardType::SKILL));
            Card c;
            if (bc.distinct_for_combat(options, n, 1, &c) == 1) {
                card_modify_cost(c, 0, true, 2 | 4 | 8);  // SetToFreeThisTurn
                bc.add_card_to_hand(c);
                bc.notify_card_generated(c);
            }
            return true;
        }
        case CardId::DUAL_WIELD:
            bc.start_choice(ChoiceOp::DUPLICATE, ChoicePile::HAND, 1, false,
                            card, bc.card_will_exhaust(card),
                            card_var(card, VarId::CARDS));
            return true;
        case CardId::ENLIGHTENMENT:
            // Enlightenment: reduce-only Set(1) this combat (upgraded) or this
            // turn / until played, on every hand card.
            for (int i = 0; i < bc.handCount; ++i)
                card_modify_cost(bc.hand[i], 1, true, card.upgraded ? 0 : (2 | 4), true);
            return true;
        case CardId::EXTERMINATE:
            bc.attack_all_from_card(card, dmg,
                                    card_var(card, VarId::REPEAT));
            return true;
        case CardId::FEEDING_FRENZY_CARD:
            bc.add_temp_strength(card_var(card, VarId::STRENGTH));
            bc.player.power[static_cast<int>(PowerId::FEEDING_FRENZY)] += card_var(card, VarId::STRENGTH);
            return true;
        case CardId::HELLO_WORLD_CARD:
            bc.add_player_power(PowerId::HELLO_WORLD, 1,true);
            return true;
        case CardId::MAUL: {
            bc.attack_from_card(card, target, dmg, 2);
            const int increase = card_var(card, VarId::INCREASE);
            card.bonusDamage += increase;
            Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount,
                                  bc.exhaustCount, bc.playCount};
            for (int p = 0; p < 5; ++p) {
                for (int i = 0; i < counts[p]; ++i) {
                    if (piles[p][i].id != CardId::MAUL || &piles[p][i] == &card) continue;
                    piles[p][i].bonusDamage += increase;
                }
            }
            return true;
        }
        case CardId::METAMORPHOSIS: {
            CardId options[static_cast<int>(CardId::COUNT)];
            const int n = bc.combat_card_options(bc.characterPool, options, static_cast<int>(CardType::ATTACK));
            for (int i = 0; i < card_var(card, VarId::CARDS) && n > 0; ++i) {
                Card c = bc.next_for_combat(options, n);
                c.freeCombat = true;
                card_modify_cost(c, 0, true, 8);  // SetToFreeThisCombat
                bc.add_card_to_draw_random(c);
                bc.notify_card_generated(c);
            }
            return true;
        }
        case CardId::NEOWS_FURY: {
            bc.attack_from_card(card, target, dmg);
            // The player chooses up to min(Cards, free hand slots) discard cards.
            const int take = std::min({card_var(card, VarId::CARDS), MAX_HAND - bc.handCount, bc.discardCount});
            if (take > 0 && bc.outcome == Outcome::UNDECIDED)
                bc.start_choice(ChoiceOp::DISCARD_TO_HAND, ChoicePile::DISCARD, take, true, card,
                                bc.card_will_exhaust(card));
            return true;
        }
        case CardId::PECK:
            bc.attack_from_card(card, target, dmg, card_var(card, VarId::REPEAT));
            return true;
        case CardId::MAD_SCIENCE: {
            // Type set by Tinker Time; riders (TinkerTime.RiderEffect):
            // 1 Sapping 2 Violence 3 Choking 4 Energized 5 Wisdom 6 Chaos
            // 7 Expertise 8 Curious 9 Improvement.
            const CardType type = card_type(card);
            const int rider = card.tinkerRider;
            if (type == CardType::ATTACK) {
                bc.attack_from_card(card, target, dmg, rider == 2 ? 3 : 1);
            } else if (type == CardType::SKILL) {
                // MadScience BlockVar(8): the exported card table has block 0
                // for the canonical (Attack) Mad Science.
                bc.gain_block(8 + card.bonusBlock, true);
            } else if (rider == 7) {
                bc.add_player_power(PowerId::STRENGTH, 2,true);
                bc.add_player_power(PowerId::DEXTERITY, 2,true);
            } else if (rider == 8) {
                bc.add_player_power(PowerId::CURIOUS, 1,true);
            } else if (rider == 9) {
                bc.add_player_power(PowerId::IMPROVEMENT, 1,true);
            }
            if (bc.outcome != Outcome::UNDECIDED) return true;
            if (rider == 1 && target >= 0 && target < bc.monsterCount && bc.monsters[target].alive) {
                bc.apply_weak(target, 2);
                bc.apply_vulnerable(target, 2);
            } else if (rider == 3 && target >= 0 && target < bc.monsterCount && bc.monsters[target].alive) {
                bc.add_monster_power(target, PowerId::STRANGLE, 6,true);
            } else if (rider == 4) {
                bc.player.energy += 2;
            } else if (rider == 5) {
                bc.draw_cards(3);
            } else if (rider == 6) {
                // GetDistinctForCombat(character pool, 1, CombatCardGeneration), free this turn.
                Card generated[1];
                int n = 0;
                random_ironclad_cards(bc, 1, false, generated, n);
                if (n == 1) {
                    card_modify_cost(generated[0], 0, true, 2 | 4 | 8);  // SetToFreeThisTurn
                    bc.add_card_to_hand(generated[0]);
                    bc.notify_card_generated(generated[0]);
                }
            }
            return true;
        }
        case CardId::REBOUND:
            bc.attack_from_card(card, target, dmg);
            bc.add_player_power(PowerId::REBOUND, 1, true);
            return true;
        case CardId::RIP_AND_TEAR:
            bc.attack_random_from_card(card, dmg, 2);
            return true;
        case CardId::SQUASH:
            bc.attack_from_card(card, target, dmg);
            bc.apply_vulnerable(target, card_var(card, VarId::VULNERABLE));
            return true;
        case CardId::STACK:
            bc.gain_block(card_var(card, VarId::CALC_BASE) +
                              card_var(card, VarId::CALC_EXTRA) * bc.discardCount,
                          true);
            return true;
        case CardId::BEACON_OF_HOPE:
            return true;
        case CardId::BEAT_DOWN: {
            // BeatDown.cs: snapshot the discard's playable attacks, stable
            // shuffle, take Cards, then AutoPlay each captured card.  The card
            // leaves the discard before it is played, so its entity exists in
            // exactly one pile afterwards.
            int idxs[MAX_PILE];
            int n = 0;
            for (int i = 0; i < bc.discardCount; ++i) {
                if (card_is_attack(bc.discard[i]) && card_is_playable(bc.discard[i])) {
                    idxs[n++] = i;
                }
            }
            // StableShuffle on the Shuffle stream.
            native_sort_card_indices(bc.discard, idxs, n);
            bc.shuffleRng.shuffle(idxs, n);
            Card picks[MAX_PILE];
            int picked = 0;
            const int count = std::min<int>(card_var(card, VarId::CARDS), n);
            for (int k = 0; k < count; ++k) picks[picked++] = bc.discard[idxs[k]];
            for (int k = 0; k < picked && bc.outcome == Outcome::UNDECIDED; ++k) {
                // An earlier auto-play (e.g. Headbutt) may have moved a later
                // pick to another pile; detach the real entity wherever it is so
                // the same UID never exists twice.
                if (!bc.detach_card(picks[k].uid)) continue;
                bc.auto_play_random(picks[k], false);
            }
            return true;
        }
        case CardId::BOLAS:
            // Follows the normal result pile; BeforeHandDraw recalls it next turn.
            bc.attack_from_card(card, target, dmg);
            return true;
        case CardId::CALAMITY_CARD:
            bc.add_player_power(PowerId::CALAMITY, 1,true);
            return true;
        case CardId::ENTROPY:
            bc.add_player_power(PowerId::ENTROPY, 1,true);
            return true;
        case CardId::ETERNAL_ARMOR:
            bc.add_player_power(PowerId::PLATING, card_var(card, VarId::PLATING),true);
            return true;
        case CardId::GOLD_AXE:
            bc.attack_from_card(
                card, target,
                card_var(card, VarId::CALC_BASE) +
                    card_var(card, VarId::EXTRA_DAMAGE) * bc.cardsFinishedThisCombat);
            return true;
        case CardId::HAND_OF_GREED: {
            const bool fatal_eligible = bc.can_trigger_fatal(target);
            // HandOfGreed.cs attacks FromCard, so Pen Nib and other card-
            // sourced damage modifiers must apply (attack_monster does not).
            const bool killed = bc.attack_from_card(card, target, dmg);
            if (fatal_eligible && killed) {
                bc.gain_gold(card_var(card, VarId::GOLD));
            }
            return true;
        }
        case CardId::HIDDEN_GEM: {
            int valid[MAX_PILE];
            int preferred[MAX_PILE];
            int n = 0;
            int preferredCount = 0;
            for (int i = bc.drawCount - 1; i >= 0; --i) {   // native pile order: top first
                const CardDef &d = card_def(bc.draw[i].id);
                if (card_has(bc.draw[i], CF_UNPLAYABLE)) continue;
                if (card_type(bc.draw[i]) == CardType::CURSE) continue;
                const Card &c = bc.draw[i];
                const int enchantedReplay = c.replay + c.bonusReplay +
                    (c.enchantment == EnchantmentId::SPIRAL ||
                     (c.enchantment == EnchantmentId::GLAM && !c.enchantmentDisabled));
                if (enchantedReplay > 0) continue;
                valid[n++] = i;
                const CardType type = card_type(c);
                (void)d;
                if (type == CardType::ATTACK || type == CardType::SKILL || type == CardType::POWER)
                    preferred[preferredCount++] = i;
            }
            if (n > 0) {
                const int idx = preferredCount > 0
                    ? preferred[bc.cardSelectionRng.next_int(0, preferredCount - 1)]
                    : valid[bc.cardSelectionRng.next_int(0, n - 1)];
                bc.draw[idx].replay = static_cast<std::uint8_t>(
                    bc.draw[idx].replay + card_var(card, VarId::REPLAY));
            }
            return true;
        }
        case CardId::JACKPOT: {
            bc.attack_from_card(card, target, dmg);
            CardId pool[static_cast<int>(CardId::COUNT)];
            const int n = zero_cost_pool(bc, pool);
            for (int k = 0; k < card_var(card, VarId::CARDS) && n > 0; ++k) {
                Card c = bc.next_for_combat(pool, n);
                if (card.upgraded) bc.upgrade_card(c);
                bc.add_card_to_hand(c);
                bc.notify_card_generated(c);
            }
            return true;
        }
        case CardId::MASTER_OF_STRATEGY:
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::MAYHEM_CARD:
            bc.add_player_power(PowerId::MAYHEM, 1,true);
            return true;
        case CardId::NOSTALGIA_CARD:
            bc.add_player_power(PowerId::NOSTALGIA, 1,true);
            return true;
        case CardId::ROLLING_BOULDER:
            bc.add_player_power(PowerId::ROLLING_BOULDER, card_var(card, VarId::ROLLING_BOULDER),true);
            return true;
        case CardId::SALVO:
            bc.attack_from_card(card, target, dmg);
            bc.add_player_power(PowerId::RETAIN_HAND, 1,true);
            return true;
        case CardId::THE_GAMBIT:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::THE_GAMBIT, 1,true);
            return true;
        case CardId::TORIC_TOUGHNESS: {
            const int before = bc.player.block;
            bc.gain_block(card_block(card), true);
            if (bc.toricCount < MAX_PILE) {
                const int gained = bc.player.block - before;
                const int turns = card_var(card, VarId::TURNS);
                bc.toricBlock[bc.toricCount] = gained;
                bc.toricTurns[bc.toricCount] = turns;
                ++bc.toricCount;
                bc.player.toricToughnessBlock += gained;
                bc.add_player_power(PowerId::TORIC_TOUGHNESS, turns,true);
            }
            return true;
        }
        case CardId::WHISTLE:
            bc.attack_from_card(card, target, dmg);
            if (target >= 0 && target < bc.monsterCount &&
                bc.monsters[target].alive) {
                bc.monsters[target].stunned = true;
                roll_intent(bc, bc.monsters[target]);
            }
            return true;
        case CardId::WISH:
            if (bc.drawCount > 0) {
                bc.start_draw_choice(card, bc.card_will_exhaust(card), -1, -1);
            }
            return true;
        case CardId::FUEL:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::BYRD_SWOOP:
            // Native uses Byrdpip only as the visual attacker. Damage and
            // attack hooks belong to the player, even if no pet is present.
            bc.attack_from_card(card, target, dmg);
            return true;
        case CardId::SOUL:
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;

        default:
            return false;
    }
}

}  // namespace sts2
