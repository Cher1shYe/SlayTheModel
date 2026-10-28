#include "sts2/effects.h"

namespace sts2 {
#include "sts2/cards_generated.inc"

namespace {

bool is_colorless_index(int i) {
    return i > static_cast<int>(CardId::WHIRLWIND) && i < static_cast<int>(CardId::BECKON);
}

bool usable_generated(const CardDef &d) {
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    return d.rarity != Rarity::SPECIAL && d.rarity != Rarity::BASIC;
}

int ironclad_pool(CardId *out) {
    int n = 0;
    for (int i = 1; i <= static_cast<int>(CardId::WHIRLWIND); ++i) {
        if (usable_generated(CARD_DEFS[i])) out[n++] = static_cast<CardId>(i);
    }
    return n;
}

void random_ironclad_cards(BattleContext &bc, int count, bool upgraded, Card *out, int &outN) {
    CardId pool[256];
    const int n = ironclad_pool(pool);
    outN = 0;
    for (int k = 0; k < count && n > 0; ++k) {
        // distinct pick
        bool duplicate = true;
        int attempts = 0;
        while (duplicate && attempts++ < 64) {
            const CardId id = pool[bc.rng.next_int(0, n - 1)];
            duplicate = false;
            for (int j = 0; j < outN; ++j) if (out[j].id == id) duplicate = true;
            if (!duplicate) {
                Card c = make_card(id, upgraded, bc.nextUid++);
                if (upgraded) c.costForTurn = card_def(id).costUp;
                out[outN++] = c;
            }
        }
    }
}

void add_from_draw(BattleContext &bc, int idx) {
    Card c = bc.draw[idx];
    for (int i = idx; i < bc.drawCount - 1; ++i) bc.draw[i] = bc.draw[i + 1];
    --bc.drawCount;
    bc.add_card_to_hand(c);
}

void random_draw_auto_play(BattleContext &bc, int count) {
    for (int k = 0; k < count && bc.drawCount > 0 && bc.outcome == Outcome::UNDECIDED; ++k) {
        const int idx = bc.rng.next_int(0, bc.drawCount - 1);
        Card c = bc.draw[idx];
        for (int i = idx; i < bc.drawCount - 1; ++i) bc.draw[i] = bc.draw[i + 1];
        --bc.drawCount;
        bc.auto_play_random(c, false);
    }
}

int zero_cost_pool(CardId *out) {
    int n = 0;
    for (int i = 1; i <= static_cast<int>(CardId::WHIRLWIND); ++i) {
        const CardDef &d = CARD_DEFS[i];
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
            const int loss = card_var(card, VarId::STRENGTH_LOSS);
            bc.monsters[target].strength -= loss;
            bc.monsters[target].tempStrengthLoss += loss;
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
            int dealt = bc.calc_player_damage(dmg, target);
            bc.attack_monster(target, dmg);
            if (bc.outcome != Outcome::UNDECIDED) return true;
            if (dealt > 0) bc.gain_block(dealt, true);
            return true;
        }
        case CardId::FLASH_OF_STEEL:
            bc.attack_monster(target, dmg);
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
            for (int k = 0; k < card_var(card, VarId::CARDS); ++k) {
                Card c = bc.random_colorless_card();
                bc.add_card_to_hand(c);
            }
            return true;
        }
        case CardId::MIND_BLAST:
            bc.attack_monster(target, card_var(card, VarId::CALC_BASE) +
                                      card_var(card, VarId::EXTRA_DAMAGE) * bc.drawCount);
            return true;
        case CardId::OMNISLICE: {
            int dealt = bc.calc_player_damage(dmg, target);
            bc.attack_monster(target, dmg);
            if (bc.outcome != Outcome::UNDECIDED || dealt <= 0) return true;
            for (int i = 0; i < bc.monsterCount; ++i) {
                if (i == target || !bc.monsters[i].alive) continue;
                bc.damage_monster(i, dealt);
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
            bc.attack_monster(target, card_var(card, VarId::CALC_BASE) +
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
            bc.attack_monster(target, dmg);
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
            bc.add_player_power(PowerId::THE_BOMB, card_var(card, VarId::TURNS));
            bc.player.power[static_cast<int>(PowerId::THE_BOMB_DAMAGE)] =
                static_cast<std::int16_t>(card_var(card, VarId::BOMB_DAMAGE));
            return true;
        case CardId::THINKING_AHEAD:
            bc.draw_cards(card_var(card, VarId::CARDS));
            if (bc.handCount > 0) {
                bc.start_choice(ChoiceOp::PUT_HAND_TOP, ChoicePile::HAND, 1, false, card,
                                bc.card_will_exhaust(card));
            }
            return true;
        case CardId::THRUMMING_HATCHET:
            bc.attack_monster(target, dmg);
            if (bc.outcome == Outcome::UNDECIDED) {
                bc.returnToHand = true;
                if (bc.returnNextTurnCount < MAX_HAND) bc.returnNextTurn[bc.returnNextTurnCount++] = card;
            }
            return true;
        case CardId::VOLLEY:
            for (int i = 0; i < bc.xCost; ++i) {
                const int t = bc.random_alive_monster();
                if (t < 0) break;
                bc.attack_monster(t, dmg);
            }
            return true;

        // ---- rare ----
        case CardId::ALCHEMIZE:
            bc.gain_random_combat_potion();
            return true;
        case CardId::ANOINTED: {
            for (int i = bc.drawCount - 1; i >= 0; --i) {
                const CardDef &d = card_def(bc.draw[i].id);
                if (d.rarity == Rarity::RARE && !(d.flags & CF_UNPLAYABLE)) add_from_draw(bc, i);
            }
            return true;
        }
        case CardId::BEACON_OF_HOPE:
            return true;
        case CardId::BEAT_DOWN: {
            int picks[MAX_HAND];
            int n = 0;
            for (int i = 0; i < bc.discardCount; ++i) {
                if (card_is_attack(bc.discard[i]) && card_is_playable(bc.discard[i])) picks[n++] = i;
            }
            const int count = std::min<int>(card_var(card, VarId::CARDS), n);
            for (int k = 0; k < count; ++k) {
                const int j = bc.rng.next_int(0, n - 1);
                Card c = bc.discard[picks[j]];
                bc.auto_play_random(c, false);
                // locate and remove the played card from discard
                for (int i = bc.discardCount - 1; i >= 0; --i) {
                    if (bc.discard[i].uid == c.uid) {
                        for (int m = i; m < bc.discardCount - 1; ++m) bc.discard[m] = bc.discard[m + 1];
                        --bc.discardCount;
                        break;
                    }
                }
                for (int m = j; m < n - 1; ++m) picks[m] = picks[m + 1];
                --n;
                if (n == 0) break;
            }
            return true;
        }
        case CardId::BOLAS:
            bc.attack_monster(target, dmg);
            if (bc.outcome == Outcome::UNDECIDED) {
                bc.returnToHand = true;
                if (bc.returnNextTurnCount < MAX_HAND) bc.returnNextTurn[bc.returnNextTurnCount++] = card;
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
            bc.attack_monster(target, card_var(card, VarId::CALC_BASE) +
                                      card_var(card, VarId::EXTRA_DAMAGE) * bc.cardsPlayedThisCombat);
            return true;
        case CardId::HAND_OF_GREED: {
            const bool alive = target >= 0 && target < bc.monsterCount && bc.monsters[target].alive;
            bc.attack_monster(target, dmg);
            if (alive && target < bc.monsterCount && !bc.monsters[target].alive) {
                bc.combatGold += card_var(card, VarId::GOLD);
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
                const int idx = valid[bc.rng.next_int(0, n - 1)];
                bc.draw[idx].replay = static_cast<std::uint8_t>(
                    bc.draw[idx].replay + card_var(card, VarId::REPLAY));
            }
            return true;
        }
        case CardId::JACKPOT: {
            bc.attack_monster(target, dmg);
            CardId pool[128];
            const int n = zero_cost_pool(pool);
            for (int k = 0; k < card_var(card, VarId::CARDS) && n > 0; ++k) {
                Card c = make_card(pool[bc.rng.next_int(0, n - 1)], false, bc.nextUid++);
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
            bc.attack_monster(target, dmg);
            bc.add_player_power(PowerId::RETAIN_HAND, 1);
            return true;
        case CardId::THE_GAMBIT:
            bc.gain_block(card_block(card), true);
            bc.add_player_power(PowerId::THE_GAMBIT, 1);
            return true;

        default:
            return false;
    }
}

}  // namespace sts2
