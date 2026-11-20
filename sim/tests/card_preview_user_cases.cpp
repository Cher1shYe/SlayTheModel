// User-specified A1 synchronisation cases (2026-11-19). Each case plays the real cards
// through the engine, then compares (a) the card preview, (b) the result of actually
// playing the card, and (c) the value derived by hand from the v0.111.0 decompiled source:
//   1. Cruelty / Cruelty+ (CrueltyPower 25 / 50), enemy Vulnerable 0..5, no relics:
//      Strike, Strike+, Bully, Bully+.
//   2. Feel No Pain / Feel No Pain+ (3 / 4), Second Wind / Second Wind+ (5 / 7) exhausting
//      4 non-Attack cards from hand.
//   3. Regent: Sword Sage, Parry / Parry+ (10 / 14), Refine Blade / Refine Blade+ (Forge
//      8 / 12) forging a Sovereign Blade once, played once on an enemy without powers.
// (c) is a source derivation, not a DLL trace (no game install on this machine).
#include "sts2/battle.h"
#include "sts2/card_preview.h"

#include <algorithm>
#include <iostream>
#include <string>

using namespace sts2;

namespace {

int failures = 0;

void check(const std::string &name, int actual, int expected) {
    const bool ok = actual == expected;
    failures += ok ? 0 : 1;
    std::cout << (ok ? "PASS " : "FAIL ") << name << " expected=" << expected << " actual=" << actual << "\n";
}

BattleContext base() {
    BattleContext b;
    Card deck[10];
    for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 7777, deck, 10, 0, 500, 500);
    b.handCount = b.drawCount = b.discardCount = b.exhaustCount = 0;
    b.knownTopCount = 0;
    b.player.energy = 50;
    b.player.block = 0;
    b.relicCount = 0;  // "no relics"
    for (int i = 0; i < b.monsterCount; ++i) {
        Monster &m = b.monsters[i];
        std::fill(std::begin(m.power), std::end(m.power), 0);
        m.strength = m.vulnerable = m.weak = 0;
        m.hp = m.maxHp = 10000;
        m.block = 0;
    }
    return b;
}

void give(BattleContext &b, CardId id, bool up) { b.hand[b.handCount++] = make_card(id, up, b.nextUid++); }

int find(const BattleContext &b, CardId id, bool up) {
    for (int i = 0; i < b.handCount; ++i)
        if (b.hand[i].id == id && b.hand[i].upgraded == up) return i;
    return -1;
}

bool play(BattleContext &b, CardId id, bool up, int target = 0) {
    const int i = find(b, id, up);
    return i >= 0 && b.play_card(i, target);
}

struct Played { int damage; int block; };
// Play a copy; damage = monster 0 (hp + block) loss, block = player block gained.
Played played(const BattleContext &b, CardId id, bool up) {
    BattleContext c = b;
    const int hp = c.monsters[0].hp + c.monsters[0].block, block = c.player.block;
    if (!play(c, id, up)) return {-1, -1};
    return {hp - (c.monsters[0].hp + c.monsters[0].block), c.player.block - block};
}

// ---------------------------------------------------------------- case 1

void cruelty_case(const char *label, bool cruelty, bool crueltyPlus, int vulnerable) {
    auto b = base();
    if (cruelty) give(b, CardId::CRUELTY_CARD, false);
    if (crueltyPlus) give(b, CardId::CRUELTY_CARD, true);
    for (bool up : {false, true}) { give(b, CardId::STRIKE_IRONCLAD, up); give(b, CardId::BULLY, up); }
    if (cruelty) play(b, CardId::CRUELTY_CARD, false);
    if (crueltyPlus) play(b, CardId::CRUELTY_CARD, true);
    b.monsters[0].vulnerable = vulnerable;
    // Native: Bully = CalculationBase 4 + ExtraDamage (2 / 3) * target Vulnerable stacks.
    // VulnerablePower (only while it has stacks): x(1.5 + CrueltyPower.Amount / 100), Cruelty 25 / Cruelty+ 50
    // (stacking). Decimal product truncated: floor(base * (150 + cruelty) / 100) in integers.
    const int crueltyAmount = (cruelty ? 25 : 0) + (crueltyPlus ? 50 : 0);
    auto expected = [&](int printed) { return vulnerable > 0 ? printed * (150 + crueltyAmount) / 100 : printed; };
    const std::string p = std::string("1_") + label + "_vuln" + std::to_string(vulnerable) + "_";
    const struct { const char *name; CardId id; bool up; int printed; } rows[] = {
        {"strike", CardId::STRIKE_IRONCLAD, false, 6}, {"strike+", CardId::STRIKE_IRONCLAD, true, 9},
        {"bully", CardId::BULLY, false, 4 + 2 * vulnerable}, {"bully+", CardId::BULLY, true, 4 + 3 * vulnerable}};
    for (const auto &r : rows) {
        const int i = find(b, r.id, r.up);
        check(p + r.name + "_native", card_preview_damage(b, b.hand[i], 0, true, false), expected(r.printed));
        check(p + r.name + "_played", played(b, r.id, r.up).damage, expected(r.printed));
    }
}

void case1() {
    // Hand-checked anchors at Vulnerable 4: Cruelty 10/15/21/28, Cruelty+ 12/18/24/32, both 13/20/27/36.
    for (int v = 0; v <= 5; ++v) {
        cruelty_case("cruelty", true, false, v);
        cruelty_case("cruelty+", false, true, v);
        cruelty_case("both", true, true, v);
    }
}

// ---------------------------------------------------------------- case 2

void second_wind_case(bool fnpUp, bool swUp, int perCard, int total) {
    auto b = base();
    give(b, CardId::FEEL_NO_PAIN_CARD, fnpUp);
    give(b, CardId::SECOND_WIND, swUp);
    // Four non-Attack cards (Skill, Skill, Power, Status) and one Attack that must stay.
    give(b, CardId::DEFEND_IRONCLAD, false); give(b, CardId::SHRUG_IT_OFF, false);
    give(b, CardId::INFLAME, false); give(b, CardId::WOUND, false);
    give(b, CardId::STRIKE_IRONCLAD, false);
    play(b, CardId::FEEL_NO_PAIN_CARD, fnpUp);
    const std::string p = std::string("2_fnp") + (fnpUp ? "+" : "") + "_sw" + (swUp ? "+" : "") + "_";
    // Second Wind shows its BlockVar: 5 / 7 (no Dexterity/Frail here).
    check(p + "preview_block_per_card", card_preview_block(b, b.hand[find(b, CardId::SECOND_WIND, swUp)], -1, true, false), perCard);
    BattleContext c = b;
    const int before = c.player.block;
    play(c, CardId::SECOND_WIND, swUp);
    // SecondWind.OnPlay: for each non-Attack card in hand, Exhaust (Feel No Pain: +3/+4
    // Unpowered block) then GainBlock(Block, Move). 4 cards -> 4 * (FNP + Block).
    check(p + "total_block", c.player.block - before, total);
    check(p + "exhausted", c.exhaustCount, 4);
    check(p + "attack_kept", c.handCount == 1 && c.hand[0].id == CardId::STRIKE_IRONCLAD ? 1 : 0, 1);
}

void case2() {
    second_wind_case(false, false, 5, 4 * (3 + 5));   // 32
    second_wind_case(false, true, 7, 4 * (3 + 7));    // 40
    second_wind_case(true, false, 5, 4 * (4 + 5));    // 36
    second_wind_case(true, true, 7, 4 * (4 + 7));     // 44
}

// ---------------------------------------------------------------- case 3

void blade_case(const char *label, bool parry, bool parryPlus, bool refineUp, int damagePerPlay, int parryAmount) {
    auto b = base();
    give(b, CardId::SWORD_SAGE, false);
    if (parry) give(b, CardId::PARRY, false);
    if (parryPlus) give(b, CardId::PARRY, true);
    give(b, CardId::REFINE_BLADE, refineUp);
    play(b, CardId::SWORD_SAGE, false);
    if (parry) play(b, CardId::PARRY, false);
    if (parryPlus) play(b, CardId::PARRY, true);
    play(b, CardId::REFINE_BLADE, refineUp);  // ForgeCmd.Forge: no blade yet -> create one in hand, then +Forge
    const int i = find(b, CardId::SOVEREIGN_BLADE, false);
    const std::string p = std::string("3_") + label + "_";
    check(p + "blade_created", i >= 0 ? 1 : 0, 1);
    if (i < 0) return;
    // Sword Sage: AfterCardEnteredCombat adds Amount (1) replays to the new blade.
    check(p + "blade_replays", b.hand[i].replay + b.hand[i].bonusReplay, 1);
    // DamageVar 10 + Forge (AddDamage): 18 / 22 per play; enemy has no powers.
    check(p + "preview_damage", card_preview_damage(b, b.hand[i], 0, true, false), damagePerPlay);
    // CalculatedBlock = 0 + 1 * ParryPower (in a combat pile): 10 / 14 / 24.
    check(p + "preview_block", card_preview_block(b, b.hand[i], -1, true, false), parryAmount);
    // Played once = 2 plays (1 replay): damage 2 * per play, block 2 * Parry.
    const Played r = played(b, CardId::SOVEREIGN_BLADE, false);
    check(p + "played_damage", r.damage, 2 * damagePerPlay);
    check(p + "played_block", r.block, 2 * parryAmount);
}

void case3() {
    blade_case("parry_refine", true, false, false, 18, 10);
    blade_case("parry+_refine", false, true, false, 18, 14);
    blade_case("parry_refine+", true, false, true, 22, 10);
    blade_case("parry+_refine+", false, true, true, 22, 14);
    blade_case("both_parries_refine", true, true, false, 18, 24);
}

}  // namespace

int main() {
    case1();
    case2();
    case3();
    std::cout << "card_preview_user_cases: " << failures << " failures\n";
    return failures == 0 ? 0 : 1;
}
