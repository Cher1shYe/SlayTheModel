#include "sts2/regent.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"

#include <algorithm>
#include <stdexcept>

namespace sts2 {
namespace {

bool blade_outside_exhaust(const Card *pile, int count) {
    for (int i = 0; i < count; ++i) {
        if (pile[i].id == CardId::SOVEREIGN_BLADE) return true;
    }
    return false;
}

void forge_pile(Card *pile, int count, int amount) {
    for (int i = 0; i < count; ++i) {
        if (pile[i].id == CardId::SOVEREIGN_BLADE) pile[i].bonusDamage += amount;
    }
}

void replay_pile(Card *pile, int count, int amount) {
    for (int i = 0; i < count; ++i) {
        if (pile[i].id == CardId::SOVEREIGN_BLADE) {
            const int replay = static_cast<int>(pile[i].bonusReplay) + amount;
            pile[i].bonusReplay = static_cast<std::uint8_t>(std::max(0, replay));
        }
    }
}

// Every Sovereign Blade a SwordSagePower change can reach, including limbo
// frames. Clones are excluded from AfterCardEnteredCombat but not from
// AfterPowerAmountChanged (PlayerCombatState.AllCards includes them).
void each_blade(BattleContext &b, int amount) {
    replay_pile(b.hand, b.handCount, amount);
    replay_pile(b.draw, b.drawCount, amount);
    replay_pile(b.discard, b.discardCount, amount);
    replay_pile(b.exhaust, b.exhaustCount, amount);
    replay_pile(b.playPile, b.playCount, amount);
    replay_pile(b.returnNextTurn, b.returnNextTurnCount, amount);
    replay_pile(b.pending.cards, b.pending.count, amount);
    if (b.activePlay.active) replay_pile(&b.activePlay.card, 1, amount);
    for (int i = 0; i < b.suspendedPlayCount; ++i)
        replay_pile(&b.suspendedPlays[i].play.card, 1, amount);
}

constexpr int MONOLOGUE_CAPACITY = 160;

}  // namespace

// PlayerCmd.GainStars + PlayerCombatState.GainStars: negative input is rejected,
// the result clamps at zero, and only the actual delta enters the turn history
// (Radiate sums positive StarsModifiedEntry values for the current turn).
void regent_gain_stars(BattleContext &b, int amount) {
    if (amount < 0) throw std::invalid_argument("Stars must not be negative");
    const int before = b.regent.stars;
    b.regent.stars = std::max(0, b.regent.stars + amount);
    const int gained = b.regent.stars - before;
    if (gained > 0) b.regent.starsGainedThisTurn += gained;
    // BlackHolePower.AfterStarsGained: one unpowered hit equal to the stack.
    if (amount > 0 && b.player_power(PowerId::BLACK_HOLE) > 0) {
        b.attack_all(b.player_power(PowerId::BLACK_HOLE), 1, false);
    }
}

// ForgeCmd.Forge: create the first Sovereign Blade into hand when no
// non-exhausted copy exists, then add the amount to every copy's damage,
// including exhausted ones. Duplicate (limbo) cards are not forge targets.
void regent_forge(BattleContext &b, int amount) {
    const bool exists =
        blade_outside_exhaust(b.hand, b.handCount) ||
        blade_outside_exhaust(b.draw, b.drawCount) ||
        blade_outside_exhaust(b.discard, b.discardCount) ||
        blade_outside_exhaust(b.playPile, b.playCount) ||
        blade_outside_exhaust(b.returnNextTurn, b.returnNextTurnCount) ||
        blade_outside_exhaust(b.pending.cards, b.pending.count);
    if (!exists) {
        Card blade = make_card(CardId::SOVEREIGN_BLADE, false, b.require_card_uid());
        b.add_card_to_hand(blade);
        b.notify_card_generated(blade);
    }
    forge_pile(b.hand, b.handCount, amount);
    forge_pile(b.draw, b.drawCount, amount);
    forge_pile(b.discard, b.discardCount, amount);
    forge_pile(b.exhaust, b.exhaustCount, amount);
    forge_pile(b.playPile, b.playCount, amount);
    forge_pile(b.returnNextTurn, b.returnNextTurnCount, amount);
    forge_pile(b.pending.cards, b.pending.count, amount);
    if (b.activePlay.active && b.activePlay.card.id == CardId::SOVEREIGN_BLADE) {
        b.activePlay.card.bonusDamage += amount;
    }
    for (int i = 0; i < b.suspendedPlayCount; ++i) {
        if (b.suspendedPlays[i].play.card.id == CardId::SOVEREIGN_BLADE) {
            b.suspendedPlays[i].play.card.bonusDamage += amount;
        }
    }
}

// CardFactory.GetDistinctForCombat over ColorlessCardPool.GetUnlockedCards:
// distinct models passing FilterForCombat, then a single UnstableShuffle whose
// first `count` entries are taken (TakeRandom), consuming RNG for the whole
// pool exactly like the native call.
void regent_colorless_cards(BattleContext &b, int count, CardId *out, int &outN) {
    outN = 0;
    if (count <= 0) return;
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        const CardDef &d = card_def(id);
        if (d.pool != CardPool::COLORLESS) continue;
        if (!card_native_available(id)) continue;
        if (d.flags & (CF_MULTIPLAYER_ONLY | CF_CANNOT_GENERATE_IN_COMBAT)) continue;
        if (d.rarity == Rarity::BASIC || d.rarity == Rarity::ANCIENT ||
            d.rarity == Rarity::EVENT) continue;
        pool[n++] = id;
    }
    native_sort_card_ids(pool, n);
    b.cardGenerationRng.shuffle(pool, n);
    for (int k = 0; k < count && k < n; ++k) out[outN++] = pool[k];
}

void regent_generate_colorless(BattleContext &b, int count, bool upgraded) {
    CardId picks[static_cast<int>(CardId::COUNT)];
    int n = 0;
    regent_colorless_cards(b, count, picks, n);
    for (int i = 0; i < n; ++i) {
        Card generated = make_card(picks[i], upgraded, b.require_card_uid());
        b.add_card_to_hand(generated);
        b.notify_card_generated(generated);
    }
}

// SideTurnStart: per-turn history counters reset before energy and draw.
// VoidFormPower.BeforeSideTurnStart resets its manual-play counter here as well.
void regent_reset_turn(BattleContext &b) {
    RegentState &r = b.regent;
    r.starsGainedThisTurn = 0;
    r.cardsFinishedThisTurn = 0;
    r.skillsFinishedThisTurn = 0;
    for (int &hits : r.hitsGivenThisTurn) hits = 0;
    r.voidFormManualPlays = 0;
    // A Void Form EndTurn request never survives into the next turn.
    r.endTurnRequested = false;
}

// StarNextTurnPower.AfterEnergyReset: grant the stored stars once, then remove.
void regent_after_energy_reset(BattleContext &b) {
    const int n = b.player_power(PowerId::STAR_NEXT_TURN);
    if (n <= 0) return;
    regent_gain_stars(b, n);
    b.add_player_power(PowerId::STAR_NEXT_TURN, -n);
}

// SpectrumShiftPower.BeforeHandDraw: distinct colorless cards straight to hand.
void regent_before_hand_draw(BattleContext &b) {
    const int n = b.player_power(PowerId::SPECTRUM_SHIFT);
    if (n > 0) regent_generate_colorless(b, n);
}

// TyrannyPower.AfterPlayerTurnStart: exhaust Amount cards from hand. The grid
// auto-completes when the hand holds no more cards than the requested count.
void regent_after_player_turn_start(BattleContext &b) {
    const int n = b.player_power(PowerId::TYRANNY);
    if (n <= 0 || b.handCount == 0) return;
    Card source{};
    b.start_choice(ChoiceOp::EXHAUST, ChoicePile::HAND, std::min(n, b.handCount),
                   false, source, false);
}

// ReflectPower.AfterSideTurnStart: its one-turn duration ticks down at the
// start of the owner's side turn.
void regent_after_side_turn_start(BattleContext &b) {
    if (b.player_power(PowerId::REFLECT) > 0) b.add_player_power(PowerId::REFLECT, -1);
}

// AfterSideTurnEnd hooks. MonologuePower removes itself and gives back exactly
// the Strength it granted; PaleBlueDotPower re-arms for the next turn.
void regent_player_turn_end(BattleContext &b) {
    RegentState &r = b.regent;
    for (int i = 0; i < r.monologueCount; ++i) {
        if (r.monologueApplied[i] != 0) b.add_player_power(PowerId::STRENGTH, -r.monologueApplied[i]);
        b.add_player_power(PowerId::MONOLOGUE, -1);
        r.monologueAmounts[i] = 0;
        r.monologueApplied[i] = 0;
    }
    r.monologueCount = 0;
    r.paleBlueActivated = false;
}

// ConquerorPower.AfterSideTurnEnd: one stack per stack expires on each enemy
// side end (the power sits on the enemy, not the player).
void regent_enemy_turn_end(BattleContext &b) {
    for (int i = 0; i < b.monsterCount; ++i) {
        if (b.monsters[i].alive && b.monster_power(i, PowerId::CONQUEROR) > 0)
            b.add_monster_power(i, PowerId::CONQUEROR, -1);
    }
}

// TheSealedThronePower.BeforeCardPlayed grants stars for every play iteration.
// MonologuePower.BeforeCardPlayed snapshots each live instance's Strength value,
// so a Monologue applied during the play does not trigger for it.
void regent_before_card_played(BattleContext &b) {
    if (b.player_power(PowerId::THE_SEALED_THRONE) > 0)
        regent_gain_stars(b, b.player_power(PowerId::THE_SEALED_THRONE));
    RegentState &r = b.regent;
    for (int i = 0; i < MONOLOGUE_CAPACITY; ++i)
        b.activePlay.regent.monologue[i] = i < r.monologueCount ? r.monologueAmounts[i] : 0;
}

// AfterCardPlayed hooks, once per CardPlay iteration.
void regent_after_card_played(BattleContext &b, const Card &card) {
    RegentState &r = b.regent;
    const bool lastInSeries = b.activePlay.nextPlay >= b.activePlay.playCount;
    ++r.cardsFinishedThisTurn;
    if (card_is_skill(card)) ++r.skillsFinishedThisTurn;
    // MonologuePower.AfterCardPlayed: grant the snapshot Strength per instance.
    for (int i = 0; i < r.monologueCount && i < MONOLOGUE_CAPACITY; ++i) {
        const int amount = b.activePlay.regent.monologue[i];
        if (amount == 0) continue;
        b.add_player_power(PowerId::STRENGTH, amount);
        r.monologueApplied[i] += amount;
    }
    // BlackHolePower.AfterCardPlayed: triggers after a card that spent stars.
    if (lastInSeries && b.activePlay.starsSpent > 0 &&
        b.player_power(PowerId::BLACK_HOLE) > 0 && b.outcome == Outcome::UNDECIDED) {
        b.attack_all(b.player_power(PowerId::BLACK_HOLE), 1, false);
    }
    // PaleBlueDotPower.AfterCardPlayed: at five finished plays this turn, draw
    // next turn; once per turn.
    if (!r.paleBlueActivated && r.cardsFinishedThisTurn >= 5 &&
        b.player_power(PowerId::PALE_BLUE_DOT) > 0 &&
        b.outcome == Outcome::UNDECIDED) {
        r.paleBlueActivated = true;
        b.add_player_power(PowerId::DRAW_CARDS_NEXT_TURN, b.player_power(PowerId::PALE_BLUE_DOT));
    }
    // VoidFormPower.AfterCardPlayed: manual, last-in-series plays consume the
    // turn's free-card allowance.
    if (!b.activePlay.autoPlay && lastInSeries) ++r.voidFormManualPlays;
}

// SwordSagePower.AfterPowerAmountChanged adds ReplayCount to every Sovereign
// Blade already in combat. VoidFormPower's zero-cost visual runs the native
// HideTemporaryZeroCostVisual hack whenever its amount changes.
void regent_power_changed(BattleContext &b, PowerId power, int delta) {
    if (delta == 0) return;
    if (power == PowerId::SWORD_SAGE) each_blade(b, delta);
    if (power == PowerId::VOID_FORM) b.regent.voidFormManualPlays = 999999999;
}

// ArsenalPower.AfterCardGeneratedForCombat + the CardGenerated history that
// Supermassive counts (all player-created cards, for the whole combat).
void regent_card_generated(BattleContext &b, const Card &) {
    ++b.regent.generatedThisCombat;
    if (b.player_power(PowerId::ARSENAL) > 0)
        b.add_player_power(PowerId::STRENGTH, b.player_power(PowerId::ARSENAL));
}

// SwordSagePower.AfterCardEnteredCombat: a non-clone Sovereign Blade gains the
// power's ReplayCount when it enters combat.
void regent_card_entered_combat(BattleContext &b, Card &card, bool clone) {
    if (clone || card.id != CardId::SOVEREIGN_BLADE) return;
    const int n = b.player_power(PowerId::SWORD_SAGE);
    if (n > 0) card.bonusReplay = static_cast<std::uint8_t>(int(card.bonusReplay) + n);
}

// CardModel.GetStarCostWithModifiers. Star-X cards spend all current stars and
// bypass cost hooks; VoidFormPower.TryModifyStarCost zeroes the rest.
int regent_star_cost(const BattleContext &b, const Card &c) {
    const CardDef &d = card_def(c.id);
    const bool starX = c.upgraded ? (d.starCostXUp || d.starCostX) : d.starCostX;
    if (starX) return b.regent.stars;
    int cost = c.upgraded ? d.starCostUp : d.starCost;
    if (cost < 0) return cost;
    if (regent_void_form_free(b, c)) return 0;
    return std::max(0, cost);
}

// CardPlay.SpendEnergy -> OrbitPower.AfterEnergySpent. Each Orbit instance
// tracks its own lifetime energy total; every 4 energy grants its amount.
void regent_spend_energy(BattleContext &b, int amount) {
    if (amount <= 0) return;
    b.player.energy = std::max(0, b.player.energy - amount);
    RegentState &r = b.regent;
    for (int i = 0; i < r.orbitCount; ++i) {
        const int before = r.orbitEnergy[i];
        r.orbitEnergy[i] += amount;
        const int triggers = r.orbitEnergy[i] / 4 - before / 4;
        if (triggers > 0) b.player.energy += r.orbitAmounts[i] * triggers;
    }
}

// CardPlay.SpendStars -> ChildOfTheStarsPower.AfterStarsSpent: block equal to
// the power amount times the stars spent.
void regent_spend_stars(BattleContext &b, int amount) {
    if (amount <= 0) return;
    b.regent.stars = std::max(0, b.regent.stars - amount);
    relics_stars_spent(b, amount);
    const int n = b.player_power(PowerId::CHILD_OF_THE_STARS);
    if (n > 0) b.gain_block(n * amount, false, false);
}

// VoidFormPower.TryModify{Energy,Star}Cost: the first Amount manual plays of
// the turn cost nothing; auto-plays and cards outside hand/play are skipped.
bool regent_void_form_free(const BattleContext &b, const Card &) {
    const int n = b.player_power(PowerId::VOID_FORM);
    return n > 0 && b.regent.voidFormManualPlays < n;
}

// ReflectPower.AfterDamageReceived: damage the attacker for the blocked part of
// a powered attack. The reflect is Unpowered (blockable, no Strength).
void regent_reflect_block(BattleContext &b, int monsterIdx, int blocked) {
    if (blocked <= 0 || b.player_power(PowerId::REFLECT) <= 0) return;
    if (b.outcome != Outcome::UNDECIDED) return;
    b.damage_monster(monsterIdx, blocked, true, false);
}

}  // namespace sts2
