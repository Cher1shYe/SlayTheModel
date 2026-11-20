// Source-port regressions for the v16 event/ancient audit (docs/content-audit.md):
// Tezcatara/Pael/Orobas option pools; Nutritious Soup (TezcatarasEmber), Pael's
// Claw (Goopy), Tri-Boomerang (Instinct), War Hammer and Meat Cleaver (Cook).
// Expectations come from the v0.111.0 decompilation, not from a DLL trace.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <memory>
#include <set>
#include <string>

using namespace sts2;

namespace {
std::unique_ptr<RunContext> base(const std::string &seed) {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->screen = RunScreen::MAP;
    return r;
}
void roundtrip(RunContext &r) {
    auto saved = std::make_unique<RunContext>();
    assert(RunContext::restore(r.serialize(), *saved));
    assert(saved->serialize() == r.serialize());
}
int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) if (std::strcmp(event_info(i)->name, name) == 0) return i;
    assert(false); return -1;
}
bool has(const RunContext &r, RunActionType type) {
    for (auto a : r.legal_actions()) if (a.type == type) return true;
    return false;
}
int count_relic_offers(const std::string &prefix, const char *ancient, int slot, RelicId relic,
                       void (*prepare)(RunContext &), int seeds = 300) {
    int hits = 0;
    for (int s = 0; s < seeds; ++s) {
        auto r = base(prefix + std::to_string(s));
        r->act = 1;
        if (prepare) prepare(*r);
        event_begin(*r, event_id(ancient), true);
        hits += r->eventRelics[slot] == static_cast<int>(relic);
    }
    return hits;
}

void option_pools() {
    // Tezcatara: Seal of Gold only in pool 3 (1/4), never pool 2 (1/3 each).
    assert(count_relic_offers("TEZ", "TEZCATARA", 1, RelicId::SEAL_OF_GOLD, nullptr) == 0);
    const int seal = count_relic_offers("TEZ", "TEZCATARA", 2, RelicId::SEAL_OF_GOLD, nullptr);
    assert(seal > 40 && seal < 110);
    assert(count_relic_offers("TEZ", "TEZCATARA", 0, RelicId::NUTRITIOUS_SOUP, nullptr) > 50);
    // Without a Basic Strike, Nutritious Soup is never offered.
    auto noStrikes = [](RunContext &r) {
        int dst = 0;
        for (int i = 0; i < r.deckCount; ++i) if (!card_is_strike(r.deck[i])) r.deck[dst++] = r.deck[i];
        r.deckCount = dst;
    };
    assert(count_relic_offers("TEZ", "TEZCATARA", 0, RelicId::NUTRITIOUS_SOUP, noStrikes) == 0);
    // Pael's Legion only without an event pet (Byrdonis Egg in the deck counts).
    assert(count_relic_offers("PAEL", "PAEL", 2, RelicId::PAELS_LEGION, nullptr) > 50);
    auto withEgg = [](RunContext &r) { assert(r.add_card_to_deck(r.make_run_card(CardId::BYRDONIS_EGG, false))); };
    assert(count_relic_offers("PAEL", "PAEL", 2, RelicId::PAELS_LEGION, withEgg) == 0);
    // Pael's Claw needs three Goopy-enchantable Defends: already enchanted ones do not count.
    auto enchantedDefends = [](RunContext &r) {
        for (int i = 0; i < r.deckCount; ++i)
            if (card_is_defend(r.deck[i])) card_apply_enchantment(r.deck[i], EnchantmentId::SOWN, 1);
    };
    assert(count_relic_offers("PAEL", "PAEL", 1, RelicId::PAELS_CLAW, nullptr) > 0);
    assert(count_relic_offers("PAEL", "PAEL", 1, RelicId::PAELS_CLAW, enchantedDefends) == 0);
    // Orobas: Archaic Tooth keys on Bash; Break alone does not qualify.
    auto breakOnly = [](RunContext &r) {
        for (int i = 0; i < r.deckCount; ++i) if (r.deck[i].id == CardId::BASH) r.deck[i].id = CardId::BREAK;
    };
    assert(count_relic_offers("OROBAS", "OROBAS", 2, RelicId::ARCHAIC_TOOTH, nullptr) > 0);
    assert(count_relic_offers("OROBAS", "OROBAS", 2, RelicId::ARCHAIC_TOOTH, breakOnly) == 0);
}

void nutritious_soup() {
    auto r = base("SOUP");
    assert(r->add_relic(RelicId::NUTRITIOUS_SOUP));
    int ember = 0;
    for (int i = 0; i < r->deckCount; ++i) {
        const Card &c = r->deck[i];
        const bool basicStrike = card_is_strike(c) && card_def(c.id).rarity == Rarity::BASIC;
        assert((c.enchantment == EnchantmentId::TEZCATARAS_EMBER) == basicStrike);
        if (!basicStrike) continue;
        ++ember;
        assert(card_cost(c) == 0 && card_has(c, CF_ETERNAL) && !card_can_transform_from_deck(c));
        Card up = c;
        card_apply_upgrade(up);
        assert(card_cost(up) == 0);  // EnergyCost.UpgradeBy: the base stays 0
        assert(r->battle.enchant_card_damage(c, 6) == 9);
    }
    assert(ember == 5);
    roundtrip(*r);
}

void paels_claw_goopy() {
    auto r = base("CLAW");
    assert(r->add_relic(RelicId::PAELS_CLAW));
    for (int i = 0; i < r->deckCount; ++i) {
        const Card &c = r->deck[i];
        assert((c.enchantment == EnchantmentId::GOOPY) == card_is_defend(c));
        if (card_is_defend(c)) assert(c.enchantmentAmount == 1 && card_has(c, CF_EXHAUST));
    }
    // Play a Goopy Defend: block 5 + (Amount - 1) = 5, Amount 1 -> 2 on the deck card.
    int played = 0;
    for (int s = 0; s < 20 && !played; ++s) {
        auto t = base("CLAW");
        assert(t->add_relic(RelicId::PAELS_CLAW));
        t->begin_combat(Encounter::SETUP_SLIMES_WEAK);
        BattleContext &b = t->battle;
        for (int turn = 0; turn < 3 && !played; ++turn) {
            for (int i = 0; i < b.handCount; ++i) {
                if (b.hand[i].enchantment != EnchantmentId::GOOPY) continue;
                const std::uint16_t uid = b.hand[i].uid;
                const int before = b.player.block;
                assert(b.step(Action{ActionType::PLAY_CARD, static_cast<std::uint8_t>(i), 0, 0}));
                assert(b.player.block - before == 5);
                bool exhausted = false;
                for (int k = 0; k < b.exhaustCount; ++k) exhausted |= b.exhaust[k].uid == uid;
                assert(exhausted);
                b.outcome = Outcome::PLAYER_VICTORY;
                t->finish_combat();
                for (int k = 0; k < t->deckCount; ++k)
                    if (t->deck[k].uid == uid) assert(t->deck[k].enchantmentAmount == 2);
                played = 1;
                break;
            }
            if (!played) b.step(Action{ActionType::END_TURN, 0, 0, 0});
        }
    }
    assert(played);
}

void tri_boomerang_instinct() {
    auto r = base("BOOMERANG");
    r->screen = RunScreen::MAP;
    assert(r->add_relic(RelicId::TRI_BOOMERANG));
    assert(r->cardGrid.kind == 23 && r->cardGrid.minSelect == 3 && r->cardGrid.maxSelect == 3);
    roundtrip(*r);
    std::set<int> picked;
    for (int i = 0; i < r->deckCount && static_cast<int>(picked.size()) < 3; ++i)
        if (card_type(r->deck[i]) == CardType::ATTACK) { assert(select_card_grid(*r, i)); picked.insert(i); }
    assert(confirm_card_grid(*r) || r->cardGrid.preview);
    if (r->cardGrid.kind) assert(confirm_card_grid(*r));
    int instinct = 0;
    for (int i = 0; i < r->deckCount; ++i) {
        if (r->deck[i].enchantment != EnchantmentId::INSTINCT) continue;
        ++instinct;
        assert(picked.count(i) && r->battle.enchant_card_damage(r->deck[i], 6) == 12);
    }
    assert(instinct == 3);
    for (int i = 0; i < r->deckCount; ++i)
        if (card_type(r->deck[i]) != CardType::ATTACK) assert(!card_can_enchant(r->deck[i], EnchantmentId::INSTINCT));
}

void war_hammer() {
    auto r = base("WARHAMMER");
    assert(r->add_relic(RelicId::WAR_HAMMER));
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    r->combatIsElite = true; r->combatIsBoss = false;
    r->battle.outcome = Outcome::PLAYER_VICTORY;
    r->finish_combat();
    int upgraded = 0;
    for (int i = 0; i < r->deckCount; ++i) upgraded += r->deck[i].upgraded;
    assert(upgraded == 4);
    auto n = base("WARHAMMER");
    assert(n->add_relic(RelicId::WAR_HAMMER));
    n->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    n->combatIsElite = n->combatIsBoss = false;
    n->battle.outcome = Outcome::PLAYER_VICTORY;
    n->finish_combat();
    for (int i = 0; i < n->deckCount; ++i) assert(!n->deck[i].upgraded);
}

void meat_cleaver_cook() {
    auto r = base("COOK");
    r->screen = RunScreen::REST;
    r->restUsedOptions = 0;
    assert(!has(*r, RunActionType::REST_COOK));
    assert(r->add_relic(RelicId::MEAT_CLEAVER));
    r->screen = RunScreen::REST;
    assert(has(*r, RunActionType::REST_COOK));
    const int deckBefore = r->deckCount, maxHpBefore = r->maxHp, hpBefore = r->hp;
    assert(r->step({RunActionType::REST_COOK, 0}));
    assert(r->cardGrid.kind == 6 && r->cardGrid.minSelect == 2 && r->cardGrid.service == 4);
    assert(r->step({RunActionType::CANCEL_GRID_SELECTION, 0}));
    assert(!r->cardGrid.kind && has(*r, RunActionType::REST_COOK) && r->deckCount == deckBefore);
    assert(r->step({RunActionType::REST_COOK, 0}));
    roundtrip(*r);
    assert(select_card_grid(*r, 0) && select_card_grid(*r, 1));
    while (r->cardGrid.kind) assert(confirm_card_grid(*r));
    assert(r->deckCount == deckBefore - 2 && r->maxHp == maxHpBefore + 5 && r->hp == hpBefore + 5);
    assert(r->restUsedOptions & 128);
    assert(!has(*r, RunActionType::REST_COOK) && !has(*r, RunActionType::REST_HEAL));
}
}  // namespace

int main() {
    option_pools();
    nutritious_soup();
    paels_claw_goopy();
    tri_boomerang_instinct();
    war_hammer();
    meat_cleaver_cook();
    std::cout << "native_ancient_relics_v16 ok\n";
    return 0;
}
