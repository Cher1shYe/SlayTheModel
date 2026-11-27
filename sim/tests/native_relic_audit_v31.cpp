// v31 (DEVLOG 58): relic and card line-by-line audit against the v0.111.0 decompilation. One case per
// corrected relic; each is chosen so the pre-v31 code gives a different result.
#include "sts2/run.h"
#include "sts2/relics.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <string>

using namespace sts2;

namespace {
int failures = 0;
void check(const char *name, bool ok) {
    if (!ok) { ++failures; std::cout << "FAIL " << name << "\n"; }
}
std::unique_ptr<RunContext> fight(std::initializer_list<RelicId> relics, const std::string &seed = "V31AUDIT") {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->screen = RunScreen::MAP;
    for (RelicId id : relics) assert(r->add_relic(id));
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    return r;
}

// Hook.ModifyHpLost(AfterOsty) visits relics in bar order: Remnant (cap 20) then Rod (-1) gives
// 19 for a 25-point hit; Rod first gives 20. Pre-v31 was always Rod first.
void rod_and_remnant_follow_bar_order() {
    auto a = fight({RelicId::BEATING_REMNANT, RelicId::TUNGSTEN_ROD});
    a->battle.hpLostThisTurn = 0;
    check("Remnant before Rod: 25 -> 19", relics_modify_hp_loss(a->battle, 25) == 19);
    auto b = fight({RelicId::TUNGSTEN_ROD, RelicId::BEATING_REMNANT});
    b->battle.hpLostThisTurn = 0;
    check("Rod before Remnant: 25 -> 20", relics_modify_hp_loss(b->battle, 25) == 20);
}

// MerchantCardEntry.Populate runs Hook.ModifyMerchantCardCreationResults: Molten Egg shows the
// shop's Attacks upgraded. Buying Toxic Egg in the shop (UpdateEntries) upgrades its Skills.
void eggs_upgrade_shop_cards() {
    auto r = std::make_unique<RunContext>();
    r->init_seed("V31SHOP", 10);
    assert(r->add_relic(RelicId::MOLTEN_EGG));
    r->roll_shop();
    r->screen = RunScreen::SHOP;
    int attacks = 0, upgraded = 0;
    for (int i = 0; i < r->shopCount; ++i) {
        if (card_type(r->shopCards[i]) != CardType::ATTACK) continue;
        ++attacks;
        upgraded += r->shopCards[i].upgraded;
    }
    check("shop has Attacks", attacks > 0);
    check("Molten Egg: every stocked Attack is upgraded", upgraded == attacks);
    r->shopRelics[0] = static_cast<int>(RelicId::TOXIC_EGG);
    r->shopRelicSold[0] = false;
    r->shopRelicPrices[0] = 1;
    r->gold = 999;
    int skills = 0;
    for (int i = 0; i < r->shopCount; ++i) skills += card_type(r->shopCards[i]) == CardType::SKILL;
    check("buy Toxic Egg in the shop", r->step(RunAction{RunActionType::BUY_RELIC, 0}));
    int skillsUp = 0;
    for (int i = 0; i < r->shopCount; ++i)
        skillsUp += card_type(r->shopCards[i]) == CardType::SKILL && r->shopCards[i].upgraded;
    check("shop has Skills", skills > 0);
    check("Toxic Egg bought in the shop upgrades the stocked Skills", skillsUp == skills);
}

// RingingTriangle.ShouldFlush: the turn-1 hand is kept, without a RetainHand power. Pre-v31 it
// was RetainHand 1: visible in the observation, and a card's RetainHand stacked to 2 turns.
void ringing_triangle_is_not_a_power() {
    auto r = fight({RelicId::RINGING_TRIANGLE});
    BattleContext &b = r->battle;
    check("no RetainHand power on turn 1", b.player_power(PowerId::RETAIN_HAND) == 0);
    b.add_player_power(PowerId::RETAIN_HAND, 1);    // as Well-Laid-type cards do
    const int hand1 = b.handCount;
    check("end turn 1", b.step(Action{ActionType::END_TURN, 0, 0, 0}));
    check("turn-1 hand retained", b.turn == 2 && b.handCount > hand1);
    check("card RetainHand consumed", b.player_power(PowerId::RETAIN_HAND) == 0);
    check("end turn 2", b.step(Action{ActionType::END_TURN, 0, 0, 0}));
    check("turn-2 hand flushed (turn 3 holds only the 5 drawn cards)", b.turn == 3 && b.handCount == 5);
}

// SneckoEye / FakeSneckoEye.BeforeCombatStart: PowerCmd.Apply<ConfusedPower>(1) (Single).
void snecko_eye_applies_confused() {
    auto r = fight({RelicId::SNECKO_EYE, RelicId::FAKE_SNECKO_EYE});
    check("Confused from both relics (a Single power still adds Amount)", r->battle.player_power(PowerId::CONFUSED) == 2);
    auto plain = fight({});
    check("no Confused without the relic", plain->battle.player_power(PowerId::CONFUSED) == 0);
}

// PaelsLegion doubles every block gain of the first card play that gains block; the cooldown
// starts at that play's AfterCardPlayed. Pre-v31 the second gain of the same play was not doubled.
void paels_legion_doubles_the_whole_play() {
    auto r = fight({RelicId::PAELS_LEGION});
    BattleContext &b = r->battle;
    b.activePlay.active = true;
    b.activePlay.card = make_card(CardId::DEFEND_IRONCLAD, false, b.require_card_uid());
    check("first gain doubled", relics_modify_block_gain(b, 5, true, true) == 10);
    check("second gain of the same play doubled", relics_modify_block_gain(b, 5, true, true) == 10);
    relics_card_played(b, b.activePlay.card);
    b.activePlay.active = false;
    check("cooldown after the play", relic_aux(b, RelicId::PAELS_LEGION) == 2);
    check("next play not doubled", relics_modify_block_gain(b, 5, true, true) == 5);
}

// ArchaicTooth.AfterObtained: CardCmd.Transform(Bash -> Break). The Break is a new card at the
// end of the deck that went through the deck-add hooks (Molten Egg upgrades it, Lucky Fysh pays).
void archaic_tooth_is_a_transform() {
    auto r = std::make_unique<RunContext>();
    r->init_seed("V31TOOTH", 10);
    r->screen = RunScreen::MAP;
    assert(r->add_relic(RelicId::MOLTEN_EGG));
    assert(r->add_relic(RelicId::LUCKY_FYSH));
    int bashAt = -1;
    for (int i = 0; i < r->deckCount; ++i) if (r->deck[i].id == CardId::BASH) bashAt = i;
    check("starting deck has Bash", bashAt >= 0);
    const std::uint16_t bashUid = r->deck[bashAt].uid;
    const int gold = r->gold, count = r->deckCount;
    check("obtain Archaic Tooth", r->add_relic(RelicId::ARCHAIC_TOOTH));
    int bashes = 0;
    for (int i = 0; i < r->deckCount; ++i) bashes += r->deck[i].id == CardId::BASH;
    const Card &last = r->deck[r->deckCount - 1];
    check("Bash removed, deck size kept", bashes == 0 && r->deckCount == count);
    check("Break appended as a new card", last.id == CardId::BREAK && last.uid != bashUid);
    check("Molten Egg upgraded the Break", last.upgraded);
    check("Lucky Fysh paid for the added card", r->gold == gold + 15);
}

// A 0-hit AttackCommand still runs BeforeAttack/AfterAttack and spends Vigor (Whirlwind at X = 0).
void zero_hit_attack_spends_vigor() {
    auto r = fight({});
    BattleContext &b = r->battle;
    b.hand[0] = make_card(CardId::WHIRLWIND, false, b.hand[0].uid);
    b.player.energy = 0;
    b.add_player_power(PowerId::VIGOR, 8);
    check("play Whirlwind at X = 0", b.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("Vigor spent by the 0-hit attack", b.player_power(PowerId::VIGOR) == 0);
}

// Shiv.TargetType is AllEnemies with Fan of Knives: no target choice (one play action, not one per
// enemy), and the card view says so.
void fan_of_knives_shiv_has_no_target_choice() {
    auto r = std::make_unique<RunContext>();
    r->init_seed("V31SHIV", 10);
    r->screen = RunScreen::MAP;
    r->begin_combat(Encounter::SETUP_TOADPOLES_WEAK);
    BattleContext &b = r->battle;
    int alive = 0;
    for (int m = 0; m < b.monsterCount; ++m) alive += b.monsters[m].alive && !b.monsters[m].reviving;
    b.hand[0] = make_card(CardId::SHIV, false, b.hand[0].uid);
    auto shiv_plays = [&] {
        int n = 0;
        for (const Action &a : b.legal_actions()) n += a.type == ActionType::PLAY_CARD && a.hand == 0;
        return n;
    };
    check("Toadpoles has two enemies", alive >= 2);
    check("plain Shiv: one play per enemy", shiv_plays() == alive);
    b.add_player_power(PowerId::FAN_OF_KNIVES, 1);
    check("Fan of Knives Shiv: a single untargeted play", shiv_plays() == 1 &&
                                                          b.card_target_now(b.hand[0]) == TargetType::ALL_ENEMIES);
}

void snapshot_roundtrip() {
    auto roundtrip = [](RunContext &r) {
        auto saved = std::make_unique<RunContext>();
        return RunContext::restore(r.serialize(), *saved) && saved->serialize() == r.serialize();
    };
    auto a = fight({RelicId::SNECKO_EYE, RelicId::RINGING_TRIANGLE});
    check("snapshot with Confused restores", roundtrip(*a));
    auto c = fight({RelicId::PAELS_LEGION});
    relics_card_played(c->battle, c->battle.hand[0]);  // no-op outside an affected play
    c->battle.relicAux[0] = 2;                          // cooldown state between turns
    check("snapshot with Legion cooldown restores", roundtrip(*c));
    // A decision inside the affected play (True Grit+ gains block, then asks which card to
    // exhaust): the -1 / UID state must survive save and load.
    auto d = fight({RelicId::PAELS_LEGION});
    BattleContext &b = d->battle;
    b.hand[0] = make_card(CardId::TRUE_GRIT, true, b.hand[0].uid);
    b.player.energy = 3;
    const int block0 = b.player.block;
    check("play True Grit+", b.step(Action{ActionType::PLAY_CARD, 0, 0, 0}));
    check("True Grit+ waits for the exhaust choice", b.pending.op != ChoiceOp::NONE);
    check("its block was doubled", b.player.block - block0 == 2 * card_var(b.activePlay.card, VarId::BLOCK));
    check("snapshot inside the affected play restores", roundtrip(*d));
    check("finish the choice", b.step(Action{ActionType::CHOOSE, 0, 0, b.pending.cards[0].uid}));
    if (b.pending.op != ChoiceOp::NONE) b.step(Action{ActionType::CONFIRM, 0, 0, 0});
    check("cooldown after True Grit+", relic_aux(b, RelicId::PAELS_LEGION) == 2);
}
}  // namespace

int main() {
    rod_and_remnant_follow_bar_order();
    eggs_upgrade_shop_cards();
    ringing_triangle_is_not_a_power();
    snecko_eye_applies_confused();
    paels_legion_doubles_the_whole_play();
    archaic_tooth_is_a_transform();
    zero_hit_attack_spends_vigor();
    fan_of_knives_shiv_has_no_target_choice();
    snapshot_roundtrip();
    std::cout << "native relic audit v31: " << failures << " failures\n";
    return failures ? 1 : 0;
}
