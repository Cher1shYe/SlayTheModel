// Source-port regressions for the v18 event option-effect audit (docs/content-audit.md §8):
// Maw Bank is used up only by MerchantEntry purchases (Hook.AfterItemPurchased with
// goldSpent > 0). Waterlogged Scriptorium pays with PlayerCmd.LoseGold, so Maw Bank
// stays active; the Fake Merchant sells through NMerchantRelic slots, so a purchase
// there uses it up. Expectations come from the v0.111.0 decompilation, not a DLL trace.
#include "sts2/run.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <memory>

using namespace sts2;

namespace {
int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) if (std::strcmp(event_info(i)->name, name) == 0) return i;
    assert(false); return -1;
}
std::unique_ptr<RunContext> with_maw_bank(const char *seed) {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, 10);
    r->screen = RunScreen::MAP;
    r->act = 1;
    r->gold = 300;
    assert(r->add_relic(RelicId::MAW_BANK));
    assert(!r->mawBankPurchased);
    return r;
}

void waterlogged_keeps_maw_bank() {
    for (int option : {1, 2}) {
        auto r = with_maw_bank("V18WATERLOGGED");
        event_begin(*r, event_id("WATERLOGGED_SCRIPTORIUM"), false);
        assert(event_choose(*r, option));
        assert(r->gold == 300 - (option == 1 ? 55 : 99));
        assert(r->cardGrid.kind == 12);
        int picked = 0;
        for (int i = 0; i < r->deckCount && picked < option; ++i)
            if (card_can_enchant(r->deck[i], EnchantmentId::STEADY) && select_card_grid(*r, i)) ++picked;
        assert(picked == option);
        while (r->cardGrid.kind) assert(confirm_card_grid(*r));
        assert(!r->mawBankPurchased);  // LoseGold(Spent) is not an item purchase
    }
}

void fake_merchant_uses_maw_bank() {
    auto r = with_maw_bank("V18FAKEMERCHANT");
    event_begin(*r, event_id("FAKE_MERCHANT"), false);
    const int price = r->eventData[0];
    assert(price >= 43 && price <= 58);  // round(50 * [0.85, 1.15))
    assert(event_choose(*r, 0));
    assert(r->gold == 300 - price);
    assert(r->mawBankPurchased);
    // Leaving without buying keeps it.
    auto l = with_maw_bank("V18FAKEMERCHANT");
    event_begin(*l, event_id("FAKE_MERCHANT"), false);
    assert(event_choose(*l, 6));
    assert(!l->mawBankPurchased);
}
}  // namespace

int main() {
    waterlogged_keeps_maw_bank();
    fake_merchant_uses_maw_bank();
    std::cout << "native_event_options_v18 ok\n";
    return 0;
}
