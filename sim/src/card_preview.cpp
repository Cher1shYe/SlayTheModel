// Observation checklist A1: native card display values (see card_preview.h).
//
// Ported from v0.111.0 (artifacts/native-source/v0.111.0/MegaCrit/sts2/Core):
//   Localization/DynamicVars/{DamageVar,BlockVar,CalculatedDamageVar,CalculatedBlockVar,CalculatedVar}.cs
//   Hooks/Hook.cs ModifyDamage / ModifyDamageInternal / ModifyBlock
//   Models/CardModel.cs UpdateDynamicVarPreview (runGlobalHooks only in Hand/Play)
//   every ModifyDamageAdditive / ModifyDamageMultiplicative / ModifyDamageCap /
//   ModifyBlockAdditive / ModifyBlockMultiplicative / Enchant* override reachable here.
// Native arithmetic is System.Decimal; it is exact for these magnitudes, so this file
// uses exact rationals (never float) and truncates once at the end like (int)PreviewValue.
#include "sts2/card_preview.h"
#include "sts2/exact.h"

#include <cmath>
#include <cstdint>
#include <numeric>
#include <stdexcept>

#include "sts2/necrobinder.h"
#include "sts2/regent.h"
#include "sts2/relics.h"
#include "sts2/silent.h"

namespace sts2 {
namespace {

// Shared exact rationals (sts2/exact.h), the same arithmetic as the engine's damage path.
using Q = Exact;
Q q(std::int64_t n, std::int64_t d = 1) { return Exact::of(n, d); }
Q add(Q a, Q b) { return a + b; }
Q mul(Q a, Q b) { return a * b; }
bool less(Q a, Q b) { return a < b; }
Q max0(Q a) { return a.n < 0 ? Q{} : a; }
int truncate(Q a) { return a.truncate(); }
Q from_double(double x) { return Exact::of_double(x); }

bool alive_target(const BattleContext &bc, int t) {
    return t >= 0 && t < bc.monsterCount && bc.monsters[t].alive;
}
int mpow(const Monster &m, PowerId id) { return m.power[static_cast<int>(id)]; }

// CalculatedVar.Calculate(target): base + extra * multiplier(card, target).
// `ok` is false for calculated cards whose multiplier is not ported here.
std::int64_t calculated_damage_base(const BattleContext &bc, const Card &card, int target, bool &ok) {
    ok = true;
    const std::int64_t base = card_var(card, VarId::CALC_BASE), extra = card_var(card, VarId::EXTRA_DAMAGE);
    switch (card.id) {
        case CardId::ASHEN_STRIKE:   // PileType.Exhaust.GetPile(owner).Cards.Count
            return base + extra * bc.exhaustCount;
        case CardId::BODY_SLAM:      // owner.Creature.Block
            return base + extra * bc.player.block;
        case CardId::BULLY:          // target?.GetPowerAmount<VulnerablePower>() ?? 0
            return base + extra * (target >= 0 && target < bc.monsterCount ? bc.monsters[target].vulnerable : 0);
        case CardId::GANG_UP:        // powered hits on the target this turn by *other* allies: none in single player
            return base;
        case CardId::GOLD_AXE:       // History.CardPlaysFinished.Count()
            return base + extra * bc.cardsFinishedThisCombat;
        case CardId::MIND_BLAST:     // Draw pile count
            return base + extra * bc.drawCount;
        case CardId::PERFECTED_STRIKE: {  // AllCards (Hand, Draw, Discard, Exhaust, Play) tagged Strike
            // The card itself is always in one of these natively (Hand, or Play while it
            // resolves); the engine holds a resolving card outside the piles.
            int strikes = 0;
            bool selfInPiles = false;
            const Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount, bc.exhaustCount, bc.playCount};
            for (int p = 0; p < 5; ++p)
                for (int i = 0; i < counts[p]; ++i) {
                    strikes += card_is_strike(piles[p][i]) ? 1 : 0;
                    selfInPiles |= piles[p][i].uid == card.uid;
                }
            if (!selfInPiles && card_is_strike(card)) ++strikes;
            return base + extra * strikes;
        }
        case CardId::REND:           // target?.Powers.Count(ShouldCountPower) ?? 0
            return base + extra * (target >= 0 && target < bc.monsterCount ? rend_debuff_count(bc.monsters[target]) : 0);
        default:
            ok = false;
            return 0;
    }
}

std::int64_t calculated_block_base(const BattleContext &bc, const Card &card, int target, bool &ok) {
    ok = true;
    const std::int64_t base = card_var(card, VarId::CALC_BASE), extra = card_var(card, VarId::CALC_EXTRA);
    switch (card.id) {
        case CardId::DEMONIC_SHIELD:  // owner.Creature.Block
            return base + extra * bc.player.block;
        case CardId::EXPECT_A_FIGHT:  // Math.Max(0, owner Strength)
            return base + extra * std::max(0, bc.player.strength);
        case CardId::MIMIC:           // target?.Block ?? 0 (AnyAlly: no other ally in single player)
            (void) target;
            return base;
        case CardId::STACK:           // Discard pile count
            return base + extra * bc.discardCount;
        case CardId::SOVEREIGN_BLADE: // GetOwnerParryAmount: owner ParryPower while the card is in a combat pile
            return base + extra * bc.player_power(PowerId::PARRY);
        default:
            ok = false;
            return 0;
    }
}

bool is_calculated_damage(CardId id) {
    switch (id) {
        case CardId::ASHEN_STRIKE: case CardId::BODY_SLAM: case CardId::BULLY: case CardId::CRESCENT_SPEAR:
        case CardId::DEATH_MARCH: case CardId::GANG_UP: case CardId::GOLD_AXE: case CardId::MEMENTO_MORI:
        case CardId::MIND_BLAST: case CardId::MURDER: case CardId::PERFECTED_STRIKE: case CardId::PRECISE_CUT:
        case CardId::PROTECTOR: case CardId::REND: case CardId::SOUL_STORM: case CardId::SQUEEZE:
        case CardId::SUPERMASSIVE: case CardId::TIMES_UP: case CardId::UNLEASH:
            return true;
        default:
            return false;
    }
}

bool is_calculated_block(CardId id) {
    switch (id) {
        case CardId::DEMONIC_SHIELD: case CardId::EXPECT_A_FIGHT: case CardId::MIMIC: case CardId::MIRAGE:
        case CardId::SACRIFICE: case CardId::SOVEREIGN_BLADE: case CardId::STACK:
            return true;
        default:
            return false;
    }
}

// Enchantment EnchantDamageAdditive then EnchantDamageMultiplicative (powered attack props).
Q enchant_damage(const Card &card, Q num) {
    switch (card.enchantment) {
        case EnchantmentId::SHARP: return add(num, q(card.enchantmentAmount));
        case EnchantmentId::VIGOROUS: return card.enchantmentDisabled ? num : add(num, q(card.enchantmentAmount));
        case EnchantmentId::MOMENTUM: return add(num, q(card.momentumExtraDamage));
        case EnchantmentId::TEZCATARAS_EMBER: return add(num, q(3));
        case EnchantmentId::INSTINCT: return mul(num, q(2));
        case EnchantmentId::CORRUPTED: return mul(num, q(3, 2));
        default: return num;
    }
}

// Goopy: Amount - 1; Nimble: Amount. No enchantment multiplies block.
Q enchant_block(const Card &card, Q num) {
    switch (card.enchantment) {
        case EnchantmentId::GOOPY: return add(num, q(card.enchantmentAmount - 1));
        case EnchantmentId::NIMBLE: return add(num, q(card.enchantmentAmount));
        default: return num;
    }
}

// Hook.ModifyDamageInternal(target, dealer = player, props = Move (powered attack),
// cardSource = card, cardPlay = null), after the card's own enchantment.
Q modify_damage(const BattleContext &bc, const Card &card, Q num, int target, bool inPlay) {
    // ---- additive (order irrelevant: exact sums)
    std::int64_t plus = bc.player.strength;                 // StrengthPower (Owner == dealer)
    plus += bc.player_power(PowerId::VIGOR);                // VigorPower (no command in progress)
    plus += static_cast<std::int64_t>(relics_damage_additive(bc, card));  // MysticLighter 9, Strike Dummy 3, Fake 1, Miniature Cannon 3
    num = add(num, q(plus));
    // Other characters' additive powers, reusing the engine helpers (cardPlay is null: no energy spent).
    num = add(num, from_double(silent_damage_additive(bc, &card, true)));  // Accuracy, Phantom Blades
    // OneForAllPower with cardPlay == null: not X-cost (engine cost < 0) and current cost (all modifiers) == 0.
    // (The engine's defect_damage_additive models the play-time EnergySpent branch instead.)
    if (bc.player_power(PowerId::ONE_FOR_ALL) != 0 && card_cost(card) >= 0 && bc.energy_cost_in_combat(card) == 0)
        num = add(num, q(bc.player_power(PowerId::ONE_FOR_ALL)));
    // ---- multiplicative
    if (bc.player.weak > 0) num = mul(num, q(3, 4));         // WeakPower DamageDecrease 0.75 (Paper Krane only when the player is the target)
    if (bc.player_power(PowerId::SHRINK) != 0) num = mul(num, q(7, 10));  // (100 - 30) / 100
    if (bc.player_power(PowerId::DOUBLE_DAMAGE) > 0) num = mul(num, q(2));
    if (bc.player_power(PowerId::GIGANTIFICATION) > 0) num = mul(num, q(3));  // commandToModify == null
    // PenNib: AttackToDouble == null -> x2 when AttacksPlayed == 9 and the card is not in Play;
    // otherwise only the attack being doubled (the card in Play during that play).
    const int nib = relic_has(bc, RelicId::PEN_NIB) ? relic_aux(bc, RelicId::PEN_NIB) : -1;
    if ((nib == 9 && !inPlay) || (nib == 100 && inPlay)) num = mul(num, q(2));
    if (alive_target(bc, target)) {
        const Monster &m = bc.monsters[target];
        if (m.vulnerable > 0) {                              // VulnerablePower 1.5 (+0.25 Paper Phrog, + Cruelty/100)
            Q v = q(3, 2);
            if (relic_has(bc, RelicId::PAPER_PHROG)) v = add(v, q(1, 4));
            v = add(v, q(bc.player_power(PowerId::CRUELTY), 100));
            num = mul(num, v);
        }
        if (mpow(m, PowerId::SOAR) > 0) num = mul(num, q(1, 2));     // DamageDecrease 50 / 100
        if (mpow(m, PowerId::FLUTTER) > 0) num = mul(num, q(1, 2));
        if (mpow(m, PowerId::COVERED) > 0) num = mul(num, q(0));
        if (mpow(m, PowerId::SLOW) > 0) num = mul(num, q(10 + m.slowCardsThisTurn, 10));  // 1 + 0.1 * SlowAmount
        num = mul(num, from_double(regent_damage_multiplier(bc, card, target)));
        num = mul(num, from_double(silent_damage_multiplier(bc, target, true)));  // Tracking
    }
    num = mul(num, from_double(necrobinder_damage_multiplier(bc, &card, target, true)));  // Lethality, Hang, Debilitate
    // ---- cap (IntangiblePower 1, HardToKillPower Amount)
    if (alive_target(bc, target)) {
        const Monster &m = bc.monsters[target];
        if (mpow(m, PowerId::INTANGIBLE) > 0 && less(q(1), num)) num = q(1);
        const int htk = mpow(m, PowerId::HARD_TO_KILL);
        if (htk > 0 && less(q(htk), num)) num = q(htk);
    }
    return num;
}

// Hook.ModifyBlock(target = player, props = Move, cardSource = card, cardPlay = null).
Q modify_block(const BattleContext &bc, const Card &card, Q num, bool inPlay) {
    num = enchant_block(card, num);
    std::int64_t plus = bc.player.dexterity;                 // DexterityPower (powered card block)
    if (card_is_defend(card)) plus += bc.player_power(PowerId::FASTEN);  // FastenPower: Defend-tagged cards
    num = add(num, q(plus));
    // UnmovablePower with cardPlay == null: x2 while fewer than Amount BlockGainedEntry
    // rows from card plays exist this turn (in Play, the card's own play is excluded).
    const int unmovable = bc.player_power(PowerId::UNMOVABLE);
    const int entries = bc.blockGainEntriesThisTurn - (inPlay ? bc.blockGainEntriesThisPlay : 0);
    if (unmovable > 0 && entries < unmovable) num = mul(num, q(2));
    num = mul(num, from_double(silent_block_multiplier(bc)));  // ShadowmeldPower 2^Amount
    if (bc.player.frail > 0) num = mul(num, q(3, 4));
    if (bc.player_power(PowerId::NO_BLOCK) > 0) num = mul(num, q(0));
    // Vambrace: x2 until block was gained this combat (TriggeringCard: the card in Play).
    if (relic_has(bc, RelicId::VAMBRACE)) {
        const int state = relic_aux(bc, RelicId::VAMBRACE);
        if (state == 0 || (state == 1 && inPlay)) num = mul(num, q(2));
    }
    if (relic_has(bc, RelicId::PAELS_LEGION) && relic_aux(bc, RelicId::PAELS_LEGION) <= 0) num = mul(num, q(2));
    return num;
}

}  // namespace

int card_preview_damage(const BattleContext &bc, const Card &card, int target, bool inHandOrPlay, bool inPlay) {
    Q num;
    if (is_calculated_damage(card.id)) {
        bool ok = false;
        const std::int64_t base = calculated_damage_base(bc, card, target, ok);
        if (!ok) return PREVIEW_UNSUPPORTED;
        // CalculatedDamageVar: global hooks (which apply the enchantment first) or,
        // outside Hand/Play, the enchanted calculation; then Math.Max(PreviewValue, 0).
        num = inHandOrPlay ? modify_damage(bc, card, enchant_damage(card, q(base)), target, inPlay)
                           : enchant_damage(card, q(base));
    } else {
        // DamageVar: BaseValue (base + permanent bonuses), same two paths. BaseValue is a decimal
        // and need not be integral: Thrash adds the hook-modified damage of the exhausted attack
        // (e.g. x0.75 under Weak), so a fractional base is exact native state, not an error.
        const double raw = card_base_damage(card);
        const Q base = raw == std::floor(raw) ? q(static_cast<std::int64_t>(raw)) : from_double(raw);
        num = inHandOrPlay ? modify_damage(bc, card, enchant_damage(card, base), target, inPlay)
                           : enchant_damage(card, base);
    }
    return truncate(max0(num));
}

int card_preview_block(const BattleContext &bc, const Card &card, int target, bool inHandOrPlay, bool inPlay) {
    std::int64_t base;
    if (is_calculated_block(card.id)) {
        bool ok = false;
        base = calculated_block_base(bc, card, target, ok);
        if (!ok) return PREVIEW_UNSUPPORTED;
    } else {
        base = card_block(card);
    }
    const Q num = inHandOrPlay ? modify_block(bc, card, q(base), inPlay) : enchant_block(card, q(base));
    return truncate(max0(num));
}

}  // namespace sts2
