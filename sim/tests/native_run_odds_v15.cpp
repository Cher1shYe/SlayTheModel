// Source-port regressions for the v15 run-odds audit (docs/content-audit.md):
// UnknownMapPointOdds shop blacklist, PotionRewardOdds elite update and White
// Beast Statue, EncounterModel.CalculateGoldProportion, merchant relic costs and
// A6 card removal, native first-act selection for the fully unlocked default.
// Expectations are derived from the v0.111.0 decompilation, not a DLL trace.
#include "sts2/run.h"
#include "sts2/relics.h"
#include <cassert>
#include <cmath>
#include <iostream>
#include <memory>
#include <string>

using namespace sts2;

namespace {
std::unique_ptr<RunContext> base(const std::string &seed, int ascension = 10) {
    auto r = std::make_unique<RunContext>();
    r->init_seed(seed, ascension);
    r->screen = RunScreen::SHOP;
    return r;
}

void roundtrip(RunContext &r) {
    auto saved = std::make_unique<RunContext>();
    assert(RunContext::restore(r.serialize(), *saved));
    assert(saved->serialize() == r.serialize());
}

int native_round(double v) { return static_cast<int>(std::nearbyint(v)); }

// ---- UnknownMapPointOdds / RunManager.BuildRoomTypeBlacklist ----------------
void unknown_room_shop_blacklist() {
    auto r = base("UNKNOWNSHOP");
    r->curRow = r->curCol = -1;  // no children check: only the previous room matters
    auto force_shop = [&] {
        r->unknownMonsterOdds = 0.0f;
        r->unknownTreasureOdds = 0.0f;
        r->unknownShopOdds = 1.0f;
    };
    force_shop();
    r->lastPointType = static_cast<std::int8_t>(MapPointType::SHOP);
    assert(r->roll_unknown_room_type() == static_cast<int>(RoomType::EVENT));
    // A blacklisted type is not rolled and its odds do not grow.
    assert(r->unknownShopOdds == 1.0f);
    force_shop();
    r->lastPointType = static_cast<std::int8_t>(MapPointType::MONSTER);
    assert(r->roll_unknown_room_type() == static_cast<int>(RoomType::SHOP));

    // Through enter_map_point: a Shop point, then an Unknown child of it.
    int checked = 0, unknownShopChain = 0;
    for (int s = 0; s < 400 && (checked < 3 || unknownShopChain < 2); ++s) {
        auto run = base("UNKNOWNSHOPMAP" + std::to_string(s));
        const ActMap &map = run->map;
        for (int i = 0; i < map.pointCount; ++i) {
            const MapNode &node = map.nodes[i];
            if (node.type != static_cast<int>(MapPointType::SHOP) &&
                node.type != static_cast<int>(MapPointType::UNKNOWN)) continue;
            for (int c = 0; c < node.childCount; ++c) {
                const int child = node.children[c];
                if (map.nodes[child].type != static_cast<int>(MapPointType::UNKNOWN)) continue;
                auto t = std::make_unique<RunContext>(*run);
                if (node.type == static_cast<int>(MapPointType::SHOP)) {
                    t->enter_map_point(i);
                    assert(t->lastPointType == static_cast<int>(MapPointType::SHOP));
                    ++checked;
                } else {
                    // Unknown that rolls Shop also blacklists the next Unknown.
                    t->unknownMonsterOdds = t->unknownTreasureOdds = 0.0f;
                    t->unknownShopOdds = 1.0f;
                    bool allShop = node.childCount > 0;
                    for (int k = 0; k < node.childCount; ++k)
                        allShop &= map.nodes[node.children[k]].type == static_cast<int>(MapPointType::SHOP);
                    if (allShop) continue;
                    t->enter_map_point(i);
                    if (t->screen != RunScreen::SHOP) continue;
                    assert(t->lastPointType == static_cast<int>(MapPointType::SHOP));
                    ++unknownShopChain;
                }
                t->unknownMonsterOdds = t->unknownTreasureOdds = 0.0f;
                t->unknownShopOdds = 1.0f;
                t->screen = RunScreen::MAP;
                t->enter_map_point(child);
                assert(t->screen != RunScreen::SHOP);
                break;
            }
        }
    }
    assert(checked >= 3 && unknownShopChain >= 2);
}

// ---- PotionRewardOdds.Roll ---------------------------------------------------
void potion_reward_odds() {
    int eliteBonusDrops = 0, normal = 0;
    for (int s = 0; s < 300; ++s) {
        for (bool elite : {false, true}) {
            auto r = base("POTIONODDS" + std::to_string(s));
            r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
            r->combatIsElite = elite;
            r->combatIsBoss = false;
            r->potionRewardOdds = 0.4f;
            Rng probe = r->playerRng[PRNG_REWARDS];
            const float roll = probe.next_float();
            const float threshold = 0.4f + (elite ? 0.125f : 0.0f);
            r->battle.outcome = Outcome::PLAYER_VICTORY;
            r->finish_combat();
            const bool dropped = roll < threshold;
            assert((r->pendingPotionCount > 0) == dropped);
            assert(r->potionRewardOdds == (dropped ? 0.4f - 0.1f : 0.4f + 0.1f));
            if (elite && roll >= 0.4f && dropped) ++eliteBonusDrops;
            if (!elite) ++normal;
        }
    }
    assert(eliteBonusDrops > 0 && normal > 0);

    // White Beast Statue: forced, no RNG and no odds change.
    auto r = base("POTIONSTATUE");
    assert(r->add_relic(RelicId::WHITE_BEAST_STATUE));
    r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
    r->combatIsElite = r->combatIsBoss = false;
    r->potionRewardOdds = 0.4f;
    const auto before = r->playerRng[PRNG_REWARDS].counter;
    Rng probe = r->playerRng[PRNG_REWARDS];
    const int expectedGold = probe.next_int(7, 15);  // first rewards draw is now the gold roll (A3)
    r->battle.outcome = Outcome::PLAYER_VICTORY;
    r->finish_combat();
    assert(r->pendingPotionCount == 1 && r->potionRewardOdds == 0.4f);
    assert(r->pendingGoldReward == expectedGold);
    assert(r->playerRng[PRNG_REWARDS].counter > before);
}

// ---- EncounterModel.CalculateGoldProportion ----------------------------------
int gold_after(Encounter encounter, int escaped, bool fatEscaped, bool stolen, int ascension) {
    auto r = base("GOLDPROPORTION", ascension);
    r->begin_combat(encounter);
    r->combatIsElite = r->combatIsBoss = false;
    r->battle.escapedMonsterCount = static_cast<std::uint8_t>(escaped);
    r->battle.fatGremlinEscaped = fatEscaped;
    r->battle.mercGoldStolen = stolen;
    roundtrip(*r);
    r->battle.outcome = Outcome::PLAYER_VICTORY;
    r->finish_combat();
    return r->pendingGoldReward;
}

void gold_proportion() {
    const int full = gold_after(Encounter::SETUP_THIEVING_HOPPER_WEAK, 0, false, false, 10);
    assert(full >= 7 && full <= 15);
    assert(gold_after(Encounter::SETUP_THIEVING_HOPPER_WEAK, 1, false, false, 10) == 0);
    assert(gold_after(Encounter::SETUP_GREMLIN_MERC_NORMAL, 0, false, false, 10) >= 7);
    for (int asc : {0, 10}) {
        const int lo = native_round((asc >= 3 ? 7 : 10) * 0.5), hi = native_round((asc >= 3 ? 15 : 20) * 0.5);
        const int half = gold_after(Encounter::SETUP_GREMLIN_MERC_NORMAL, 1, true, false, asc);
        assert(half >= lo && half <= hi);  // A10: 3.5 -> 4 and 7.5 -> 8 (half to even)
    }
    assert(gold_after(Encounter::SETUP_GREMLIN_MERC_NORMAL, 1, true, true, 10) == 0);

    // A real escape: the hopper's escape move increments the counter.
    int escapes = 0;
    for (int s = 0; s < 40 && escapes == 0; ++s) {
        auto r = base("HOPPERESCAPE" + std::to_string(s));
        r->begin_combat(Encounter::SETUP_THIEVING_HOPPER_WEAK);
        r->battle.player.maxHp = r->battle.player.hp = 900;
        for (int turn = 0; turn < 40 && r->battle.outcome == Outcome::UNDECIDED; ++turn) {
            const auto legal = r->battle.legal_actions();
            Action end{};
            bool found = false;
            for (const Action &a : legal) if (a.type == ActionType::END_TURN) { end = a; found = true; }
            if (!found) break;
            r->battle.step(end);
        }
        if (r->battle.outcome == Outcome::PLAYER_VICTORY && r->battle.monsters[0].hp > 0) {
            assert(r->battle.escapedMonsterCount == 1);
            ++escapes;
        }
    }
    assert(escapes == 1);
}

// ---- Merchant prices ---------------------------------------------------------
void merchant_prices() {
    for (int asc : {0, 6, 10}) {
        for (int used : {0, 2}) {
            auto r = base("REMOVALPRICE", asc);
            r->cardShopRemovalsUsed = used;
            r->roll_shop();
            assert(r->removalBasePrice == (asc >= 6 ? 100 + 50 * used : 75 + 25 * used));
        }
    }
    const int cost[] = {0, 175, 225, 275, 200};  // by Rarity: COMMON, UNCOMMON, RARE, SPECIAL(Shop)
    int seen[5]{}, belowOldMinimum = 0;
    for (int s = 0; s < 300; ++s) {
        auto r = base("RELICPRICE" + std::to_string(s));
        r->roll_shop();
        for (int i = 0; i < r->shopRelicCount; ++i) {
            const int rarity = static_cast<int>(relic_def(static_cast<RelicId>(r->shopRelics[i])).rarity);
            assert(rarity >= 1 && rarity <= 4);
            const int price = r->shopRelicBasePrices[i];
            assert(price >= native_round(cost[rarity] * 0.85) && price <= native_round(cost[rarity] * 1.15));
            belowOldMinimum += price < native_round((cost[rarity] + 25) * 0.85);
            ++seen[rarity];
        }
        for (int i = 5; i < r->shopCount; ++i) {  // colorless: Uncommon 86, Rare 172 (not 173)
            const bool rare = card_def(r->shopCards[i].id).rarity == Rarity::RARE;
            const int base = rare ? 172 : 86;
            assert(r->shopBasePrices[i] >= native_round(base * 0.95) && r->shopBasePrices[i] <= native_round(base * 1.05));
        }
    }
    assert(seen[1] && seen[2] && seen[3] && seen[4] && belowOldMinimum > 0);
}

// ---- Default profile: native first-act selection -----------------------------
void first_act_default() {
    int underdocks = 0, total = 0;
    for (int s = 0; s < 400; ++s) {
        auto r = std::make_unique<RunContext>();
        r->init(9'100'000 + s, 10);
        assert(r->nativeProgress.underdocksUnlocked);
        assert(r->actTypes[0] == ActType::OVERGROWTH || r->actTypes[0] == ActType::UNDERDOCKS);
        underdocks += r->actTypes[0] == ActType::UNDERDOCKS;
        ++total;
    }
    assert(underdocks > total * 2 / 5 && underdocks < total * 3 / 5);
    // Explicitly fixing the act still works.
    auto r = std::make_unique<RunContext>();
    NativeProgressContext progress;
    r->init_with_context(42, 10, static_cast<int>(ActType::OVERGROWTH), progress);
    assert(r->actTypes[0] == ActType::OVERGROWTH);
}
}  // namespace

int main() {
    unknown_room_shop_blacklist();
    potion_reward_odds();
    gold_proportion();
    merchant_prices();
    first_act_default();
    std::cout << "native_run_odds_v15 ok\n";
    return 0;
}
