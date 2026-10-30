#include <cstring>
#include <iostream>
#include "sts2/map.h"
#include "sts2/run.h"

using namespace sts2;

static int failures = 0;
static void check(const char *name, bool condition) {
    if (!condition) { std::cerr << name << " failed\n"; ++failures; }
}

static int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) {
        const EventInfo *info = event_info(i);
        if (info && std::strcmp(info->name, name) == 0) return i;
    }
    return -1;
}

static int count_points(const ActMap &map, MapPointType type) {
    int n = 0;
    for (int i = 0; i < map.pointCount; ++i)
        n += map.nodes[i].type == static_cast<int>(type);
    return n;
}

int main() {
    {
        RunContext rc;
        rc.init(12, 0);
        check("Pael's Growth can be obtained", rc.add_relic(RelicId::PAELS_GROWTH));
        check("Pael's Growth offers deck selection", rc.cardGrid.kind == 4);
        RunContext restored;
        check("Clone selection snapshot restores", RunContext::restore(rc.serialize(), restored));
        check("Clone selection can choose first card", rc.step({RunActionType::SELECT_GRID_CARD, 0}));
        check("Clone enchant amount is four", rc.deck[0].enchantment == EnchantmentId::CLONE && rc.deck[0].enchantmentAmount == 4);
        check("Clone selection closes", rc.cardGrid.kind == 0);
        const int originalCount = rc.deckCount;
        const std::uint16_t originalUid = rc.deck[0].uid;
        rc.screen = RunScreen::REST;
        check("Clone rest succeeds", rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone rest copies one card", rc.deckCount == originalCount + 1);
        check("Clone copy retains enchantment and distinct UID", rc.deck[originalCount].enchantment == EnchantmentId::CLONE && rc.deck[originalCount].uid != originalUid);
        rc.screen = RunScreen::REST;
        check("Clone rest repeats with original and clone", rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone copies grow from a fixed original snapshot", rc.deckCount == originalCount + 3);
    }
    {
        RunContext rc;
        rc.init(13, 0);
        rc.add_relic(RelicId::PAELS_GROWTH);
        rc.step({RunActionType::SELECT_GRID_CARD, 0});
        rc.add_relic(RelicId::BING_BONG);
        rc.add_relic(RelicId::LUCKY_FYSH);
        rc.screen = RunScreen::REST;
        const int count = rc.deckCount, gold = rc.gold;
        check("Clone rest with Bing Bong succeeds", rc.step({RunActionType::REST_CLONE, 0}));
        check("Bing Bong duplicates Clone addition", rc.deckCount == count + 2);
        check("Clone additions have unique UIDs", rc.deck[count].uid != rc.deck[count + 1].uid && rc.deck[count].uid != rc.deck[0].uid);
        check("Lucky Fysh triggers for both copies", rc.gold == gold + 30);
        while (rc.deckCount < MAX_DECK - 1)
            rc.deck[rc.deckCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 500 + rc.deckCount);
        rc.screen = RunScreen::REST;
        const int before = rc.deckCount, beforeGold = rc.gold;
        check("Clone capacity rejects entire action", !rc.step({RunActionType::REST_CLONE, 0}));
        check("Clone capacity failure is atomic", rc.deckCount == before && rc.gold == beforeGold && rc.screen == RunScreen::REST);
    }
    for (unsigned seed = 0; seed < 20; ++seed) {
        ActMap a9, a10;
        Rng rng9(seed), rng10(seed);
        generate_act_map(a9, rng9, 2, 9);
        generate_act_map(a10, rng10, 2, 10);
        check("A9 final act has no second boss", a9.secondBossIdx == -1);
        check("A10 final act adds one boss node", a10.secondBossIdx >= 0 &&
              a10.pointCount == a9.pointCount + 1);
        check("A10 boss node consumes no map RNG", rng9.counter == rng10.counter);
        if (a10.secondBossIdx >= 0 && a10.bossIdx >= 0) {
            const MapNode &first = a10.nodes[a10.bossIdx];
            const MapNode &second = a10.nodes[a10.secondBossIdx];
            check("A10 second boss coordinate", a10.at(a10.mapLength + 1, MAP_WIDTH / 2) == a10.secondBossIdx);
            check("A10 first boss has one second boss child", first.childCount == 1 &&
                  first.children[0] == a10.secondBossIdx);
            check("A10 second boss has first boss parent", second.parentCount == 1 &&
                  second.parents[0] == a10.bossIdx && second.childCount == 0);
            check("A10 both nodes are bosses", first.type == static_cast<int>(MapPointType::BOSS) &&
                  second.type == static_cast<int>(MapPointType::BOSS));
        }
        for (int act : {0, 1}) {
            ActMap earlier;
            Rng rng(seed);
            generate_act_map(earlier, rng, act, 10);
            check("A10 earlier acts have one boss", earlier.secondBossIdx == -1);
        }
    }
    for (int act = 0; act < 3; ++act) {
        int elite0 = 0, elite1 = 0, rest5 = 0, rest6 = 0;
        for (unsigned seed = 0; seed < 100; ++seed) {
            ActMap maps[4];
            Rng rngs[] = {Rng(seed), Rng(seed), Rng(seed), Rng(seed)};
            const int asc[] = {0, 1, 5, 6};
            for (int i = 0; i < 4; ++i) generate_act_map(maps[i], rngs[i], act, asc[i]);
            elite0 += count_points(maps[0], MapPointType::ELITE);
            elite1 += count_points(maps[1], MapPointType::ELITE);
            rest5 += count_points(maps[2], MapPointType::REST);
            rest6 += count_points(maps[3], MapPointType::REST);
        }
        check("A1 increases elite count", elite1 > elite0);
        check("A6 decreases rest count", rest6 < rest5);
    }
    {
        RunContext rc;
        rc.init(2020, 0);
        event_begin(rc, event_id("DENSE_VEGETATION"), false);
        Rng shared(rc.seed, "DENSE_VEGETATION");
        check("shared event RNG excludes player id", rc.eventRng.next_int(0, 100000) == shared.next_int(0, 100000));
        event_begin(rc, event_id("TABLET_OF_TRUTH"), false);
        Rng persistent(rc.seed + 1u, "TABLET_OF_TRUTH");
        for (int i = 0; i < 3; ++i) {
            int candidates[MAX_DECK];
            int n = 0;
            for (int j = 0; j < rc.deckCount; ++j)
                if (card_upgradable(rc.deck[j])) candidates[n++] = j;
            const int selected = candidates[persistent.next_int(0, n - 1)];
            event_choose(rc, 0);
            check("multi-page event advances persistent RNG", rc.eventRng.counter == persistent.counter);
            check("multi-page event uses next RNG draw", rc.deck[selected].upgraded);
        }
    }
    {
        RunContext rc;
        rc.init(3, 2);
        rc.hp = 19; rc.maxHp = 100;
        event_begin(rc, event_id("OROBAS"), true);
        check("A2 Ancient heals 80 percent of missing HP", rc.hp == 83);
        event_begin(rc, event_id("NEOW"), true);
        check("A2 Neow heals 80 percent from zero", rc.hp == 80);
    }
    {
        RunContext rc;
        rc.init(4, 0);
        rc.deckCount = MAX_DECK;
        event_begin(rc, event_id("BRAIN_LEECH"), false);
        const int hp = rc.hp;
        check("full deck rejects event choice", !event_choose(rc, 1));
        check("rejected event choice keeps HP and deck", rc.hp == hp && rc.deckCount == MAX_DECK);
    }
    {
        RunContext rc;
        rc.init(5, 0);
        rc.add_relic(RelicId::BING_BONG);
        rc.deckCount = MAX_DECK;
        event_begin(rc, event_id("WELLSPRING"), false);
        check("Bing Bong accounts for both new cards", !event_choose(rc, 1));
        check("rejected replacement does not remove a card", rc.deckCount == MAX_DECK);
    }
    {
        RunContext rc;
        rc.init(6, 0);
        rc.gold = 500;
        rc.relicCount = MAX_RELICS;
        event_begin(rc, event_id("WELCOME_TO_WONGOS"), false);
        check("full relic inventory rejects purchase", !event_choose(rc, 0));
        check("rejected relic purchase keeps gold", rc.gold == 500);
    }
    for (unsigned seed = 0; seed < 500; ++seed) {
        RunContext rc;
        rc.seed = seed;
        rc.deckCount = 1;
        rc.deck[0] = rc.make_run_card(CardId::STRIKE_IRONCLAD, false);
        event_begin(rc, event_id("AROMA_OF_CHAOS"), false);
        check("Aroma transformation succeeds", event_choose(rc, 0));
        const CardDef &replacement = card_def(rc.deck[0].id);
        check("Aroma uses the original character pool", replacement.pool == CardPool::IRONCLAD);
        check("Aroma transformation is not basic or event", replacement.rarity == Rarity::COMMON ||
              replacement.rarity == Rarity::UNCOMMON || replacement.rarity == Rarity::RARE);
        check("Aroma excludes the original card", rc.deck[0].id != CardId::STRIKE_IRONCLAD);
    }
    return failures == 0 ? 0 : 1;
}
