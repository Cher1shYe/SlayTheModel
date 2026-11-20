// Observation checklist A1: card display values vs the v0.111.0 native preview rules.
//
// Every expected number below is derived by hand from the decompiled native code
// (DamageVar/BlockVar/Calculated*Var.UpdateCardPreview, Hook.ModifyDamage/ModifyBlock and
// the individual power/relic/enchantment hooks; System.Decimal arithmetic, truncated by
// DynamicVar's (int)PreviewValue). The derivation is written next to each check.
//
// Section 2 additionally plays each damage/block card on a copy of the battle and
// compares the engine's actual result with the preview. A difference there is reported
// as ENGINE (the preview follows native; the engine's play path may differ) and counted
// separately: it does not fail this test, but every one is listed in the output.
#include "sts2/battle.h"
#include "sts2/card_preview.h"
#include "sts2/relics.h"

#include <algorithm>
#include <cstring>
#include <iostream>
#include <string>

using namespace sts2;

namespace {

int failures = 0;
int engine_differences = 0;

void check(const std::string &name, int actual, int expected) {
    const bool ok = actual == expected;
    failures += ok ? 0 : 1;
    std::cout << (ok ? "PASS " : "FAIL ") << name << " expected=" << expected << " actual=" << actual << "\n";
}

BattleContext base() {
    BattleContext b;
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 4321, deck, 10, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.knownTopCount = 0;
    b.player.energy = 50;
    b.player.block = 0;
    b.relicCount = 0;
    for (int i = 0; i < b.monsterCount; ++i) {
        Monster &m = b.monsters[i];
        std::fill(std::begin(m.power), std::end(m.power), 0);
        m.strength = m.vulnerable = m.weak = 0;
        m.hp = m.maxHp = 10000;
        m.block = 0;
        m.slowCardsThisTurn = 0;
    }
    return b;
}

Card &hand(BattleContext &b, CardId id, bool up = false) {
    b.hand[b.handCount] = make_card(id, up, b.nextUid++);
    return b.hand[b.handCount++];
}

void relic(BattleContext &b, RelicId id, int aux = 0) {
    b.relics[b.relicCount] = static_cast<int>(id);
    b.relicAux[b.relicCount++] = aux;
}

int dmg(const BattleContext &b, int handIdx, int target) {
    return card_preview_damage(b, b.hand[handIdx], target, true, false);
}
int blk(const BattleContext &b, int handIdx) { return card_preview_block(b, b.hand[handIdx], -1, true, false); }

// Plays hand[handIdx] on monster 0 in a copy; returns monster 0's (hp + block) loss.
int engine_damage(const BattleContext &b, int handIdx) {
    BattleContext c = b;
    const int before = c.monsters[0].hp + c.monsters[0].block;
    if (!c.play_card(handIdx, 0)) return -1;
    return before - (c.monsters[0].hp + c.monsters[0].block);
}
int engine_block(const BattleContext &b, int handIdx) {
    BattleContext c = b;
    const int before = c.player.block;
    if (!c.play_card(handIdx, 0)) return -1;
    return c.player.block - before;
}

void engine(const std::string &name, int actual, int preview) {
    if (actual == preview) {
        std::cout << "  engine agrees: " << name << " = " << actual << "\n";
        return;
    }
    ++engine_differences;
    std::cout << "  ENGINE " << name << " preview(native)=" << preview << " engine=" << actual << "\n";
}

// ------------------------------------------------------------------ 1. native values

void damage_modifiers() {
    {   // DamageVar: BaseValue 6, nothing else.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        check("strike_plain_untargeted", dmg(b, 0, -1), 6);
        check("strike_plain_targeted", dmg(b, 0, 0), 6);
        engine("strike_plain", engine_damage(b, 0), 6);
    }
    {   // Strength +2 (additive), Weak x0.75: untargeted (6+2)*0.75 = 6; target Vulnerable x1.5: 8*0.75*1.5 = 9.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.strength = 2; b.player.weak = 1; b.monsters[0].vulnerable = 2;
        check("str_weak_untargeted", dmg(b, 0, -1), 6);
        check("str_weak_vulnerable", dmg(b, 0, 0), 9);
        engine("str_weak_vulnerable", engine_damage(b, 0), 9);
    }
    {   // Paper Phrog: Vulnerable 1.5 + 0.25. (6+3)*0.75*1.75 = 11.8125 -> 11.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD); relic(b, RelicId::PAPER_PHROG);
        b.player.strength = 3; b.player.weak = 1; b.monsters[0].vulnerable = 1;
        check("paper_phrog", dmg(b, 0, 0), 11);
        engine("paper_phrog", engine_damage(b, 0), 11);
    }
    {   // Cruelty 25: Vulnerable 1.5 + 25/100 = 1.75. 6 * 1.75 = 10.5 -> 10.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::CRUELTY)] = 25; b.monsters[0].vulnerable = 1;
        check("cruelty", dmg(b, 0, 0), 10);
        engine("cruelty", engine_damage(b, 0), 10);
    }
    {   // Shrink (-1 = permanent, Shrinker Beetle): (100-30)/100. (6+24)*0.7 = 21 exactly in decimal.
        // (In binary floating point 30*0.7 = 20.999999999999996, which floors to 20.)
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.strength = 24; b.player.power[static_cast<int>(PowerId::SHRINK)] = -1;
        check("shrink_exact_decimal", dmg(b, 0, 0), 21);
        engine("shrink_exact_decimal", engine_damage(b, 0), 21);
        b.player.strength = 4; b.player.weak = 1; b.monsters[0].vulnerable = 1;  // 10*0.7*0.75*1.5 = 7.875
        check("shrink_weak_vulnerable", dmg(b, 0, 0), 7);
        engine("shrink_weak_vulnerable", engine_damage(b, 0), 7);
    }
    {   // Vigor 5 is additive in the preview (no AttackCommand in progress): 6+5 = 11.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::VIGOR)] = 5;
        check("vigor", dmg(b, 0, -1), 11);
        engine("vigor", engine_damage(b, 0), 11);
    }
    {   // Pen Nib AttacksPlayed == 9 and the card is not in Play: x2 -> 12. In Play: x1 -> 6.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD); relic(b, RelicId::PEN_NIB, 9);
        check("pen_nib_hand", dmg(b, 0, -1), 12);
        check("pen_nib_card_in_play_not_doubled", card_preview_damage(b, b.hand[0], -1, true, true), 6);
        engine("pen_nib", engine_damage(b, 0), 12);
        relic_aux_set(b, RelicId::PEN_NIB, 8);
        check("pen_nib_count_8", dmg(b, 0, -1), 6);
    }
    {   // Strike Dummy +3 on Strike-tagged cards only; Bash has no tag.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD); hand(b, CardId::BASH); relic(b, RelicId::STRIKE_DUMMY);
        check("strike_dummy_strike", dmg(b, 0, -1), 9);
        check("strike_dummy_bash", dmg(b, 1, -1), 8);
        engine("strike_dummy_strike", engine_damage(b, 0), 9);
    }
    {   // Miniature Cannon +3 on upgraded cards: Strike+ 9 + 3 = 12; unupgraded 6.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD, true); hand(b, CardId::STRIKE_IRONCLAD);
        relic(b, RelicId::MINIATURE_CANNON);
        check("miniature_cannon_upgraded", dmg(b, 0, -1), 12);
        check("miniature_cannon_plain", dmg(b, 1, -1), 6);
        engine("miniature_cannon_upgraded", engine_damage(b, 0), 12);
    }
    {   // Enchantment runs first inside Hook.ModifyDamage: Corrupted 6*1.5 = 9, then Strength +2 = 11
        // (not (6+2)*1.5 = 12). Outside Hand/Play only the enchantment applies: 9.
        auto b = base(); Card &c = hand(b, CardId::STRIKE_IRONCLAD);
        c.enchantment = EnchantmentId::CORRUPTED; b.player.strength = 2;
        check("corrupted_before_strength", dmg(b, 0, -1), 11);
        check("corrupted_outside_hand", card_preview_damage(b, b.hand[0], -1, false, false), 9);
        engine("corrupted_before_strength", engine_damage(b, 0), 11);
    }
    {   // Sharp +2 enchantment, Mystic Lighter +9 for an enchanted card: 6+2+9 = 17.
        auto b = base(); Card &c = hand(b, CardId::STRIKE_IRONCLAD);
        c.enchantment = EnchantmentId::SHARP; c.enchantmentAmount = 2; relic(b, RelicId::MYSTIC_LIGHTER);
        check("sharp_mystic_lighter", dmg(b, 0, -1), 17);
        engine("sharp_mystic_lighter", engine_damage(b, 0), 17);
    }
    {   // Double Damage x2 and Gigantification x3: 6*2*3 = 36.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::DOUBLE_DAMAGE)] = 1;
        b.player.power[static_cast<int>(PowerId::GIGANTIFICATION)] = 1;
        check("double_gigantification", dmg(b, 0, -1), 36);
        engine("double_gigantification", engine_damage(b, 0), 36);
    }
    {   // Target-side: Covered x0, Intangible cap 1, Hard To Kill cap Amount, Soar/Flutter x0.5, Slow 1 + 0.1n.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD); b.player.strength = 4;  // 10 before target modifiers
        Monster &m = b.monsters[0];
        m.power[static_cast<int>(PowerId::COVERED)] = 1;
        check("covered", dmg(b, 0, 0), 0);
        check("covered_not_untargeted", dmg(b, 0, -1), 10);
        m.power[static_cast<int>(PowerId::COVERED)] = 0;
        m.power[static_cast<int>(PowerId::INTANGIBLE)] = 1;
        check("intangible_cap", dmg(b, 0, 0), 1);
        m.power[static_cast<int>(PowerId::INTANGIBLE)] = 0;
        m.power[static_cast<int>(PowerId::HARD_TO_KILL)] = 5;
        check("hard_to_kill_cap", dmg(b, 0, 0), 5);
        m.power[static_cast<int>(PowerId::HARD_TO_KILL)] = 0;
        m.power[static_cast<int>(PowerId::SOAR)] = 1;
        check("soar", dmg(b, 0, 0), 5);
        m.power[static_cast<int>(PowerId::SOAR)] = 0;
        m.power[static_cast<int>(PowerId::FLUTTER)] = 1;
        check("flutter", dmg(b, 0, 0), 5);
        engine("flutter", engine_damage(b, 0), 5);
        m.power[static_cast<int>(PowerId::FLUTTER)] = 0;
        m.power[static_cast<int>(PowerId::SLOW)] = 1; m.slowCardsThisTurn = 3;
        check("slow_three_cards", dmg(b, 0, 0), 13);  // 10 * 1.3
        engine("slow_three_cards", engine_damage(b, 0), 13);
    }
    {   // Decimal vs binary floating point: (6+9) * 3 (Gigantification) * 1.4 (Slow, 4 cards) = 63 exactly
        // in decimal; 15.0*3*1.4 = 62.99999999999999 in double.
        auto b = base(); hand(b, CardId::STRIKE_IRONCLAD); b.player.strength = 9;
        b.player.power[static_cast<int>(PowerId::GIGANTIFICATION)] = 1;
        b.monsters[0].power[static_cast<int>(PowerId::SLOW)] = 1; b.monsters[0].slowCardsThisTurn = 4;
        check("decimal_gigantification_slow", dmg(b, 0, 0), 63);
        engine("decimal_gigantification_slow", engine_damage(b, 0), 63);
    }
    {   // One For All (cardPlay == null branch): current cost must be 0. Anger (0) 6+4 = 10, Strike (1) 6.
        auto b = base(); hand(b, CardId::ANGER); hand(b, CardId::STRIKE_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::ONE_FOR_ALL)] = 4;
        check("one_for_all_zero_cost", dmg(b, 0, -1), 10);
        check("one_for_all_cost_one", dmg(b, 1, -1), 6);
    }
}

void calculated_damage() {
    {   // Perfected Strike: 6 + 2 * (Strike-tagged cards in Hand/Draw/Discard/Exhaust/Play, itself included).
        // Hand: PS, Strike; Draw: Strike; Discard: Defend; Exhaust: Strike -> 4 -> 6 + 8 = 14.
        auto b = base(); hand(b, CardId::PERFECTED_STRIKE); hand(b, CardId::STRIKE_IRONCLAD);
        b.draw[b.drawCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        b.discard[b.discardCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        b.exhaust[b.exhaustCount++] = make_card(CardId::STRIKE_IRONCLAD, false, b.nextUid++);
        check("perfected_strike", dmg(b, 0, -1), 14);
        engine("perfected_strike", engine_damage(b, 0), 14);
    }
    {   // Body Slam: 0 + 1 * Block 7 = 7; with Strength 2 -> 9.
        auto b = base(); hand(b, CardId::BODY_SLAM); b.player.block = 7; b.player.strength = 2;
        check("body_slam", dmg(b, 0, -1), 9);
        engine("body_slam", engine_damage(b, 0), 9);
    }
    {   // Bully: 4 + 2 * target Vulnerable. Untargeted: 4. Target Vulnerable 3: (4+6) * 1.5 = 15.
        auto b = base(); hand(b, CardId::BULLY); b.monsters[0].vulnerable = 3;
        check("bully_untargeted", dmg(b, 0, -1), 4);
        check("bully_targeted", dmg(b, 0, 0), 15);
        engine("bully_targeted", engine_damage(b, 0), 15);
    }
    {   // Rend: 10 + 5 * debuffs. Target with Vulnerable, Weak, negative Strength: 3 -> 25 * 1.5 = 37.5 -> 37.
        auto b = base(); hand(b, CardId::REND);
        b.monsters[0].vulnerable = 1; b.monsters[0].weak = 1; b.monsters[0].strength = -2;
        check("rend_untargeted", dmg(b, 0, -1), 10);
        check("rend_targeted", dmg(b, 0, 0), 37);
        engine("rend_targeted", engine_damage(b, 0), 37);
    }
    {   // Ashen Strike 6 + 3 * Exhaust (2) = 12; Mind Blast 0 + Draw (5) = 5; Gold Axe 0 + plays finished (4) = 4.
        auto b = base(); hand(b, CardId::ASHEN_STRIKE); hand(b, CardId::MIND_BLAST); hand(b, CardId::GOLD_AXE);
        for (int i = 0; i < 2; ++i) b.exhaust[b.exhaustCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        for (int i = 0; i < 5; ++i) b.draw[b.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        b.cardsFinishedThisCombat = 4;
        check("ashen_strike", dmg(b, 0, -1), 12);
        check("mind_blast", dmg(b, 1, -1), 5);
        check("gold_axe", dmg(b, 2, -1), 4);
        engine("ashen_strike", engine_damage(b, 0), 12);
        engine("mind_blast", engine_damage(b, 1), 5);
        engine("gold_axe", engine_damage(b, 2), 4);
    }
    {   // Gang Up: hits on the target by *other* allies this turn; none in single player -> 5.
        auto b = base(); hand(b, CardId::GANG_UP);
        check("gang_up_single_player", dmg(b, 0, 0), 5);
    }
    {   // Other characters' calculated damage (e.g. Murder) is not ported: explicit unsupported.
        auto b = base(); hand(b, CardId::MURDER);
        check("murder_unsupported", dmg(b, 0, 0), PREVIEW_UNSUPPORTED);
    }
}

void block_modifiers() {
    {   // Defend 5 + Dexterity 2 = 7; Frail x0.75 -> 5.25 -> 5.
        auto b = base(); hand(b, CardId::DEFEND_IRONCLAD); b.player.dexterity = 2; b.player.frail = 1;
        check("defend_dex_frail", blk(b, 0), 5);
        engine("defend_dex_frail", engine_block(b, 0), 5);
    }
    {   // Unmovable 1 with no block-gaining play yet this turn: x2 -> 10; after one such play: 5.
        auto b = base(); hand(b, CardId::DEFEND_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::UNMOVABLE)] = 1;
        check("unmovable_first", blk(b, 0), 10);
        engine("unmovable_first", engine_block(b, 0), 10);
        b.blockGainEntriesThisTurn = 1;
        check("unmovable_used", blk(b, 0), 5);
    }
    {   // Unmovable counts BlockGainedEntry rows from *other* card plays (native), not plays.
        // Amount 2. Play A gains block twice: both gains are doubled (0 rows from other plays).
        // Play B: 2 rows from play A -> not doubled. (Counting plays would still double: 1 < 2.)
        auto b = base(); hand(b, CardId::DEFEND_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::UNMOVABLE)] = 2;
        b.blockGainEntriesThisPlay = 0;           // play A starts
        b.gain_block(5, true); b.gain_block(5, true);
        check("unmovable_same_play_both_doubled", b.player.block, 20);
        check("unmovable_entries_counted", b.blockGainEntriesThisTurn, 2);
        b.blockGainEntriesThisPlay = 0;           // play B starts
        const int before = b.player.block;
        b.gain_block(5, true);
        check("unmovable_second_play_not_doubled", b.player.block - before, 5);
        check("unmovable_preview_after_two_entries", blk(b, 0), 5);
        // A zero-amount gain records no entry (CreatureCmd.GainBlock: only when > 0).
        b.player.power[static_cast<int>(PowerId::NO_BLOCK)] = 1;
        b.gain_block(5, true);
        check("unmovable_zero_gain_no_entry", b.blockGainEntriesThisTurn, 3);
    }
    {   // No Block: x0. Vambrace before any block this combat: x2. Pael's Legion off cooldown: x2.
        auto b = base(); hand(b, CardId::DEFEND_IRONCLAD);
        b.player.power[static_cast<int>(PowerId::NO_BLOCK)] = 1;
        check("no_block", blk(b, 0), 0);
        engine("no_block", engine_block(b, 0), 0);
        b.player.power[static_cast<int>(PowerId::NO_BLOCK)] = 0;
        relic(b, RelicId::VAMBRACE, 0);
        check("vambrace_first", blk(b, 0), 10);
        engine("vambrace_first", engine_block(b, 0), 10);
        relic_aux_set(b, RelicId::VAMBRACE, 2);
        check("vambrace_used", blk(b, 0), 5);
    }
    {   // Fasten 3: Defend-tagged cards only. Defend 5+3 = 8; Shrug It Off 8 stays 8.
        auto b = base(); hand(b, CardId::DEFEND_IRONCLAD); hand(b, CardId::SHRUG_IT_OFF);
        b.player.power[static_cast<int>(PowerId::FASTEN)] = 3;
        check("fasten_defend", blk(b, 0), 8);
        check("fasten_not_defend", blk(b, 1), 8);
    }
    {   // Calculated block: Expect a Fight 15 + 5 * max(0, Strength 2) = 25, + Dexterity 1 = 26.
        // Stack 0 + Discard (4) = 4 (+1 = 5). Demonic Shield 0 + own Block 6 = 6 (+1 = 7).
        auto b = base(); hand(b, CardId::EXPECT_A_FIGHT); hand(b, CardId::STACK); hand(b, CardId::DEMONIC_SHIELD);
        b.player.strength = 2; b.player.dexterity = 1; b.player.block = 6;
        for (int i = 0; i < 4; ++i) b.discard[b.discardCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.nextUid++);
        check("expect_a_fight", blk(b, 0), 26);
        check("stack", blk(b, 1), 5);
        check("demonic_shield", blk(b, 2), 7);
        engine("expect_a_fight", engine_block(b, 0), 26);
        engine("stack", engine_block(b, 1), 5);
    }
    {   // Negative Strength on Expect a Fight counts as 0: 15.
        auto b = base(); hand(b, CardId::EXPECT_A_FIGHT); b.player.strength = -3;
        check("expect_a_fight_negative_strength", blk(b, 0), 15);
    }
}

}  // namespace

int main() {
    damage_modifiers();
    calculated_damage();
    block_modifiers();
    std::cout << "card_preview_native: " << failures << " failures, " << engine_differences
              << " engine differences (listed above as ENGINE)\n";
    return failures == 0 ? 0 : 1;
}
