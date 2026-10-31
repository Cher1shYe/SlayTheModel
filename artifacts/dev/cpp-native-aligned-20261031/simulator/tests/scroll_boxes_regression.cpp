#include "sts2/run.h"
#include "sts2/relics.h"

#include <cassert>
#include <set>

using namespace sts2;

int main() {
    RunContext run;
    run.init(147, 0);
    run.screen = RunScreen::SHOP;
    run.gold = 500;
    assert(run.add_relic(RelicId::BING_BONG));
    assert(run.add_relic(RelicId::LUCKY_FYSH));
    const int before = run.deckCount;
    assert(run.add_relic(RelicId::SCROLL_BOXES));
    assert(run.gold == 0 && run.cardGrid.kind == 5 && run.cardGrid.count == 6);
    std::set<int> ids;
    for (int i = 0; i < 6; ++i) {
        const Card &card = run.cardGrid.cards[i];
        assert(card_def(card.id).rarity == (i % 3 == 2 ? Rarity::UNCOMMON : Rarity::COMMON));
        assert(ids.insert(static_cast<int>(card.id)).second);
    }
    RunContext restored;
    assert(RunContext::restore(run.serialize(), restored));
    assert(run.step({RunActionType::SELECT_GRID_CARD, 1}));
    assert(run.cardGrid.preview && run.deckCount == before);
    assert(RunContext::restore(run.serialize(), restored));
    assert(run.step({RunActionType::CANCEL_GRID_PREVIEW, 0}));
    assert(run.cardGrid.kind == 5 && !run.cardGrid.preview);
    assert(run.step({RunActionType::SELECT_GRID_CARD, 1}));
    assert(run.step({RunActionType::CONFIRM_GRID_CARDS, 0}));
    assert(run.cardGrid.kind == 0 && run.screen == RunScreen::SHOP);
    assert(run.deckCount == before + 6 && run.gold == 90);

    RunContext full;
    full.init(148, 0);
    full.gold = 500;
    full.deckCount = MAX_DECK - 2;
    assert(!full.add_relic(RelicId::SCROLL_BOXES));
    assert(full.gold == 500 && !run_has_relic(full, RelicId::SCROLL_BOXES));

    RunContext nested;
    nested.init(149, 0);
    nested.screen = RunScreen::REWARDS;
    nested.pendingGoldReward = 42;
    nested.pendingRelicCount = 1;
    nested.pendingRelics[0] = static_cast<int>(RelicId::SCROLL_BOXES);
    assert(nested.step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(nested.cardGrid.kind == 5 && nested.pendingGoldReward == 42);
    assert(nested.step({RunActionType::SELECT_GRID_CARD, 0}));
    assert(nested.step({RunActionType::CONFIRM_GRID_CARDS, 0}));
    assert(nested.screen == RunScreen::REWARDS && nested.pendingGoldReward == 42);
    assert(nested.step({RunActionType::TAKE_GOLD_REWARD, 0}));

    RunContext event;
    event.init(150, 0);
    assert(event.screen == RunScreen::EVENT);
    assert(event.add_relic(RelicId::SCROLL_BOXES));
    assert(event.step({RunActionType::SELECT_GRID_CARD, 0}));
    assert(event.step({RunActionType::CONFIRM_GRID_CARDS, 0}));
    assert(event.screen == RunScreen::EVENT);

    RunContext blocked;
    blocked.init(151, 0);
    blocked.eventRelics[0] = static_cast<int>(RelicId::SCROLL_BOXES);
    blocked.deckCount = MAX_DECK - 2;
    const int oldGold = blocked.gold;
    assert(!event_option_available(blocked, 0));
    assert(!blocked.step({RunActionType::EVENT_CHOICE, 0}));
    assert(blocked.gold == oldGold && blocked.screen == RunScreen::EVENT);
}
