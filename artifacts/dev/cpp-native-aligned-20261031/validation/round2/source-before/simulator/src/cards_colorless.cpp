#include "sts2/effects.h"
#include "sts2/monsters.h"

namespace sts2 {
#include "sts2/cards_generated.inc"

namespace {

bool usable_generated(const CardDef &d) {
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                   CF_CANNOT_GENERATE_IN_COMBAT)) {
        return false;
    }
    return d.rarity == Rarity::COMMON || d.rarity == Rarity::UNCOMMON ||
           d.rarity == Rarity::RARE;
}

int ironclad_pool(CardId *out) {
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        if (CARD_DEFS[i].pool == CardPool::IRONCLAD &&
            usable_generated(CARD_DEFS[i])) {
            out[n++] = static_cast<CardId>(i);
        }
    }
    return n;
}

void random_ironclad_cards(BattleContext &bc, int count, bool upgraded, Card *out, int &outN) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    const int n = ironclad_pool(pool);
    outN = 0;
    for (int k = 0; k < count && n > 0; ++k) {
        // distinct pick
        bool duplicate = true;
        int attempts = 0;
        while (duplicate && attempts++ < 64) {
            const CardId id = pool[bc.cardGenerationRng.next_int(0, n - 1)];
            duplicate = false;
            for (int j = 0; j < outN; ++j) if (out[j].id == id) duplicate = true;
            if (!duplicate) {
                Card c = make_card(id, upgraded, bc.require_card_uid());
                if (upgraded) c.costForTurn = card_def(id).costUp;
                out[outN++] = c;
            }
        }
    }
}

void add_from_draw(BattleContext &bc, int idx) {
    Card c = bc.draw[idx];
    bc.remove_draw_at(idx);
    bc.add_card_to_hand(c);
}

void random_draw_auto_play(BattleContext &bc, int count) {
    for (int k = 0; k < count && bc.drawCount > 0 && bc.outcome == Outcome::UNDECIDED; ++k) {
        const int idx = bc.cardSelectionRng.next_int(0, bc.drawCount - 1);
        Card c = bc.draw[idx];
        bc.remove_draw_at(idx);
        bc.auto_play_random(c, false);
    }
}

int zero_cost_pool(CardId *out) {
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = CARD_DEFS[i];
        if (d.pool != CardPool::IRONCLAD) continue;
        if (!usable_generated(d)) continue;
        if (d.cost == 0 && d.costUp == 0) out[n++] = static_cast<CardId>(i);
    }
    return n;
}

int rend_debuff_count(const Monster &m) {
    int n = 0;
    if (m.vulnerable > 0) ++n;
    if (m.weak > 0) ++n;
    if (m.power[static_cast<int>(PowerId::POISON)] > 0) ++n;
    if (m.power[static_cast<int>(PowerId::GRAPPLE)] > 0) ++n;
    if (m.power[static_cast<int>(PowerId::KNOCKDOWN)] > 0) ++n;
    if (m.power[static_cast<int>(PowerId::SHRINK)] > 0) ++n;
    if (m.power[static_cast<int>(PowerId::SLOW)] > 0) ++n;
    if (m.power[static_cast<int>(PowerId::MANGLE_POW)] > 0) ++n;
    return n;
}

}  // namespace

bool colorless_effect(BattleContext &bc, Card &card, int target) {
    const int dmg = card_damage(card);

    switch (card.id) {
        // ---- uncommon ----
        case CardId::AUTOMATION:
            bc.add_player_power(PowerId::AUTOMATION, 1);
            return true;
        case CardId::BELIEVE_IN_YOU:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::CATASTROPHE:
            random_draw_auto_play(bc, card_var(card, VarId::CARDS));
            return true;
        case CardId::COORDINATE_CARD:
            bc.add_player_power(PowerId::COORDINATE, card_var(card, VarId::STRENGTH));
            return true;
        case CardId::DARK_SHACKLES: {
            if (target < 0 || target >= bc.monsterCount) return true;
            // DarkShacklesPower: temporary strength loss, restored at the end of
            // the affected monster's turn (same timing as Mangle).
            bc.apply_strength_loss(target, card_var(card, VarId::STRENGTH_LOSS));
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
            bc.add_player_power(PowerId::RETAIN_HAND, 1);
            return true;
        case CardId::FASTEN:
            bc.add_player_power(PowerId::FASTEN, card_var(card, VarId::EXTRA_BLOCK));
            return true;
        case CardId::FINESSE:
            bc.gain_block(card_block(card), true);
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::FISTICUFFS: {
            // Fisticuffs.cs: GainBlock(sum of DamageResult.TotalDamage +
            // OverkillDamage), i.e. the actual result, including Vigor and
            // Intangible, not a precomputed estimate.
            int b = dmg;
            if (bc.player_power(PowerId::VIGOR) > 0) {
                b += bc.player_power(PowerId::VIGOR);
                bc.add_player_power(PowerId::VIGOR, -bc.player_power(PowerId::VIGOR));
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
            CardId picked[MAX_HAND]{};
            picked[0] = CardId::JACK_OF_ALL_TRADES;
            int n = 1;
            for (int k = 0; k < card_var(card, VarId::CARDS); ++k) {
                Card c = bc.random_colorless_card_excluding(picked, n);
                if (n < MAX_HAND) picked[n++] = c.id;
                bc.add_card_to_hand(c);
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
            int b = dmg;
            if (bc.player_power(PowerId::VIGOR) > 0) {
                b += bc.player_power(PowerId::VIGOR);
                bc.add_player_power(PowerId::VIGOR, -bc.player_power(PowerId::VIGOR));
            }
            const int hitDmg = bc.calc_player_damage(b, target, true, &card);
            const DamageDealt res = bc.damage_monster(target, hitDmg, true, true);
            bc.trigger_skittish(target, res.unblocked > 0);
            const int splash = res.total + res.overkill;
            if (splash <= 0) return true;
            for (int i = 0; i < bc.monsterCount; ++i) {
                if (i == target || !bc.monsters[i].alive) continue;
                bc.damage_monster(i, splash, true, false);
            }
            return true;
        }
        case CardId::PANACHE_CARD:
            bc.add_player_power(PowerId::PANACHE, card_var(card, VarId::PANACHE_DAMAGE));
            return true;
        case CardId::PANIC_BUTTON:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::NO_BLOCK, card_var(card, VarId::TURNS));
            return true;
        case CardId::PREP_TIME:
            bc.add_player_power(PowerId::PREP_TIME, card_var(card, VarId::PREP_TIME));
            return true;
        case CardId::PRODUCTION:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::PROLONG:
            if (bc.player.block > 0) bc.add_player_power(PowerId::BLOCK_NEXT_TURN, bc.player.block);
            return true;
        case CardId::OUTMANEUVER:
            bc.nextTurnEnergy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::RELAX:
            bc.gain_block(card_block(card), true);
            bc.nextTurnDraw += card_var(card, VarId::CARDS);
            bc.nextTurnEnergy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::BRIGHTEST_FLAME: {
            bc.player.energy += card_var(card, VarId::ENERGY);
            bc.draw_cards(card_var(card, VarId::CARDS));
            // CreatureCmd.LoseMaxHp: max HP drops by the full amount; current
            // HP is only reduced when it would exceed the new maximum.
            bc.player.maxHp = std::max(0, bc.player.maxHp - card_var(card, VarId::MAX_HP));
            if (bc.player.hp > bc.player.maxHp) bc.player.hp = bc.player.maxHp;
            return true;
        }
        case CardId::PROWESS:
            bc.add_player_power(PowerId::STRENGTH, card_var(card, VarId::STRENGTH));
            bc.add_player_power(PowerId::DEXTERITY, card_var(card, VarId::DEXTERITY));
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
            }
            return true;
        case CardId::SHOCKWAVE:
            for (int i = 0; i < bc.monsterCount; ++i) {
                if (!bc.monsters[i].alive) continue;
                bc.apply_weak(i, card_var(card, VarId::POWER));
                bc.apply_vulnerable(i, card_var(card, VarId::POWER));
            }
            return true;
        case CardId::SPLASH: {
            Card offers[MAX_HAND];
            int n = 0;
            random_ironclad_cards(bc, 3, card.upgraded, offers, n);
            if (n == 0) return true;
            bc.start_offer(ChoiceOp::OFFER_TO_HAND, offers, n, card, bc.card_will_exhaust(card), true);
            bc.pending.optional = true;
            return true;
        }
        case CardId::STRATAGEM:
            bc.add_player_power(PowerId::STRATAGEM, 1);
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
            for (int i = 0; i < bc.xCost; ++i) {
                const int t = bc.random_alive_monster();
                if (t < 0) break;
                bc.attack_from_card(card, t, dmg);
            }
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
                    if (card_upgradable(piles[p][i])) bc.upgrade_card(piles[p][i]);
                }
            }
            return true;
        }
        case CardId::APPARITION:
            bc.add_player_power(PowerId::INTANGIBLE,
                                card_var(card, VarId::INTANGIBLE_POWER));
            return true;
        case CardId::ANOINTED: {
            for (int i = bc.drawCount - 1; i >= 0; --i) {
                const CardDef &d = card_def(bc.draw[i].id);
                if (d.rarity == Rarity::RARE && !(d.flags & CF_UNPLAYABLE)) add_from_draw(bc, i);
            }
            return true;
        }
        case CardId::CALTROPS:
            bc.add_player_power(PowerId::THORNS, card_var(card, VarId::THORNS_POWER));
            return true;
        case CardId::DISTRACTION: {
            Card c = bc.random_card_of_type(CardType::SKILL, false);
            card_set_turn_cost(c, 0);
            bc.add_card_to_hand(c);
            return true;
        }
        case CardId::DUAL_WIELD:
            bc.start_choice(ChoiceOp::DUPLICATE, ChoicePile::HAND, 1, false,
                            card, bc.card_will_exhaust(card),
                            card_var(card, VarId::CARDS));
            return true;
        case CardId::ENLIGHTENMENT:
            for (int i = 0; i < bc.handCount; ++i) {
                if (card.upgraded) {
                    if (bc.hand[i].combatCostCap < 0 || bc.hand[i].combatCostCap > 1) {
                        bc.hand[i].combatCostCap = 1;
                    }
                } else if (bc.hand[i].costForTurn > 1) {
                    card_set_turn_cost(bc.hand[i], 1);
                }
            }
            return true;
        case CardId::EXTERMINATE:
            bc.attack_all_from_card(card, dmg,
                                    card_var(card, VarId::REPEAT));
            return true;
        case CardId::FEEDING_FRENZY_CARD:
            bc.add_temp_strength(card_var(card, VarId::STRENGTH));
            return true;
        case CardId::HELLO_WORLD_CARD:
            bc.add_player_power(PowerId::HELLO_WORLD, 1);
            return true;
        case CardId::MAUL: {
            bc.attack_from_card(card, target, dmg, 2);
            const int increase = card_var(card, VarId::INCREASE);
            Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount,
                                  bc.exhaustCount, bc.playCount};
            for (int p = 0; p < 5; ++p) {
                for (int i = 0; i < counts[p]; ++i) {
                    if (piles[p][i].id != CardId::MAUL) continue;
                    piles[p][i].bonusDamage += increase;
                }
            }
            return true;
        }
        case CardId::METAMORPHOSIS:
            for (int i = 0; i < card_var(card, VarId::CARDS); ++i) {
                Card c = bc.random_card_of_type(CardType::ATTACK, false);
                c.freeCombat = true;
                bc.add_card_to_draw_random(c);
            }
            return true;
        case CardId::NEOWS_FURY: {
            bc.attack_from_card(card, target, dmg);
            int take = std::min(card_var(card, VarId::CARDS), bc.discardCount);
            for (int i = 0; i < take; ++i) {
                const int idx = bc.cardSelectionRng.next_int(0, bc.discardCount - 1);
                Card c = bc.discard[idx];
                for (int j = idx; j + 1 < bc.discardCount; ++j) {
                    bc.discard[j] = bc.discard[j + 1];
                }
                --bc.discardCount;
                bc.add_card_to_hand(c);
            }
            return true;
        }
        case CardId::PECK:
            bc.attack_from_card(card, target, dmg, card_var(card, VarId::REPEAT));
            return true;
        case CardId::REBOUND:
            bc.attack_from_card(card, target, dmg);
            bc.reboundPending = true;
            return true;
        case CardId::RIP_AND_TEAR:
            for (int i = 0; i < 2; ++i) {
                const int t = bc.random_alive_monster();
                if (t < 0) break;
                bc.attack_from_card(card, t, dmg);
            }
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
            for (int i = n - 1; i > 0; --i) {
                const int j = bc.cardSelectionRng.next_int(0, i);
                std::swap(idxs[i], idxs[j]);
            }
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
            bc.attack_from_card(card, target, dmg);
            if (bc.outcome == Outcome::UNDECIDED) {
                bc.returnToHand = true;
                bc.queue_return_next_turn(card);
            }
            return true;
        case CardId::CALAMITY_CARD:
            bc.add_player_power(PowerId::CALAMITY, 1);
            return true;
        case CardId::ENTROPY:
            bc.add_player_power(PowerId::ENTROPY, 1);
            return true;
        case CardId::ETERNAL_ARMOR:
            bc.add_player_power(PowerId::PLATING, card_var(card, VarId::PLATING));
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
            int n = 0;
            for (int i = 0; i < bc.drawCount; ++i) {
                const CardDef &d = card_def(bc.draw[i].id);
                if (d.flags & CF_UNPLAYABLE) continue;
                if (d.type == CardType::CURSE) continue;
                valid[n++] = i;
            }
            if (n > 0) {
                const int idx = valid[bc.cardSelectionRng.next_int(0, n - 1)];
                bc.draw[idx].replay = static_cast<std::uint8_t>(
                    bc.draw[idx].replay + card_var(card, VarId::REPLAY));
            }
            return true;
        }
        case CardId::JACKPOT: {
            bc.attack_from_card(card, target, dmg);
            CardId pool[static_cast<int>(CardId::COUNT)];
            const int n = zero_cost_pool(pool);
            for (int k = 0; k < card_var(card, VarId::CARDS) && n > 0; ++k) {
                Card c = make_card(pool[bc.cardGenerationRng.next_int(0, n - 1)],
                                   false, bc.require_card_uid());
                if (card.upgraded) bc.upgrade_card(c);
                bc.add_card_to_hand(c);
            }
            return true;
        }
        case CardId::MASTER_OF_STRATEGY:
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::MAYHEM_CARD:
            bc.add_player_power(PowerId::MAYHEM, 1);
            return true;
        case CardId::NOSTALGIA_CARD:
            bc.add_player_power(PowerId::NOSTALGIA, 1);
            return true;
        case CardId::ROLLING_BOULDER:
            bc.add_player_power(PowerId::ROLLING_BOULDER, card_var(card, VarId::ROLLING_BOULDER));
            return true;
        case CardId::SALVO:
            bc.attack_from_card(card, target, dmg);
            bc.add_player_power(PowerId::RETAIN_HAND, 1);
            return true;
        case CardId::THE_GAMBIT:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::THE_GAMBIT, 1);
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
                bc.add_player_power(PowerId::TORIC_TOUGHNESS, turns);
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

        default:
            return false;
    }
}

}  // namespace sts2
