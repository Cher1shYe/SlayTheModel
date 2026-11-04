// Quest cards: Dowsing counts Unknown rooms and transforms into Abundance;
// Abundance offers three distinct upgraded character Power cards.
#include "sts2/battle.h"
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/map.h"

#include <iostream>

using namespace sts2;

namespace {
int checks = 0, failures = 0;
void check(bool ok, const char *label) {
    ++checks;
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
}

int main() {
    {
        // Dowsing.BeforeRoomEntered: five Unknown rooms (single-player room
        // count is one) transform the quest card into Abundance.
        RunContext rc;
        rc.init(31, 0);
        Card dowsing = rc.make_run_card(CardId::DOWSING, false);
        check(dowsing.bonusDamage == 5, "Dowsing starts with five rooms");
        check(rc.add_card_to_deck(dowsing), "Dowsing enters the deck");
        const int deckIndex = rc.deckCount - 1;
        int node = -1;
        for (int i = 0; i < rc.map.pointCount && node < 0; ++i) {
            for (int r = 0; r < MAP_MAX_ROWS && node < 0; ++r)
                for (int c = 0; c < MAP_WIDTH; ++c)
                    if (rc.map.index[r][c] == i) {
                        rc.map.nodes[i].type = static_cast<std::int8_t>(MapPointType::UNKNOWN);
                        node = i;
                        break;
                    }
        }
        check(node >= 0, "map has a node to mark Unknown");
        for (int room = 1; room <= 4; ++room) {
            rc.screen = RunScreen::MAP;
            rc.inBattle = false;
            rc.enter_map_point(node);
            check(rc.deck[deckIndex].id == CardId::DOWSING &&
                  static_cast<int>(rc.deck[deckIndex].bonusDamage) == 5 - room,
                  "Dowsing counts down one room per Unknown entry");
        }
        rc.screen = RunScreen::MAP;
        rc.inBattle = false;
        rc.enter_map_point(node);
        check(rc.deck[deckIndex].id == CardId::ABUNDANCE,
              "the fifth Unknown room transforms Dowsing into Abundance");
        check(rc.deck[deckIndex].bonusDamage == 0, "Abundance keeps no room counter");
    }
    {
        // Abundance.OnPlay: three distinct upgraded Power cards, one chosen
        // into the hand.
        Card deck[10];
        for (int i = 0; i < 10; ++i)
            deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, 300 + i);
        BattleContext b;
        b.init(Encounter::SETUP_CULTISTS_NORMAL, 9, deck, 10, 0, 80, 80);
        b.hand[b.handCount++] = make_card(CardId::ABUNDANCE, false, 700);
        const int hand = b.handCount - 1;
        Action a{};
        a.type = ActionType::PLAY_CARD;
        a.hand = static_cast<std::uint8_t>(hand);
        check(b.step(a), "Abundance plays");
        check(b.pending.op == ChoiceOp::OFFER_TO_HAND && b.pending.count == 3,
              "Abundance offers three cards");
        bool distinct = true;
        for (int i = 0; i < b.pending.count; ++i) {
            const Card &c = b.pending.cards[i];
            check(card_def(c.id).type == CardType::POWER, "offer is a Power card");
            check(c.upgraded, "offer is upgraded");
            check(card_def(c.id).pool == CardPool::IRONCLAD, "offer is from the character pool");
            for (int j = 0; j < i; ++j) distinct = distinct && b.pending.cards[j].id != c.id;
        }
        check(distinct, "Abundance offers are distinct");
        const std::uint16_t uid = b.pending.cards[0].uid;
        const CardId chosen = b.pending.cards[0].id;
        Action pick{};
        pick.type = ActionType::CHOOSE;
        pick.uid = uid;
        check(b.step(pick), "choosing an Abundance card resolves");
        bool inHand = false;
        for (int i = 0; i < b.handCount; ++i)
            inHand = inHand || (b.hand[i].id == chosen && b.hand[i].upgraded);
        check(inHand, "chosen upgraded Power card enters the hand");
    }
    {
        // LanternKey.ModifyUnknownMapPointRoomTypes / ModifyNextEvent: in the
        // third act every Unknown point is the WarHistorianRepy event.
        RunContext rc;
        rc.init(57, 0);
        rc.act = 2;
        check(rc.add_card_to_deck(rc.make_run_card(CardId::LANTERN_KEY, false)),
              "LanternKey enters the deck");
        int node = -1;
        for (int i = 0; i < rc.map.pointCount && node < 0; ++i)
            for (int r = 0; r < MAP_MAX_ROWS && node < 0; ++r)
                for (int c = 0; c < MAP_WIDTH; ++c)
                    if (rc.map.index[r][c] == i) {
                        rc.map.nodes[i].type = static_cast<std::int8_t>(MapPointType::UNKNOWN);
                        node = i;
                        break;
                    }
        check(node >= 0, "map node available for the LanternKey event");
        rc.screen = RunScreen::MAP;
        rc.inBattle = false;
        rc.enter_map_point(node);
        check(rc.screen == RunScreen::EVENT &&
              rc.eventId == event_war_historian_repy_id(),
              "LanternKey turns an Unknown point into WarHistorianRepy");
        check(event_option_count(rc) == 2, "WarHistorianRepy offers cage and chest");
        // UNLOCK_CAGE: one LanternKey is removed and HistoryCourse obtained.
        check(event_choose(rc, 0), "cage option resolves");
        bool key = false;
        for (int i = 0; i < rc.deckCount; ++i)
            key = key || rc.deck[i].id == CardId::LANTERN_KEY;
        check(!key, "the first LanternKey leaves the deck");
        check(run_has_relic(rc, RelicId::HISTORY_COURSE), "HistoryCourse obtained");
        check(rc.eventId < 0, "single-key event finishes after the first unlock");
    }
    {
        // UNLOCK_CHEST grants two potion rewards and two relic rewards; a
        // second LanternKey unlocks the other side on a second page.
        RunContext rc;
        rc.init(58, 0);
        check(rc.add_card_to_deck(rc.make_run_card(CardId::LANTERN_KEY, false)) &&
              rc.add_card_to_deck(rc.make_run_card(CardId::LANTERN_KEY, false)),
              "two LanternKeys enter the deck");
        rc.eventId = static_cast<std::int8_t>(event_war_historian_repy_id());
        rc.screen = RunScreen::EVENT;
        event_begin(rc, event_war_historian_repy_id(), false);
        check(event_choose(rc, 1), "chest option resolves");
        check(rc.pendingPotionCount == 2 && rc.pendingRelicCount == 2,
              "chest offers two potions and two relics");
        check(rc.eventPage == 1 && event_option_count(rc) == 1,
              "a second LanternKey unlocks the other side");
        check(event_choose(rc, 0), "second page resolves");
        check(run_has_relic(rc, RelicId::HISTORY_COURSE),
              "the second page unlocks the cage");
        check(rc.eventId < 0, "event finishes after the second unlock");
    }
    {
        // SpoilsMap.ModifyGeneratedMap: act 2 uses the hourglass map, whose
        // paths all converge on one centered treasure node.
        RunContext rc;
        rc.init(77, 0);
        check(rc.add_card_to_deck(rc.make_run_card(CardId::SPOILS_MAP, false)),
              "SpoilsMap enters the deck");
        check(rc.deck[rc.deckCount - 1].bonusDamage == 1,
              "SpoilsMap targets act 2 (index 1)");
        rc.start_act(1);
        const int treasureRow = rc.map.mapLength - 7;
        const int center = rc.map.at(treasureRow, MAP_WIDTH / 2);
        check(center >= 0 && rc.map.nodes[center].type ==
                                 static_cast<std::int8_t>(MapPointType::TREASURE),
              "the centered treasure node exists");
        int treasureCount = 0;
        int strayInRow = 0;
        for (int r = 0; r < MAP_MAX_ROWS; ++r)
            for (int c = 0; c < MAP_WIDTH; ++c) {
                const int idx = rc.map.at(r, c);
                if (idx < 0) continue;
                if (rc.map.nodes[idx].type ==
                    static_cast<std::int8_t>(MapPointType::TREASURE))
                    ++treasureCount;
                if (r == treasureRow && c != MAP_WIDTH / 2) ++strayInRow;
            }
        check(treasureCount == 1, "the hourglass map has exactly one treasure");
        check(strayInRow == 0, "all other treasure-row nodes were redirected");
        check(center >= 0 && rc.map.nodes[center].parentCount >= 2,
              "multiple paths converge on the treasure");
        // Every point is reachable from the start and can reach the boss.
        bool reachable[MAP_MAX_POINTS] = {};
        int queue[MAP_MAX_POINTS];
        int head = 0, tail = 0, seen = 0;
        queue[tail++] = rc.map.startIdx;
        reachable[rc.map.startIdx] = true;
        while (head < tail) {
            const int idx = queue[head++];
            ++seen;
            const MapNode &n = rc.map.nodes[idx];
            for (int i = 0; i < n.childCount; ++i)
                if (!reachable[n.children[i]]) {
                    reachable[n.children[i]] = true;
                    queue[tail++] = n.children[i];
                }
        }
        check(seen == rc.map.pointCount, "every hourglass point is reachable");
        bool reachesBoss[MAP_MAX_POINTS] = {};
        head = tail = seen = 0;
        queue[tail++] = rc.map.bossIdx;
        reachesBoss[rc.map.bossIdx] = true;
        while (head < tail) {
            const int idx = queue[head++];
            ++seen;
            const MapNode &n = rc.map.nodes[idx];
            for (int i = 0; i < n.parentCount; ++i)
                if (!reachesBoss[n.parents[i]]) {
                    reachesBoss[n.parents[i]] = true;
                    queue[tail++] = n.parents[i];
                }
        }
        check(seen == rc.map.pointCount, "every hourglass point reaches the boss");
    }
    {
        // SpoilsMap.OnQuestComplete: entering the act's treasure point grants
        // 600 gold and removes the card from the deck.
        RunContext rc;
        rc.init(78, 0);
        check(rc.add_card_to_deck(rc.make_run_card(CardId::SPOILS_MAP, false)),
              "SpoilsMap enters the deck for the quest run");
        rc.start_act(1);
        int treasure = -1;
        int treasureRow = -1, treasureCol = -1;
        for (int r = 0; r < MAP_MAX_ROWS && treasure < 0; ++r)
            for (int c = 0; c < MAP_WIDTH && treasure < 0; ++c) {
                const int idx = rc.map.at(r, c);
                if (idx >= 0 && rc.map.nodes[idx].type ==
                                    static_cast<std::int8_t>(MapPointType::TREASURE)) {
                    treasure = idx;
                    treasureRow = r;
                    treasureCol = c;
                }
            }
        check(treasure >= 0 && treasureRow == rc.map.mapLength - 7 &&
                  treasureCol == MAP_WIDTH / 2,
              "the quest treasure is the centered hourglass point");
        const int gold = rc.gold;
        rc.screen = RunScreen::MAP;
        rc.inBattle = false;
        rc.enter_map_point(treasure);
        check(rc.gold == gold + 600, "completing SpoilsMap grants 600 gold");
        bool stillHeld = false;
        for (int i = 0; i < rc.deckCount; ++i)
            stillHeld = stillHeld || rc.deck[i].id == CardId::SPOILS_MAP;
        check(!stillHeld, "a completed SpoilsMap leaves the deck");
    }
    std::cout << "quest cards: " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
