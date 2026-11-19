// Native v0.111.0 Neow declaration order and pickup continuations.
// Only the PARITY0001 initial offers below have an actual native-host capture;
// the other cases check source-ported behavior, not executed DLL equivalence.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/observe.h"
#include "sts2/macro_obs.h"
#include <algorithm>
#include <cassert>
#include <iostream>
#include <memory>
#include <set>

using namespace sts2;
namespace {
std::unique_ptr<RunContext> base() {
    auto r = std::make_unique<RunContext>();
    r->init_seed("NEOWGENERATION", 10);
    r->screen = RunScreen::MAP;
    return r;
}
bool legal(const RunContext &r, RunActionType type) {
    for (const auto &a : r.legal_actions()) if (a.type == type) return true;
    return false;
}
void roundtrip(RunContext &r) {
    const auto bytes = r.serialize();
    auto restored = std::make_unique<RunContext>();
    assert(RunContext::restore(bytes, *restored));
    assert(restored->serialize() == bytes);
    assert(public_observation(r) == public_observation(*restored));
    assert(macro_observation(r).num == macro_observation(*restored).num);
    // The new fields describe already shown choices; future randomness remains
    // hidden, including while an obtained relic opens its nested reward set.
    restored->runRng[RNG_NICHE].next_int_exclusive(100);
    restored->runRng[RNG_SHUFFLE].next_int_exclusive(100);
    restored->playerRng[PRNG_REWARDS].next_int_exclusive(100);
    assert(public_observation(r) == public_observation(*restored));
    assert(macro_observation(r).num == macro_observation(*restored).num);
}
int curses(const RunContext &r) {
    int n = 0;
    for (int i = 0; i < r.deckCount; ++i) n += card_type(r.deck[i]) == CardType::CURSE;
    return n;
}
void captured_initial_options() {
    NativeProgressContext progress;
    progress.numberOfRuns = 0;
    progress.applyDiscoveryOrder = true;
    progress.underdocksUnlocked = true;
    progress.underdocksDiscovered = false;
    progress.aeonglassSeen = false;
    for (auto &word : progress.seenEncounters) word = 0;
    auto r = base();
    r->init_seed_with_context("PARITY0001", 10, -1, progress);
    assert(r->actTypes[0] == ActType::UNDERDOCKS);
    assert(r->eventRelics[0] == static_cast<int>(RelicId::NEW_LEAF));
    assert(r->eventRelics[1] == static_cast<int>(RelicId::GOLDEN_PEARL));
    assert(r->eventRelics[2] == static_cast<int>(RelicId::SILKEN_TRESS));
    assert(r->eventRng.counter == 19);
    roundtrip(*r);
    // Discovery controls the first act/room bags, not this event's RNG.
    r->init_seed("PARITY0001", 10);
    assert(r->eventRelics[0] == static_cast<int>(RelicId::NEW_LEAF));
    assert(r->eventRelics[1] == static_cast<int>(RelicId::GOLDEN_PEARL));
    assert(r->eventRelics[2] == static_cast<int>(RelicId::SILKEN_TRESS));
    RelicId pool[30];
    assert(native_neow_relic_pool(*r, pool, 30) == 29); // MassiveScroll is multiplayer only.
    std::set<RelicId> ids(pool, pool + 29);
    assert(ids.size() == 29 && !ids.count(RelicId::MASSIVE_SCROLL));
    for (RelicId id : ids) assert(relic_implemented(id));
    r->nativeProgress.unlockedCharacterMask = 1;
    const int n = native_neow_relic_pool(*r, pool, 30);
    assert(std::find(pool, pool + n, RelicId::KALEIDOSCOPE) == pool + n);
}
void set_bones_rewards(RunContext &r, RelicId first, RelicId second) {
    assert(r.add_relic(RelicId::NEOWS_BONES));
    assert(r.neowsBonesStage == 1 && r.screen == RunScreen::REWARDS);
    // Force two declared reward identities to exercise continuations separately
    // from the RNG contract checked below; never alter the captured fixture.
    r.pendingRelics[0] = r.neowsBonesRelics[0] = static_cast<int>(first);
    r.pendingRelics[1] = r.neowsBonesRelics[1] = static_cast<int>(second);
}
void bones_rewards() {
    auto r = base();
    RelicId pool[30], eligible[30];
    const int count = native_neow_relic_pool(*r, pool, 30);
    int n = 0;
    for (int i = 0; i < count; ++i) if (pool[i] != RelicId::NEOWS_BONES) eligible[n++] = pool[i];
    Rng expected = r->playerRng[PRNG_REWARDS];
    expected.shuffle(eligible, n);
    assert(r->add_relic(RelicId::NEOWS_BONES));
    assert(r->pendingRelics[0] == static_cast<int>(eligible[0]));
    assert(r->pendingRelics[1] == static_cast<int>(eligible[1]));
    assert(r->playerRng[PRNG_REWARDS].counter == expected.counter);
    roundtrip(*r);

    r = base();
    set_bones_rewards(*r, RelicId::FISHING_ROD, RelicId::WINGED_BOOTS);
    const int before = curses(*r), nicheBefore = r->runRng[RNG_NICHE].counter;
    assert(!legal(*r, RunActionType::LEAVE_REWARDS));
    assert(!r->step({RunActionType::LEAVE_REWARDS, 0}));
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 1}));
    assert(curses(*r) == before && r->neowsBonesStage == 1);
    roundtrip(*r);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(curses(*r) == before + 1 && r->neowsBonesStage == 0);
    assert(r->screen == RunScreen::MAP && r->runRng[RNG_NICHE].counter == nicheBefore + 1);
    roundtrip(*r);

    // An obtained relic may open its own skippable reward set. Leaving that set
    // returns to Bones' remaining mandatory relic without prematurely cursing.
    r = base();
    set_bones_rewards(*r, RelicId::KALEIDOSCOPE, RelicId::WINGED_BOOTS);
    const int beforeNested = curses(*r);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(r->neowsBonesStage == 2 && r->pendingRelicCount == 0 && r->pendingCardReward);
    roundtrip(*r);
    assert(r->step({RunActionType::LEAVE_REWARDS, 0}));
    assert(r->neowsBonesStage == 1 && !r->pendingCardReward && r->pendingRelicCount == 2);
    assert(r->pendingRelicClaimed[0] && !r->pendingRelicClaimed[1]);
    assert(curses(*r) == beforeNested && !legal(*r, RunActionType::LEAVE_REWARDS));
    roundtrip(*r);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 1}));
    assert(curses(*r) == beforeNested + 1 && r->neowsBonesStage == 0);
    roundtrip(*r);

    r = base();
    set_bones_rewards(*r, RelicId::HEFTY_TABLET, RelicId::FISHING_ROD);
    const int beforeGrid = curses(*r);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 1}));
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(r->cardGrid.kind == 16 && curses(*r) == beforeGrid);
    roundtrip(*r);
    assert(r->step({RunActionType::CONFIRM_GRID_CARDS, 0}));
    assert(curses(*r) == beforeGrid + 2 && r->neowsBonesStage == 0);
    roundtrip(*r);
}
void neow_proceed() {
    auto obtain = [](RelicId id) {
        auto r = base();
        r->screen = RunScreen::EVENT;
        r->eventRelics[0] = static_cast<int>(id);
        assert(r->step({RunActionType::EVENT_CHOICE, 0}));
        return r;
    };
    auto proceed = [](RunContext &r) {
        assert(r.screen == RunScreen::EVENT && r.eventPage == 127);
        assert(event_option_count(r) == 1 && r.eventChoiceCount == 1);
        assert(event_option_available(r, 0) && !event_option_available(r, 1));
        assert(r.eventRelics[0] == 0);
        roundtrip(r);
        const int gold = r.gold, relics = r.relicCount, floor = r.floor;
        assert(r.step({RunActionType::EVENT_CHOICE, 0}));
        assert(r.screen == RunScreen::MAP && r.eventId == -1);
        assert(r.gold == gold && r.relicCount == relics && r.floor == floor);
    };
    auto r = obtain(RelicId::GOLDEN_PEARL);
    proceed(*r);

    r = obtain(RelicId::HEFTY_TABLET);
    assert(r->eventPage == 126 && r->cardGrid.kind == 16);
    assert(event_option_count(*r) == 0 && !legal(*r, RunActionType::EVENT_CHOICE));
    assert(!r->step({RunActionType::EVENT_CHOICE, 0}));
    roundtrip(*r);
    assert(r->step({RunActionType::CONFIRM_GRID_CARDS, 0}));
    proceed(*r);

    r = obtain(RelicId::KALEIDOSCOPE);
    assert(r->eventPage == 126 && r->screen == RunScreen::REWARDS);
    assert(event_option_count(*r) == 0);
    roundtrip(*r);
    assert(r->step({RunActionType::LEAVE_REWARDS, 0}));
    proceed(*r);

    r = obtain(RelicId::NEOWS_BONES);
    assert(r->eventPage == 126 && r->neowsBonesStage == 1);
    r->pendingRelics[0] = r->neowsBonesRelics[0] = static_cast<int>(RelicId::FISHING_ROD);
    r->pendingRelics[1] = r->neowsBonesRelics[1] = static_cast<int>(RelicId::WINGED_BOOTS);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(r->eventPage == 126 && event_option_count(*r) == 0);
    assert(r->step({RunActionType::TAKE_RELIC_REWARD, 1}));
    proceed(*r);
}
void progress_preserves_card_offsets() {
    auto r = base();
    r->screen = RunScreen::SHOP;
    r->deck[0] = r->make_run_card(CardId::DOWSING, false);
    r->shopCount = 1;
    r->shopCards[0] = r->make_run_card(CardId::DOWSING, false);
    r->shopPrices[0] = 77;
    const auto before = macro_observation(*r);
    r->deck[0].guiltyCombatsSeen = 2;
    r->shopCards[0].guiltyCombatsSeen = 3;
    const auto after = macro_observation(*r);
    assert(before.kind == after.kind && before.id == after.id);
    int changed = 0;
    for (std::size_t i = 0; i < after.num.size(); ++i) {
        if (before.num[i] == after.num[i]) continue;
        assert(i % MACRO_ENTITY_NUM == 78);
        ++changed;
    }
    assert(changed == 2); // deck selection/offer source/price/selection keep their offsets.
}
void simple_map(RunContext &r, MapPointType type) {
    r.map = ActMap{};
    std::fill(&r.map.index[0][0], &r.map.index[0][0] + MAP_MAX_ROWS * MAP_WIDTH, -1);
    r.map.rooms = 5; r.map.mapLength = 6; r.map.startIdx = 0; r.map.bossIdx = 12;
    r.map.pointCount = 13;
    for (int row = 0; row <= 6; ++row) {
        const int a = row * 2;
        r.map.index[row][0] = a;
        r.map.nodes[a].type = static_cast<int>(type);
        if (row < 6) {
            r.map.index[row][1] = a + 1;
            r.map.nodes[a + 1].type = static_cast<int>(type);
            r.map.nodes[a].childCount = r.map.nodes[a + 1].childCount = 1;
            r.map.nodes[a].children[0] = r.map.nodes[a + 1].children[0] = a + 2;
        }
    }
    r.curRow = r.curCol = 0; r.screen = RunScreen::MAP;
}
void winged_boots_and_dowsing() {
    auto r = base();
    assert(r->add_relic(RelicId::WINGED_BOOTS));
    const int boots = r->relicCount - 1;
    simple_map(*r, MapPointType::REST);
    assert(r->available_map_nodes() == std::vector<int>({2, 3}));
    r->enter_map_point(2); // existing edge is free
    assert(r->relicAux[boots] == 0);
    for (int i : {5, 7, 9}) r->enter_map_point(i);
    assert(r->relicAux[boots] == 3);
    assert(r->available_map_nodes() == std::vector<int>({10}));

    r = base();
    assert(r->add_relic(RelicId::DOWSING_ROD));
    roundtrip(*r);
    const auto questUid = r->deck[r->deckCount - 1].uid;
    simple_map(*r, MapPointType::UNKNOWN);
    r->unknownMonsterOdds = r->unknownTreasureOdds = r->unknownShopOdds = -1;
    r->eventBagN = 0;
    for (int i : {2, 4, 6, 8}) r->enter_map_point(i);
    assert(r->deck[r->deckCount - 1].id == CardId::DOWSING);
    assert(r->deck[r->deckCount - 1].guiltyCombatsSeen == 4);
    assert(r->add_relic(RelicId::TOXIC_EGG));
    r->enter_map_point(10);
    const Card &abundance = r->deck[r->deckCount - 1];
    assert(abundance.id == CardId::ABUNDANCE && abundance.uid != questUid);
    assert(abundance.upgraded && abundance.guiltyCombatsSeen == 0);
    assert(sizeof(Card) == 304);
}
}
int main() {
    captured_initial_options();
    bones_rewards();
    neow_proceed();
    progress_preserves_card_offsets();
    winged_boots_and_dowsing();
    std::cout << "native Neow generation and continuations ok\n";
}
