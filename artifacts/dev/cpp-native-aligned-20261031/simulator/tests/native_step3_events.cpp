// Round 4 step 3, batch 1: native event order, epoch filter, visited ids >= 64,
// Whispering Hollow / Wood Carvings / Zen Weaver, Slither and the physical
// potion belt. Expectations come from the v0.111.0 decompilation (no DLL
// fixtures were available for this batch; see the step README).
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <vector>

#include "sts2/card_candidates.h"
#include "sts2/monsters.h"
#include "sts2/observe.h"
#include "sts2/potion_slots.h"
#include "sts2/relic_card_rewards.h"
#include "sts2/relics.h"
#include "sts2/run.h"
#include "sts2/search.h"

using namespace sts2;

namespace {

int checks = 0;
void check(bool ok, const char *what) {
    ++checks;
    if (!ok) {
        std::cerr << "FAIL " << what << "\n";
        std::exit(1);
    }
}

int event(const char *name) {
    for (int i = 0; i < event_count(); ++i)
        if (!std::strcmp(event_info(i)->name, name)) return i;
    std::cerr << "missing event " << name << "\n";
    std::exit(1);
}

// Native ActModel.AllEvents + ModelDb.AllSharedEvents (declaration order).
const std::vector<const char *> SHARED = {
    "BRAIN_LEECH", "CRYSTAL_SPHERE", "DOLL_ROOM", "FAKE_MERCHANT", "POTION_COURIER",
    "RANWID_THE_ELDER", "RELIC_TRADER", "ROOM_FULL_OF_CHEESE", "SELF_HELP_BOOK",
    "SLIPPERY_BRIDGE", "STONE_OF_ALL_TIME", "SYMBIOTE", "TEA_MASTER",
    "THE_FUTURE_OF_POTIONS", "THE_LEGENDS_WERE_TRUE", "THIS_OR_THAT",
    "WAR_HISTORIAN_REPY", "WELCOME_TO_WONGOS"};
const std::vector<const char *> OVERGROWTH = {
    "AROMA_OF_CHAOS", "BYRDONIS_NEST", "DENSE_VEGETATION", "JUNGLE_MAZE_ADVENTURE",
    "LUMINOUS_CHOIR", "MORPHIC_GROVE", "SAPPHIRE_SEED", "SUNKEN_STATUE", "TABLET_OF_TRUTH",
    "UNREST_SITE", "WELLSPRING", "WHISPERING_HOLLOW", "WOOD_CARVINGS"};
const std::vector<const char *> HIVE = {
    "AMALGAMATOR", "BUGSLAYER", "COLORFUL_PHILOSOPHERS", "COLOSSAL_FLOWER",
    "FIELD_OF_MAN_SIZED_HOLES", "INFESTED_AUTOMATON", "LOST_WISP", "SPIRIT_GRAFTER",
    "THE_LANTERN_KEY", "ZEN_WEAVER"};
const std::vector<const char *> GLORY = {
    "BATTLEWORN_DUMMY", "GRAVE_OF_THE_FORGOTTEN", "HUNGRY_FOR_MUSHROOMS", "REFLECTIONS",
    "ROUND_TEA_PARTY", "TRIAL", "TINKER_TIME"};
const std::vector<const char *> UNDERDOCKS = {
    "ABYSSAL_BATHS", "DROWNING_BEACON", "ENDLESS_CONVEYOR", "PUNCH_OFF",
    "SPIRALING_WHIRLPOOL", "SUNKEN_STATUE", "SUNKEN_TREASURY", "DOORS_OF_LIGHT_AND_DARK",
    "TRASH_HEAP", "WATERLOGGED_SCRIPTORIUM"};

void check_pool(ActType act, const std::vector<const char *> &own,
                const NativeProgressContext *progress, const char *skip) {
    std::vector<int> expected;
    std::vector<const char *> names = own;
    names.insert(names.end(), SHARED.begin(), SHARED.end());
    for (const char *name : names) {
        const int id = event(name);  // every native event must be registered
        if (skip && !std::strcmp(name, skip)) continue;
        if (event_info(id)->status != EventStatus::UNSUPPORTED) expected.push_back(id);
    }
    int ids[128];
    const int n = event_pool_for_act_type(act, ids, 128, progress);
    check(n == static_cast<int>(expected.size()), "event pool size");
    for (int i = 0; i < n; ++i) check(ids[i] == expected[i], "event pool native order");
}

RunContext start(const char *name, int gold = 300) {
    RunContext r;
    r.init(42, 0);
    r.gold = gold;
    r.hp = 50;
    event_begin(r, event(name), false);
    return r;
}

int count_card(const RunContext &r, CardId id) {
    int n = 0;
    for (int i = 0; i < r.deckCount; ++i) n += r.deck[i].id == id;
    return n;
}

void select_grid(RunContext &r, std::initializer_list<int> cards) {
    for (int i : cards) check(r.step({RunActionType::SELECT_GRID_CARD, i}), "grid select");
    check(r.step({RunActionType::CONFIRM_GRID_CARDS, 0}), "grid confirm");
}

// Mirror of events.cpp decimal_gold_from_float for the rounding check.
void decimal_gold_for_test(int base, float f, int &plain, int &withBowler) {
    char text[32];
    std::snprintf(text, sizeof text, "%.6e", static_cast<double>(f));
    long long mantissa = 0; int exponent = 0; bool negative = false; const char *p = text;
    if (*p == '-') { negative = true; ++p; }
    for (; *p && *p != 'e'; ++p) if (*p >= '0' && *p <= '9') mantissa = mantissa * 10 + (*p - '0');
    if (*p == 'e') exponent = std::atoi(p + 1);
    const int scale = 6 - exponent;
    long double value = static_cast<long double>(negative ? -mantissa : mantissa);
    for (int i = 0; i < scale; ++i) value /= 10;
    plain = static_cast<int>(base + value);
    withBowler = static_cast<int>((base + value) * 1.25L);
}

void set_page_for_test(RunContext &r, int page, int options) {
    r.eventPage = static_cast<std::int8_t>(page);
    r.eventChoiceCount = static_cast<std::int8_t>(options);
}

bool deck_mask_has_for_test(const RunContext &r, int i) { return (r.eventDeckMask[i / 64] >> (i % 64)) & 1u; }

}  // namespace

int main() {
    // --- event bag order and epoch filter ------------------------------------
    check_pool(ActType::OVERGROWTH, OVERGROWTH, nullptr, nullptr);
    check_pool(ActType::HIVE, HIVE, nullptr, nullptr);
    check_pool(ActType::GLORY, GLORY, nullptr, nullptr);
    check_pool(ActType::UNDERDOCKS, UNDERDOCKS, nullptr, nullptr);
    {
        NativeProgressContext p;
        p.event2EpochRevealed = false;
        check_pool(ActType::GLORY, GLORY, &p, "REFLECTIONS");
        p = NativeProgressContext();
        p.event3EpochRevealed = false;
        check_pool(ActType::HIVE, HIVE, &p, "COLORFUL_PHILOSOPHERS");
        p = NativeProgressContext();
        p.event1EpochRevealed = false;
        check_pool(ActType::UNDERDOCKS, UNDERDOCKS, &p, "TRASH_HEAP");
    }
    check(event("ZEN_WEAVER") >= 64, "test covers an id beyond the old 64-bit mask");
    check(event_count() <= PUB_EVENT_N && event_count() <= MAX_EVENTS, "event id capacity");

    // --- visited events beyond id 63 -----------------------------------------
    {
        RunContext r;
        r.init(123, 0);
        r.act = 1;
        r.gold = 200;
        const int zen = event("ZEN_WEAVER"), well = event("WELLSPRING");
        const int node = r.map.at(r.curRow, r.curCol);
        r.map.nodes[node].type = static_cast<int>(MapPointType::UNKNOWN);
        r.unknownMonsterOdds = r.unknownEliteOdds = r.unknownTreasureOdds = r.unknownShopOdds = -1;
        r.eventBagN = 2;
        r.eventBagPos = 0;
        r.eventBag[0] = static_cast<std::uint16_t>(zen);
        r.eventBag[1] = static_cast<std::uint16_t>(well);
        r.enter_map_point(node);
        check(r.eventId == zen, "Zen Weaver entered");
        check((r.visitedEvents[zen / 64] >> (zen % 64)) & 1u, "high event id marked visited");
        RunContext again = r;
        again.eventId = -1;
        again.screen = RunScreen::MAP;
        again.eventBagPos = 0;
        again.unknownMonsterOdds = again.unknownEliteOdds = again.unknownTreasureOdds =
            again.unknownShopOdds = -1;
        again.enter_map_point(node);
        check(again.eventId == well, "visited high id is skipped");
        std::vector<float> obs = public_observation(r);
        check(static_cast<int>(obs.size()) == PUBLIC_OBS_DIM, "observation size");
        RunContext restored;
        check(RunContext::restore(r.serialize(), restored), "snapshot with high event id");
    }

    // --- Zen Weaver -----------------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        r.gold = 124;
        check(!event_is_allowed(r, event("ZEN_WEAVER")), "Zen Weaver needs 125 gold");
        r.gold = 125;
        check(event_is_allowed(r, event("ZEN_WEAVER")), "Zen Weaver allowed at 125");

        r = start("ZEN_WEAVER", 200);
        check(event_option_count(r) == 3, "Zen Weaver has three options");
        check(event_option_available(r, 1) && !event_option_available(r, 2), "250 option locked");
        const int deck = r.deckCount;
        check(r.step({RunActionType::EVENT_CHOICE, 0}), "breathing techniques");
        check(r.gold == 150 && r.deckCount == deck + 2 && count_card(r, CardId::ENLIGHTENMENT) == 2,
              "two Enlightenment for 50 gold");
        check(!r.deck[r.deckCount - 1].upgraded && r.screen == RunScreen::MAP, "unupgraded, finished");

        r = start("ZEN_WEAVER", 200);
        r.add_relic(RelicId::TOXIC_EGG);
        check(r.step({RunActionType::EVENT_CHOICE, 0}), "breathing techniques with Toxic Egg");
        check(r.deck[r.deckCount - 1].upgraded && r.deck[r.deckCount - 2].upgraded,
              "Toxic Egg upgrades added skills");

        r = start("ZEN_WEAVER", 300);
        check(r.step({RunActionType::EVENT_CHOICE, 2}), "arachnid acupuncture");
        check(r.cardGrid.kind == 6 && r.cardGrid.minSelect == 2 && r.cardGrid.maxSelect == 2,
              "remove two cards");
        check(r.gold == 50, "250 gold paid");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot during removal");
        select_grid(r, {0, 9});
        check(r.deckCount == 8 && count_card(r, CardId::BASH) == 0, "two cards removed");

        r = start("ZEN_WEAVER", 130);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.cardGrid.maxSelect == 1 && r.gold == 5,
              "emotional awareness removes one for 125");
    }

    // --- Whispering Hollow ----------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        r.gold = 43;
        check(!event_is_allowed(r, event("WHISPERING_HOLLOW")), "needs 44 gold");
        r = start("WHISPERING_HOLLOW", 120);
        Rng rng(r.seed, "WHISPERING_HOLLOW");
        const int gold = 35 + rng.next_int_range(-9, 10);
        check(r.eventData[0] == gold && gold >= 26 && gold <= 44, "CalculateVars gold");
        check(r.eventRng.counter == 1, "one event RNG call before options");
        RunContext potion = r;
        check(potion.step({RunActionType::EVENT_CHOICE, 0}), "gold for potions");
        check(potion.gold == 120 - gold && potion.screen == RunScreen::REWARDS, "potion rewards offered");
        int offered = 0;
        for (int i = 0; i < potion.pendingPotionCount; ++i) offered += potion.pendingPotions[i] != 0;
        check(offered == 2, "two potion rewards");

        const int deck = r.deckCount;
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.eventCardSelection == 4, "hug selects");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 9}), "transform Bash");
        check(r.deckCount == deck && count_card(r, CardId::BASH) == 0, "Bash transformed");
        check(r.hp == 41 && r.screen == RunScreen::MAP, "nine damage after transform");
    }

    // --- Wood Carvings and Slither ---------------------------------------------
    {
        RunContext r = start("WOOD_CARVINGS");
        check(event_option_count(r) == 3 && event_option_available(r, 1), "three options, snake open");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventCardSelection == 7, "bird selects");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 9}), "bird on Bash");
        check(count_card(r, CardId::PECK) == 1 && count_card(r, CardId::BASH) == 0 &&
              !r.deck[r.deckCount - 1].upgraded, "Bash became Peck");

        r = start("WOOD_CARVINGS");
        r.add_relic(RelicId::TOXIC_EGG);
        check(r.step({RunActionType::EVENT_CHOICE, 2}) && r.step({RunActionType::EVENT_SELECT_CARD, 5}),
              "torus on Defend");
        check(count_card(r, CardId::TORIC_TOUGHNESS) == 1 && r.deck[r.deckCount - 1].upgraded,
              "Defend became Toric Toughness, Toxic Egg upgrades it");

        r = start("WOOD_CARVINGS");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.eventCardSelection == 9, "snake selects");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 0}), "slither Strike");
        check(r.deck[0].enchantment == EnchantmentId::SLITHER && r.deck[0].enchantmentAmount == 1,
              "Strike has Slither");
        RunContext restored;
        check(RunContext::restore(r.serialize(), restored), "snapshot with Slither");

        // Snake is locked when nothing can take Slither (curses only).
        RunContext locked;
        locked.init(42, 0);
        locked.deckCount = 0;
        locked.add_card_to_deck(locked.make_run_card(CardId::STRIKE_IRONCLAD, false));
        locked.deck[0].enchantment = EnchantmentId::SWIFT;
        locked.deck[0].enchantmentAmount = 1;
        locked.gold = 300;
        event_begin(locked, event("WOOD_CARVINGS"), false);
        check(!event_option_available(locked, 1), "snake locked");

        // Slither.AfterCardDrawn: combat-long random 0..3 from CombatEnergyCosts.
        Card c = r.deck[0];
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 7, &c, 1, 0, 80, 80);
        bool found = false;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].uid != c.uid) continue;
            found = true;
            check(card_cost(b.hand[i]) >= 0 && card_cost(b.hand[i]) <= 3, "Slither cost range");
        }
        check(found, "Slither card drawn");
        check(b.energyCostRng.counter >= 1, "Slither consumed the energy cost RNG");
        BattleContext plain;
        Card p = c;
        p.enchantment = EnchantmentId::NONE;
        p.enchantmentAmount = 0;
        plain.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 7, &p, 1, 0, 80, 80);
        check(plain.energyCostRng.counter + 1 == b.energyCostRng.counter, "exactly one Slither roll");
    }

    // --- physical potion belt ----------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        r.potionSlots = 3;
        r.potions[0] = static_cast<int>(PotionId::FIRE_POTION);
        r.potions[1] = 0;
        r.potions[2] = static_cast<int>(PotionId::BLOCK_POTION);
        r.potionCount = 2;
        RunContext restored;
        check(RunContext::restore(r.serialize(), restored), "run belt with a hole is valid");
        r.pendingPotionCount = 1;
        r.pendingPotions[0] = static_cast<int>(PotionId::FIRE_POTION);
        r.screen = RunScreen::REWARDS;
        bool slot2 = false, slot1 = false;
        for (const RunAction &a : r.legal_actions()) {
            if (a.type != RunActionType::DISCARD_POTION) continue;
            slot1 |= a.index == 1;
            slot2 |= a.index == 2;
        }
        check(slot2 && !slot1, "discard actions address occupied physical slots");
        check(r.step({RunActionType::DISCARD_POTION, 2}), "discard slot 3");
        check(r.potionCount == 1 && r.potions[0] && !r.potions[2], "discard leaves a hole");
        check(!r.step({RunActionType::DISCARD_POTION, 2}), "empty slot cannot be discarded");
        r.potions[2] = static_cast<int>(PotionId::BLOCK_POTION);
        r.potionCount = 2;
        check(r.step({RunActionType::TAKE_POTION_REWARD, 0}), "reward fills first empty slot");
        check(r.potions[1] == static_cast<int>(PotionId::FIRE_POTION) && r.potionCount == 3, "slot 2 filled");

        // Combat keeps holes and syncs every slot back.
        RunContext c;
        c.init(42, 0);
        c.potionSlots = 3;
        c.potions[0] = static_cast<int>(PotionId::FIRE_POTION);
        c.potions[2] = static_cast<int>(PotionId::BLOCK_POTION);
        c.potionCount = 2;
        c.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        check(c.battle.potionCount == 2 && c.battle.potions[2] == static_cast<int>(PotionId::BLOCK_POTION),
              "battle copies physical slots");
        bool usable2 = false;
        for (const Action &a : c.battle.legal_actions())
            usable2 |= a.type == ActionType::USE_POTION && a.hand == 2;
        check(usable2, "potion after a hole is usable in combat");
        c.sync_potions_from_battle();
        check(c.potionCount == 2 && c.potions[2] == static_cast<int>(PotionId::BLOCK_POTION),
              "sync keeps the potion after a hole");

        // Stone of All Time: Rng.NextItem over occupied potions only.
        RunContext s;
        s.init(42, 0);
        s.act = 1;
        s.potionSlots = 3;
        s.potions[1] = static_cast<int>(PotionId::FIRE_POTION);
        s.potions[2] = static_cast<int>(PotionId::BLOCK_POTION);
        s.potionCount = 2;
        event_begin(s, event("STONE_OF_ALL_TIME"), false);
        const int k = s.eventData[0];
        check(k == 0 || k == 1, "index over occupied potions");
        const int lifted = s.potions[1 + k];
        check(s.step({RunActionType::EVENT_CHOICE, 0}), "lift");
        check(s.potionCount == 1 && s.potions[1 + k] == 0 && s.potions[2 - k] != 0 && lifted != 0,
              "the chosen occupied potion was removed in place");
    }

    // --- batch 2 ----------------------------------------------------------------
    {
        RunContext r = start("BUGSLAYER");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && count_card(r, CardId::EXTERMINATE) == 1, "Exterminate");
        r = start("BUGSLAYER");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && count_card(r, CardId::SQUASH) == 1, "Squash");
    }
    {
        RunContext r = start("INFESTED_AUTOMATON");
        const Rng before = r.playerRng[PRNG_REWARDS];
        check(r.step({RunActionType::EVENT_CHOICE, 0}), "study");
        const Card &added = r.deck[r.deckCount - 1];
        check(card_def(added.id).type == CardType::POWER && card_def(added.id).pool == CardPool::IRONCLAD,
              "Study adds an Ironclad Power");
        check(r.playerRng[PRNG_REWARDS].counter == before.counter + 2, "rarity roll and pick, no upgrade roll");
        r = start("INFESTED_AUTOMATON");
        check(r.step({RunActionType::EVENT_CHOICE, 1}), "touch core");
        const CardDef &zero = card_def(r.deck[r.deckCount - 1].id);
        check(zero.cost == 0 && zero.pool == CardPool::IRONCLAD, "Touch Core adds a canonical 0-cost card");
    }
    {
        RunContext r;
        r.init(42, 0);
        r.gold = 99;
        check(!event_is_allowed(r, event("MORPHIC_GROVE")), "Morphic Grove needs 100 gold");
        r = start("MORPHIC_GROVE", 140);
        const Rng eventBefore = r.eventRng, nicheBefore = r.runRng[RNG_NICHE];
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.gold == 0, "group steals all gold");
        check(r.cardGrid.kind == 7 && r.cardGrid.eventRng && r.cardGrid.maxSelect == 2, "transform two");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot with event-rng transform grid");
        select_grid(r, {9, 0});
        check(count_card(r, CardId::BASH) == 0 && r.deckCount == 10, "two transformed");
        check(r.eventRng.counter == eventBefore.counter + 2 &&
              r.runRng[RNG_NICHE].counter == nicheBefore.counter, "transforms use the event Rng");
        r = start("MORPHIC_GROVE", 140);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.maxHp == 85 && r.gold == 140, "loner +5 max HP");
    }
    {
        RunContext r = start("COLORFUL_PHILOSOPHERS");
        check(event_option_count(r) == 3, "three of four other colors offered");
        Rng rng(r.seed, "COLORFUL_PHILOSOPHERS");
        const int removed = rng.next_int_exclusive(4);
        const CardPool order[] = {CardPool::NECROBINDER, CardPool::REGENT, CardPool::SILENT, CardPool::DEFECT};
        int k = 0;
        for (int i = 0; i < 4; ++i)
            if (i != removed) check(r.eventData[k++] == static_cast<int>(order[i]), "color order kept");
        const CardPool chosen = static_cast<CardPool>(r.eventData[1]);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.screen == RunScreen::REWARDS, "rewards offered");
        int rewards = 0;
        const Rarity rarities[] = {Rarity::COMMON, Rarity::UNCOMMON, Rarity::RARE};
        for (int slot = 0; slot < MAX_CARD_REWARDS; ++slot) {
            if (!r.rewardCardPending[slot]) continue;
            check(r.rewardCardCounts[slot] == 3, "three cards per reward");
            for (int i = 0; i < 3; ++i) {
                const CardDef &d = card_def(r.rewardCards[slot][i].id);
                check(d.pool == chosen && d.rarity == rarities[rewards], "pool and rarity of each reward");
            }
            ++rewards;
        }
        check(rewards == 3, "three card rewards");
        RunContext solo;
        solo.init_with_context(42, 0, static_cast<int>(ActType::OVERGROWTH), [] {
            NativeProgressContext p; p.unlockedCharacterMask = 1; return p; }());
        check(!event_is_allowed(solo, event("COLORFUL_PHILOSOPHERS")), "needs another unlocked character");
    }
    {
        RunContext r = start("ROUND_TEA_PARTY");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && run_has_relic(r, RelicId::ROYAL_POISON) &&
              r.hp == r.maxHp, "enjoy tea: Royal Poison then full heal");
        r = start("ROUND_TEA_PARTY");
        const int relics = r.relicCount;
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.eventPage == 1 && event_option_count(r) == 1,
              "pick fight page");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.hp == 39 && r.relicCount == relics + 1,
              "continue fight: 11 damage and a relic");
        RunContext low;
        low.init(42, 0);
        low.hp = 11;
        check(!event_is_allowed(low, event("ROUND_TEA_PARTY")), "needs 12 HP");
    }
    {
        RunContext r;
        r.init(42, 0);
        r.gold = 150;
        r.act = 2;
        check(!event_is_allowed(r, event("TEA_MASTER")), "Tea Master not in act 3");
        r = start("TEA_MASTER", 160);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.gold == 10 && run_has_relic(r, RelicId::EMBER_TEA),
              "ember tea for 150");
        r = start("TEA_MASTER", 160);
        check(r.step({RunActionType::EVENT_CHOICE, 2}) && r.gold == 160 &&
              run_has_relic(r, RelicId::TEA_OF_DISCOURTESY), "free tea of discourtesy");
    }
    {
        RunContext r = start("LUMINOUS_CHOIR", 200);
        Rng rng(r.seed, "LUMINOUS_CHOIR");
        check(r.eventData[0] == 149 - rng.next_int_range(0, 50), "tribute cost");
        RunContext tribute = r;
        const int relics = r.relicCount, cost = r.eventData[0];
        check(tribute.step({RunActionType::EVENT_CHOICE, 1}) && tribute.gold == 200 - cost &&
              tribute.relicCount == relics + 1, "offer tribute");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.cardGrid.maxSelect == 2, "reach into the flesh");
        RunContext mid;
        check(RunContext::restore(r.serialize(), mid), "snapshot with Spore Mind pending");
        select_grid(r, {0, 1});
        check(r.deckCount == 9 && count_card(r, CardId::SPORE_MIND) == 1, "two removed, Spore Mind added");
        RunContext poor;
        poor.init(42, 0);
        poor.gold = 148;
        check(!event_is_allowed(poor, event("LUMINOUS_CHOIR")), "needs 149 gold");

        // Spore Mind: a playable 1-cost Exhaust curse without an effect.
        Card spore = r.deck[r.deckCount - 1];
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 7, &spore, 1, 0, 80, 80);
        int idx = -1;
        for (int i = 0; i < b.handCount; ++i) if (b.hand[i].id == CardId::SPORE_MIND) idx = i;
        check(idx >= 0, "Spore Mind drawn");
        const int energy = b.player.energy;
        check(b.play_card(idx, 0) && b.player.energy == energy - 1 && b.exhaustCount == 1, "Spore Mind exhausts");
    }

    // --- batch 3 ----------------------------------------------------------------
    {
        RunContext r = start("DOLL_ROOM");
        Rng rng(r.seed, "DOLL_ROOM");
        const RelicId declared[3] = {RelicId::DAUGHTER_OF_THE_WIND, RelicId::MR_STRUGGLES, RelicId::BING_BONG};
        const RelicId expected = declared[rng.next_int_range(0, 3)];
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && run_has_relic(r, expected) && r.hp == 50,
              "random doll without damage");
        r = start("DOLL_ROOM");
        check(r.step({RunActionType::EVENT_CHOICE, 2}) && r.hp == 35 && r.eventPage == 1 &&
              event_option_count(r) == 3, "examine: 15 damage, choose one of three");
        RelicId sorted[3] = {RelicId::BING_BONG, RelicId::DAUGHTER_OF_THE_WIND, RelicId::MR_STRUGGLES};
        Rng shuffle(r.seed, "DOLL_ROOM");
        shuffle.shuffle(sorted, 3);
        for (int i = 0; i < 3; ++i) check(r.eventRelics[i] == static_cast<int>(sorted[i]), "StableShuffle order");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && run_has_relic(r, sorted[1]), "take shown doll");
        r = start("DOLL_ROOM");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 45 && event_option_count(r) == 2,
              "take some time: 5 damage, choose one of two");
        RunContext other;
        other.init(42, 0);
        check(!event_is_allowed(other, event("DOLL_ROOM")), "Doll Room only in act 2");
    }
    {
        RunContext r = start("AMALGAMATOR");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.cardGrid.kind == 6 && r.cardGrid.filter == 1,
              "combine strikes");
        check(!card_grid_can_select(r, 5) && card_grid_can_select(r, 0), "only basic Strikes selectable");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot with filtered grid");
        select_grid(r, {0, 1});
        check(count_card(r, CardId::STRIKE_IRONCLAD) == 3 && count_card(r, CardId::ULTIMATE_STRIKE) == 1 &&
              r.deckCount == 9, "two Strikes became Ultimate Strike");
        RunContext few;
        few.init(42, 0);
        few.deckCount = 7;  // 5 Strikes, 2 Defends: exactly two Defends qualify
        event_begin(few, event("AMALGAMATOR"), false);
        check(few.step({RunActionType::EVENT_CHOICE, 1}) && !few.cardGrid.kind &&
              count_card(few, CardId::DEFEND_IRONCLAD) == 0 && count_card(few, CardId::ULTIMATE_DEFEND) == 1,
              "exactly two Defends are taken without a screen");
        RunContext one;
        one.init(42, 0);
        one.deckCount = 6;  // only one Defend
        check(!event_is_allowed(one, event("AMALGAMATOR")), "needs two of each");
    }
    {
        RunContext r = start("TRASH_HEAP");
        Rng rng(r.seed, "TRASH_HEAP");
        const RelicId relics[5] = {RelicId::DARKSTONE_PERIAPT, RelicId::DREAM_CATCHER, RelicId::HAND_DRILL,
                                   RelicId::MAW_BANK, RelicId::THE_BOOT};
        const RelicId expected = relics[rng.next_int_range(0, 5)];
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.hp == 42 && run_has_relic(r, expected), "dive in");
        r = start("TRASH_HEAP", 10);
        const int deck = r.deckCount;
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.gold == 110 && r.deckCount == deck + 1, "grab");
    }

    // --- batch 4 ----------------------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        r.potionSlots = 3;
        r.potions[0] = static_cast<int>(PotionId::FIRE_POTION);
        r.potions[2] = static_cast<int>(PotionId::BLOCK_POTION);
        r.potionCount = 2;
        check(event_is_allowed(r, event("THE_FUTURE_OF_POTIONS")), "two potions allow the event");
        event_begin(r, event("THE_FUTURE_OF_POTIONS"), false);
        check(event_option_count(r) == 2 && r.eventRng.counter == 2, "one type roll per potion");
        check(!event_can_remove_potions(r), "potions locked during the event");
        const Rarity target = potion_def(PotionId::BLOCK_POTION).rarity == Rarity::UNCOMMON ? Rarity::UNCOMMON
            : potion_def(PotionId::BLOCK_POTION).rarity == Rarity::COMMON ? Rarity::COMMON : Rarity::RARE;
        const int type = r.eventData[1];
        check(r.step({RunActionType::EVENT_CHOICE, 1}), "trade the second potion");
        check(r.potions[2] == 0 && r.potions[0] != 0 && r.potionCount == 1, "traded potion removed in place");
        int slot = -1;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) if (r.rewardCardPending[i]) slot = i;
        check(slot >= 0 && r.rewardCardCounts[slot] == 3, "three-card reward");
        for (int i = 0; i < 3; ++i) {
            const Card &c = r.rewardCards[slot][i];
            check(static_cast<int>(card_def(c.id).type) == type && card_def(c.id).rarity == target &&
                  card_def(c.id).pool == CardPool::IRONCLAD, "type and rarity match");
            check(c.upgraded || !card_def(c.id).maxUpgradeLevel, "reward cards upgraded");
        }
    }
    {
        RunContext r;
        r.init(42, 0);
        r.floor = 6;
        check(!event_is_allowed(r, event("SLIPPERY_BRIDGE")), "needs floor above 6");
        r.floor = 7;
        r.add_card_to_deck(r.make_run_card(CardId::POMMEL_STRIKE, false));
        r.add_card_to_deck(r.make_run_card(CardId::SHRUG_IT_OFF, false));
        check(event_is_allowed(r, event("SLIPPERY_BRIDGE")), "allowed with removable cards");
        r.hp = 50;
        event_begin(r, event("SLIPPERY_BRIDGE"), false);
        const int first = r.eventData[1];
        check(card_def(r.deck[first].id).rarity != Rarity::BASIC, "first pick skips basic cards");
        RunContext overcome = r;
        const CardId lost = overcome.deck[first].id;
        check(overcome.step({RunActionType::EVENT_CHOICE, 0}) && count_card(overcome, lost) == 0 &&
              overcome.deckCount == r.deckCount - 1, "overcome removes the shown card");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 47 && r.eventData[0] == 1, "hold on: 3 damage");
        check(r.deck[r.eventData[1]].id != r.deck[first].id && deck_mask_has_for_test(r, first),
              "next pick avoids the previous card type and records it");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot mid-bridge");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 43, "hold on again: 4 damage");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.screen == RunScreen::MAP &&
              !r.eventDeckMask[0] && !r.eventDeckMask[1], "overcome finishes and clears state");
    }

    // --- batch 5 ----------------------------------------------------------------
    {
        RunContext r = start("COLOSSAL_FLOWER", 0);
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.gold == 35, "extract first prize");
        r = start("COLOSSAL_FLOWER", 0);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 45 && r.eventPage == 1, "dig once: 5 damage");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 39 && r.eventPage == 2, "dig twice: 6 damage");
        RunContext extract = r;
        check(extract.step({RunActionType::EVENT_CHOICE, 0}) && extract.gold == 135, "extract instead: 135");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.hp == 32 && run_has_relic(r, RelicId::POLLINOUS_CORE),
              "pollinous core: 7 damage and relic");
        RunContext low;
        low.init(42, 0);
        low.hp = 18;
        check(!event_is_allowed(low, event("COLOSSAL_FLOWER")), "needs 19 HP");
    }
    {
        RunContext r = start("JUNGLE_MAZE_ADVENTURE", 0);
        Rng rng(r.seed, "JUNGLE_MAZE_ADVENTURE");
        const double solo = 150.0 + rng.next_float(-15.0f, 15.0f);
        const double join = 50.0 + rng.next_float(-15.0f, 15.0f);
        check(std::abs(r.eventData[0] - static_cast<int>(solo)) <= 1 &&
              std::abs(r.eventData[2] - static_cast<int>(join)) <= 1, "solo/join gold near the float sums");
        RunContext joined = r;
        check(joined.step({RunActionType::EVENT_CHOICE, 1}) && joined.gold == r.eventData[2] && joined.hp == 50,
              "safety in numbers");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.gold == r.eventData[0] && r.hp == 32,
              "solo quest: 18 damage and gold");
        // (decimal)float rounds to 7 significant digits before truncation.
        int plain = 0, bowler = 0;
        float almost = std::nextafter(3.0f, 0.0f);  // 2.99999976 -> 3.000000m
        decimal_gold_for_test(150, almost, plain, bowler);
        check(plain == 153 && bowler == 191, "decimal rounding before (int)");
    }
    {
        RunContext r;
        r.init(42, 0);
        r.gold = 0;
        r.add_relic(RelicId::BOWLER_HAT);
        r.add_relic(RelicId::DRAGON_FRUIT);
        const int hp = r.maxHp;
        run_gain_gold(r, 35);
        check(r.gold == 43 && r.maxHp == hp + 1, "Bowler Hat x1.25 (43), Dragon Fruit once");
    }

    // --- batch 6: enchantment events ------------------------------------------
    {
        // Sharp (+2) and Corrupted (x1.5) act on the card base before Vigor/Strength.
        Card strike = make_card(CardId::STRIKE_IRONCLAD, false, 501);
        check(card_apply_enchantment(strike, EnchantmentId::SHARP, 2), "Sharp on Strike");
        Card corrupted = make_card(CardId::STRIKE_IRONCLAD, false, 502);
        check(card_apply_enchantment(corrupted, EnchantmentId::CORRUPTED, 1), "Corrupted on Strike");
        Card defend = make_card(CardId::DEFEND_IRONCLAD, false, 503);
        check(!card_can_enchant(defend, EnchantmentId::SHARP) && !card_can_enchant(defend, EnchantmentId::CORRUPTED),
              "Sharp/Corrupted need attacks");
        Card deck[2] = {strike, corrupted};
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 9, deck, 2, 0, 80, 80);
        b.monsters[0].hp = b.monsters[0].maxHp = 10000;
        b.monsters[0].block = 0;
        b.monsters[0].vulnerable = 0;
        b.player.strength = 2;
        b.player.energy = 10;
        check(b.enchant_card_damage(strike, 6) == 8 && b.enchant_card_damage(corrupted, 6) == 9,
              "enchant transform");
        int si = -1, ci = -1;
        for (int i = 0; i < b.handCount; ++i) { if (b.hand[i].uid == 501) si = i; if (b.hand[i].uid == 502) ci = i; }
        check(si >= 0 && ci >= 0, "both drawn");
        int hp = b.monsters[0].hp;
        check(b.play_card(si, 0) && hp - b.monsters[0].hp == 10, "Sharp Strike: 6+2+2 strength");
        for (int i = 0; i < b.handCount; ++i) if (b.hand[i].uid == 502) ci = i;
        hp = b.monsters[0].hp;
        const int php = b.player.hp;
        check(b.play_card(ci, 0) && hp - b.monsters[0].hp == 11, "Corrupted Strike: 6*1.5+2 strength");
        check(b.player.hp == php - 2, "Corrupted deals 2 to the player on play");
    }
    {
        // Souls Power removes Exhaust; Perfect Fit returns on top after a shuffle.
        Card offering = make_card(CardId::OFFERING, false, 601);
        check(card_has(offering, CF_EXHAUST) && card_can_enchant(offering, EnchantmentId::SOULS_POWER),
              "Offering can take Souls Power");
        check(!card_can_enchant(make_card(CardId::STRIKE_IRONCLAD, false, 602), EnchantmentId::SOULS_POWER),
              "Souls Power needs Exhaust");
        card_apply_enchantment(offering, EnchantmentId::SOULS_POWER, 1);
        check(!card_has(offering, CF_EXHAUST), "Souls Power removes Exhaust");

        Card cards[8];
        for (int i = 0; i < 8; ++i) cards[i] = make_card(CardId::STRIKE_IRONCLAD, false, 700 + i);
        card_apply_enchantment(cards[3], EnchantmentId::PERFECT_FIT, 1);
        BattleContext b;
        b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 11, cards, 8, 0, 80, 80);
        // Move everything to the discard pile, then shuffle (non-initial).
        for (int i = 0; i < b.handCount; ++i) b.discard[b.discardCount++] = b.hand[i];
        for (int i = 0; i < b.drawCount; ++i) b.discard[b.discardCount++] = b.draw[i];
        b.handCount = b.drawCount = 0;
        b.shuffle_discard_into_draw();
        check(b.drawCount == 8 && b.draw[b.drawCount - 1].uid == 703, "Perfect Fit on top after shuffle");
    }
    {
        RunContext r = start("FIELD_OF_MAN_SIZED_HOLES");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.cardGrid.maxSelect == 2, "resist removes two");
        RunContext mid;
        check(RunContext::restore(r.serialize(), mid), "snapshot with Normality pending");
        select_grid(r, {0, 1});
        check(r.deckCount == 9 && count_card(r, CardId::NORMALITY) == 1, "Normality added after removal");
        r = start("FIELD_OF_MAN_SIZED_HOLES");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.eventCardSelection == 10, "enter your hole");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 9}) && r.deck[9].enchantment == EnchantmentId::PERFECT_FIT,
              "Perfect Fit on Bash");
    }
    {
        RunContext r = start("SYMBIOTE");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventCardSelection == 11, "approach");
        check(!event_card_selectable(r, 5) && event_card_selectable(r, 0), "Corrupted only on attacks");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 0}) && r.deck[0].enchantment == EnchantmentId::CORRUPTED,
              "Strike corrupted");
        r = start("SYMBIOTE");
        const Rng eventBefore = r.eventRng;
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.step({RunActionType::EVENT_SELECT_CARD, 9}) &&
              count_card(r, CardId::BASH) == 0 && r.eventRng.counter > eventBefore.counter,
              "kill with fire transforms with the event Rng");
        RunContext early;
        early.init(42, 0);
        check(!event_is_allowed(early, event("SYMBIOTE")), "Symbiote not in act 1");
    }
    {
        RunContext r;
        r.init(42, 0);
        check(!event_is_allowed(r, event("GRAVE_OF_THE_FORGOTTEN")), "starter deck has no Exhaust card");
        r.add_card_to_deck(r.make_run_card(CardId::OFFERING, false));
        r.gold = 300;
        r.hp = 50;
        event_begin(r, event("GRAVE_OF_THE_FORGOTTEN"), false);
        const int deck = r.deckCount;
        check(r.step({RunActionType::EVENT_CHOICE, 0}), "confront");
        check(count_card(r, CardId::DECAY) == 1 && r.deckCount == deck + 1, "Decay added first");
        int offering = -1;
        for (int i = 0; i < r.deckCount; ++i) if (r.deck[i].id == CardId::OFFERING) offering = i;
        check(r.deck[offering].enchantment == EnchantmentId::SOULS_POWER && r.screen == RunScreen::MAP,
              "only candidate auto-selected for Souls Power");
        RunContext accept;
        accept.init(42, 0);
        accept.add_card_to_deck(accept.make_run_card(CardId::OFFERING, false));
        event_begin(accept, event("GRAVE_OF_THE_FORGOTTEN"), false);
        check(accept.step({RunActionType::EVENT_CHOICE, 1}) && run_has_relic(accept, RelicId::FORGOTTEN_SOUL),
              "accept: Forgotten Soul");
    }
    {
        RunContext r = start("SELF_HELP_BOOK");
        check(event_option_count(r) == 3 && event_option_available(r, 0) && event_option_available(r, 1) &&
              !event_option_available(r, 2), "no power: entire-book option locked");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventCardSelection == 13, "read the back");
        check(!event_card_selectable(r, 5), "Sharp: attacks only");
        check(r.step({RunActionType::EVENT_SELECT_CARD, 9}) && r.deck[9].enchantment == EnchantmentId::SHARP &&
              r.deck[9].enchantmentAmount == 2, "Sharp 2 on Bash");
        r = start("SELF_HELP_BOOK");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.step({RunActionType::EVENT_SELECT_CARD, 5}) &&
              r.deck[5].enchantment == EnchantmentId::NIMBLE && r.deck[5].enchantmentAmount == 2, "Nimble 2 on Defend");
        RunContext curses;
        curses.init(42, 0);
        curses.deckCount = 0;
        curses.add_card_to_deck(curses.make_run_card(CardId::DECAY, false));
        event_begin(curses, event("SELF_HELP_BOOK"), false);
        check(event_option_count(curses) == 1 && curses.step({RunActionType::EVENT_CHOICE, 0}) &&
              curses.screen == RunScreen::MAP, "no options: skip book");
    }

    // --- batch 7: relic trading -------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        check(!run_relic_tradable(r, 0), "starter relic not tradable");
        // Placed directly: obtaining Astrolabe would open its transform grid.
        const RelicId placed[4] = {RelicId::ANCHOR, RelicId::ASTROLABE /* upon-pickup effect */,
                                   RelicId::LIZARD_TAIL, RelicId::MAW_BANK /* event relic */};
        for (RelicId id : placed) { r.relicAux[r.relicCount] = 0; r.relics[r.relicCount++] = static_cast<int>(id); }
        check(run_relic_tradable(r, 1) && !run_relic_tradable(r, 2), "common tradable, pickup relic not");
        check(run_relic_tradable(r, 3), "unused Lizard Tail tradable");
        r.relicAux[3] = 1;
        check(!run_relic_tradable(r, 3), "used Lizard Tail not tradable");
        check(!run_relic_tradable(r, 4), "event relic not tradable");
        r.relicAux[1] = 7;
        r.relicWax[2] = true;
        run_remove_relic_at(r, 1);
        check(r.relicCount == 4 && r.relics[1] == static_cast<int>(RelicId::ASTROLABE) && r.relicWax[1] &&
              r.relicAux[2] == 1 && r.relics[4] == 0 && r.relicAux[4] == 0, "removal shifts per-slot state");
    }
    {
        RunContext r;
        r.init(42, 0);
        r.act = 1;
        const RelicId commons[5] = {RelicId::ANCHOR, RelicId::BAG_OF_PREPARATION, RelicId::BLOOD_VIAL,
                                    RelicId::BRONZE_SCALES, RelicId::AMETHYST_AUBERGINE};
        for (RelicId id : commons) r.add_relic(id);
        check(event_is_allowed(r, event("RELIC_TRADER")), "five tradable relics allow the trader");
        RunContext bag = r;
        event_begin(r, event("RELIC_TRADER"), false);
        // StableShuffle: ModelId (key) order, then UnstableShuffle with the event Rng.
        int owned[5];
        for (int i = 0; i < 5; ++i) owned[i] = static_cast<int>(commons[i]);
        std::sort(owned, owned + 5, [](int a, int b) {
            return std::strcmp(relic_def(static_cast<RelicId>(a)).key, relic_def(static_cast<RelicId>(b)).key) < 0;
        });
        Rng rng(r.seed, "RELIC_TRADER");
        rng.shuffle(owned, 5);
        for (int i = 0; i < 3; ++i) check(r.eventData[i] == owned[i], "owned relics: StableShuffle, first three");
        check(event_option_count(r) == 3 && r.playerRng[PRNG_REWARDS].counter == bag.playerRng[PRNG_REWARDS].counter + 3,
              "three new relics pulled at the start (one rarity roll each)");
        const int give = r.eventData[1], get = r.eventRelics[1], count = r.relicCount;
        check(r.step({RunActionType::EVENT_CHOICE, 1}), "trade middle");
        check(!run_has_relic(r, static_cast<RelicId>(give)) && run_has_relic(r, static_cast<RelicId>(get)) &&
              r.relicCount == count, "middle relic traded");
        RunContext early = bag;
        early.act = 0;
        check(!event_is_allowed(early, event("RELIC_TRADER")), "not in act 1");
    }
    {
        RunContext r;
        r.init(42, 0);
        r.act = 1;
        r.gold = 150;
        r.add_relic(RelicId::ANCHOR);
        r.potionSlots = 3;
        r.potions[1] = static_cast<int>(PotionId::FIRE_POTION);
        r.potionCount = 1;
        check(event_is_allowed(r, event("RANWID_THE_ELDER")), "Ranwid allowed");
        RunContext base = r;
        event_begin(r, event("RANWID_THE_ELDER"), false);
        check(!event_can_remove_potions(r), "potions locked during Ranwid");
        check(r.eventData[0] == 0 && r.eventData[1] == static_cast<int>(RelicId::ANCHOR), "picked potion and relic");
        RunContext a = r, g = r;
        const int relics = r.relicCount;
        check(a.step({RunActionType::EVENT_CHOICE, 0}) && a.potionCount == 0 && a.relicCount == relics + 1,
              "give potion for a relic");
        check(g.step({RunActionType::EVENT_CHOICE, 1}) && g.gold == 50 && g.relicCount == relics + 1,
              "give 100 gold for a relic");
        check(r.step({RunActionType::EVENT_CHOICE, 2}) && !run_has_relic(r, RelicId::ANCHOR) &&
              r.relicCount == relics + 1, "give a relic for two");
        base.potionCount = 0;
        base.potions[1] = 0;
        check(!event_is_allowed(base, event("RANWID_THE_ELDER")), "needs a potion");
    }

    // --- batch 8: Endless Conveyor -----------------------------------------------
    {
        enum { CAVIAR, SPICY, JELLY, EEL, CONDIMENT, CLAM, FYSH, SALAD, NONE };
        RunContext r;
        r.init(42, 0);
        r.gold = 119;
        check(!event_is_allowed(r, event("ENDLESS_CONVEYOR")), "conveyor needs 120 gold");
        r = start("ENDLESS_CONVEYOR", 1000);
        check(r.eventData[0] == 1 && r.eventData[1] != FYSH && r.eventData[1] != SALAD &&
              r.eventRng.counter == 1, "first dish rolled once, never Golden Fysh");
        RunContext observe = r;
        check(observe.step({RunActionType::EVENT_CHOICE, 1}) && observe.screen == RunScreen::MAP, "observe chef");
        for (int grab = 1; grab <= 4; ++grab) {
            int dish = r.eventData[1];
            if (dish == CONDIMENT || dish == JELLY) { r.eventData[1] = dish = CAVIAR; r.eventData[2] = CAVIAR; }
            const int gold = r.gold;
            check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventPage == 1, "grab");
            check(r.gold == gold + (dish == FYSH ? 75 : -40), "grab cost / Golden Fysh gold");
            check(r.eventData[0] == grab + 1, "grab count");
            if (grab < 4) check(r.eventData[1] != dish, "the dish just eaten is excluded from the next roll");
        }
        check(r.eventData[1] == SALAD, "every fifth dish is Seapunk Salad");
        const Rng before = r.eventRng;
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && count_card(r, CardId::FEEDING_FRENZY_CARD) == 1,
              "salad adds Feeding Frenzy");
        check(r.eventRng.counter == before.counter + 1, "the salad itself used no RNG; next roll used one");

        // Suspicious Condiment: the next dish is rolled only after the reward closes.
        RunContext c = r;
        c.eventData[1] = c.eventData[2] = CONDIMENT;
        const int grabs = c.eventData[0];
        check(c.step({RunActionType::EVENT_CHOICE, 0}) && c.screen == RunScreen::REWARDS && c.eventData[0] == grabs,
              "condiment offers a potion before rolling");
        check(c.step({RunActionType::LEAVE_REWARDS, 0}) && c.screen == RunScreen::EVENT && c.eventData[0] == grabs + 1 &&
              c.eventPage == 1, "back to the belt after the reward");

        // Jelly Liver: transform one chosen card, then roll.
        RunContext j = r;
        j.eventData[1] = j.eventData[2] = JELLY;
        check(j.step({RunActionType::EVENT_CHOICE, 0}) && j.eventCardSelection == 4, "jelly liver selects");
        check(j.step({RunActionType::EVENT_SELECT_CARD, 9}) && count_card(j, CardId::BASH) == 0 &&
              j.eventData[0] == grabs + 1 && j.screen == RunScreen::EVENT && !j.eventCardSelection, "transformed, rolled");
        RunContext saved;
        check(RunContext::restore(j.serialize(), saved), "snapshot on the belt");
        check(j.step({RunActionType::EVENT_CHOICE, 1}) && j.screen == RunScreen::MAP, "leave");
        RunContext poor = r;
        poor.gold = 39;
        check(!event_option_available(poor, 0), "grab locked below 40 gold");
    }

    // --- batch 9: Trial --------------------------------------------------------------
    {
        RunContext r = start("TRIAL", 0);
        Rng rng(r.seed, "TRIAL");
        const int c = rng.next_int_exclusive(3);
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventPage == 2 && r.eventData[0] == c, "accept picks a case");
        RunContext rejected = start("TRIAL", 0);
        check(rejected.step({RunActionType::EVENT_CHOICE, 1}) && rejected.eventPage == 1, "reject page");
        RunContext again = rejected;
        check(again.step({RunActionType::EVENT_CHOICE, 0}) && again.eventPage == 2 && again.eventData[0] == c,
              "accept after rejecting uses the same first roll");
        check(rejected.step({RunActionType::EVENT_CHOICE, 1}) && rejected.screen == RunScreen::RUN_OVER,
              "double down abandons the run");
        // Each verdict, forcing the case.
        auto verdict = [&](int kase, int option) {
            RunContext v = start("TRIAL", 0);
            v.eventData[0] = kase;
            set_page_for_test(v, 2, 2);
            check(v.step({RunActionType::EVENT_CHOICE, option}), "verdict");
            return v;
        };
        RunContext v = verdict(0, 0);
        check(count_card(v, CardId::REGRET) == 1 && v.relicCount == 3, "merchant guilty: Regret + 2 relics");
        v = verdict(0, 1);
        check(count_card(v, CardId::SHAME) == 1 && v.cardGrid.kind == 9 && v.cardGrid.maxSelect == 2,
              "merchant innocent: Shame, upgrade 2");
        v = verdict(1, 0);
        check(v.hp == 60, "noble guilty: heal 10");
        v = verdict(1, 1);
        check(count_card(v, CardId::REGRET) == 1 && v.gold == 300, "noble innocent: Regret + 300 gold");
        v = verdict(2, 0);
        int rewards = 0;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) rewards += v.rewardCardPending[i];
        check(count_card(v, CardId::DOUBT) == 1 && rewards == 2 && v.screen == RunScreen::REWARDS,
              "nondescript guilty: Doubt + two card rewards");
        v = verdict(2, 1);
        check(count_card(v, CardId::DOUBT) == 1 && v.cardGrid.kind == 7 && v.cardGrid.eventRng &&
              v.cardGrid.maxSelect == 2, "nondescript innocent: Doubt, transform 2 (Doubt itself eligible)");
    }

    // --- batch 10: Tinker Time / Mad Science ---------------------------------------
    {
        RunContext r = start("TINKER_TIME", 0);
        check(event_option_count(r) == 1 && r.step({RunActionType::EVENT_CHOICE, 0}) && r.eventPage == 1,
              "choose card type page");
        Rng rng(r.seed, "TINKER_TIME");
        int types[3] = {1, 2, 3};
        rng.shuffle(types, 3);
        check(r.eventData[0] == types[0] && r.eventData[1] == types[1], "two random types");
        const int type = r.eventData[1];
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.eventPage == 2 && r.eventData[0] == type, "type chosen");
        const int riders[3][3] = {{1, 2, 3}, {4, 5, 6}, {7, 8, 9}};
        int offered[3] = {riders[type - 1][0], riders[type - 1][1], riders[type - 1][2]};
        rng.shuffle(offered, 3);
        check(r.eventData[2] == offered[0] && r.eventData[3] == offered[1], "two random riders of that type");
        check(r.step({RunActionType::EVENT_CHOICE, 0}), "rider chosen");
        const Card &made = r.deck[r.deckCount - 1];
        check(made.id == CardId::MAD_SCIENCE && made.tinkerType == type && made.tinkerRider == offered[0],
              "Mad Science configured");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot with configured Mad Science");
    }
    {
        auto mad = [](int type, int rider, std::uint16_t uid) {
            Card c = make_card(CardId::MAD_SCIENCE, false, uid);
            c.tinkerType = static_cast<std::uint8_t>(type);
            c.tinkerRider = static_cast<std::uint8_t>(rider);
            return c;
        };
        check(card_type(mad(2, 4, 1)) == CardType::SKILL && card_target(mad(2, 4, 1)) == TargetType::SELF &&
              card_target(mad(1, 1, 1)) == TargetType::ENEMY, "instance type and target");
        check(card_can_enchant(mad(2, 4, 1), EnchantmentId::NIMBLE) && !card_can_enchant(mad(1, 1, 1), EnchantmentId::NIMBLE),
              "only the Skill variant gains block (Nimble)");
        auto battle_with = [](Card c) {
            BattleContext b;
            b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 21, &c, 1, 0, 80, 80);
            b.monsters[0].hp = b.monsters[0].maxHp = 10000;
            b.monsters[0].block = 0;
            b.monsters[0].vulnerable = 0;
            b.player.strength = 0;
            b.player.energy = 10;
            return b;
        };
        BattleContext b = battle_with(mad(1, 2, 31));
        int hp = b.monsters[0].hp;
        check(b.play_card(0, 0) && hp - b.monsters[0].hp == 36, "Violence: 12 x 3");
        b = battle_with(mad(1, 1, 32));
        check(b.play_card(0, 0) && b.monsters[0].vulnerable == 2 && b.monsters[0].weak >= 2, "Sapping: Weak/Vulnerable 2");
        b = battle_with(mad(2, 4, 33));
        const int energy = b.player.energy;
        check(b.play_card(0, 0) && b.player.block == 8 && b.player.energy == energy - 1 + 2, "Skill: 8 block, Energized +2");
        b = battle_with(mad(3, 8, 34));
        check(b.play_card(0, 0) && b.player_power(PowerId::CURIOUS) == 1 && b.drawCount + b.discardCount == 0,
              "Curious power applied; the Power card leaves play");
        Card inflame = make_card(CardId::INFLAME, false, 35);
        b.hand[b.handCount++] = inflame;
        const int before = b.player.energy;
        check(b.play_card(b.handCount - 1, 0) && b.player.energy == before, "Curious: Inflame costs 0");

        RunContext r;
        r.init(42, 0);
        r.deckCount = 1;
        Card improvement = r.make_run_card(CardId::MAD_SCIENCE, true);  // upgraded: not a candidate
        improvement.tinkerType = 3;
        improvement.tinkerRider = 9;
        r.deck[0] = improvement;
        r.add_card_to_deck(r.make_run_card(CardId::STRIKE_IRONCLAD, false));
        r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        check(r.battle.player_power(PowerId::IMPROVEMENT) == 0, "no Improvement before playing");
        r.battle.add_player_power(PowerId::IMPROVEMENT, 1);
        for (int i = 0; i < r.battle.monsterCount; ++i) { r.battle.monsters[i].hp = 0; r.battle.monsters[i].alive = false; }
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check(r.deck[1].upgraded, "Improvement upgrades the only upgradable deck card at combat end");
    }

    // --- batch 11: Crystal Sphere -----------------------------------------------------
    {
        const int W[9] = {4, 1, 2, 2, 2, 2, 2, 1, 2}, H[9] = {4, 3, 2, 2, 2, 2, 2, 1, 1};
        auto hidden = [](const CrystalSphereState &g, int x, int y) {
            const int b = x * 11 + y; return ((g.hidden[b / 64] >> (b % 64)) & 1u) != 0; };
        RunContext r;
        r.init(42, 0);
        r.gold = 99;
        r.act = 1;
        check(!event_is_allowed(r, event("CRYSTAL_SPHERE")), "needs 100 gold");
        r.gold = 300;
        r.hp = 50;
        event_begin(r, event("CRYSTAL_SPHERE"), false);
        const int cost = r.eventData[0];
        check(cost >= 51 && cost <= 99, "uncover cost 50 + NextInt(1, 50)");
        RunContext plan = r;
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.gold == 300 - cost && r.crystalSphere.active &&
              r.crystalSphere.divinations == 3 && event_option_count(r) == 0, "uncover the future: 3 divinations");
        const CrystalSphereState &g = r.crystalSphere;
        int hiddenCount = 0;
        for (int x = 0; x < 11; ++x) for (int y = 0; y < 11; ++y) hiddenCount += hidden(g, x, y);
        check(hiddenCount == 97 && !hidden(g, 0, 0) && !hidden(g, 2, 0) && !hidden(g, 1, 1) && hidden(g, 2, 1) &&
              !hidden(g, 10, 8) && hidden(g, 3, 0), "four Manhattan-2 corners start cleared");
        int placed = 0, cells = 0;
        for (int i = 0; i < g.itemCount; ++i) {
            if (!g.itemPlaced[i]) continue;
            ++placed;
            for (int dx = 0; dx < W[g.itemType[i]]; ++dx)
                for (int dy = 0; dy < H[g.itemType[i]]; ++dy) {
                    const int x = g.itemX[i] + dx, y = g.itemY[i] + dy;
                    check(x < 11 && y < 11 && hidden(g, x, y) && g.cellItem[x * 11 + y] == i + 1, "item covers hidden cells");
                    ++cells;
                }
        }
        check(placed == 15 && cells == 51, "fifteen items on 51 cells");
        int actions = 0;
        for (const RunAction &a : r.legal_actions())
            actions += a.type == RunActionType::CRYSTAL_SPHERE_SMALL || a.type == RunActionType::CRYSTAL_SPHERE_BIG;
        check(actions == 2 * 97, "two tools for every hidden cell");
        check(!r.step({RunActionType::CRYSTAL_SPHERE_SMALL, 0}), "cleared cells cannot be clicked");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot during the minigame");
        check(static_cast<int>(public_observation(r).size()) == PUBLIC_OBS_DIM, "observation size");

        // Reveal a small gold (1x1) and the curse (2x2 via the big tool), then a third click.
        int goldItem = -1, curseItem = -1;
        for (int i = 0; i < g.itemCount; ++i) {
            if (g.itemPlaced[i] && g.itemType[i] == 7 && goldItem < 0) goldItem = i;
            if (g.itemPlaced[i] && g.itemType[i] == 6) curseItem = i;
        }
        check(r.step({RunActionType::CRYSTAL_SPHERE_SMALL, g.itemX[goldItem] * 11 + g.itemY[goldItem]}) &&
              r.crystalSphere.revealedCount == 1 && r.crystalSphere.divinations == 2, "small tool reveals a 1x1 gold");
        const int decks = r.deckCount;
        const int cx = g.itemX[curseItem], cy = g.itemY[curseItem];
        int target = -1;  // a hidden cell whose 3x3 covers the whole 2x2 curse
        for (int x = cx; x <= cx + 1 && target < 0; ++x)
            for (int y = cy; y <= cy + 1 && target < 0; ++y)
                if (hidden(g, x, y)) target = x * 11 + y;
        check(r.step({RunActionType::CRYSTAL_SPHERE_BIG, target}), "big tool");
        bool curseShown = false;
        for (int k = 0; k < r.crystalSphere.revealedCount; ++k) curseShown |= r.crystalSphere.revealed[k] == curseItem;
        check(curseShown && r.deckCount >= decks + 1 && count_card(r, CardId::DOUBT) == 1, "curse reveal adds Doubt at once");
        int third = -1;
        for (int c = 0; c < 121 && third < 0; ++c) if (hidden(g, c / 11, c % 11)) third = c;
        const int goldBefore = r.gold;
        check(r.step({RunActionType::CRYSTAL_SPHERE_SMALL, third}) && !r.crystalSphere.active &&
              r.screen == RunScreen::REWARDS, "last divination ends the minigame and offers rewards");
        check(r.extraGoldRewards[0] == 10 && r.step({RunActionType::TAKE_GOLD_REWARD, 2}) &&
              r.gold == goldBefore + 10, "revealed gold is a separate reward");

        check(plan.step({RunActionType::EVENT_CHOICE, 1}) && count_card(plan, CardId::DEBT) == 1 &&
              plan.crystalSphere.divinations == 6 && plan.gold == 300, "payment plan: Debt, 6 divinations");
    }

    // --- batch 12: event combats -------------------------------------------------------
    {
        auto win = [](RunContext &r, bool ranOut = false) {
            for (int i = 0; i < r.battle.monsterCount; ++i) { r.battle.monsters[i].hp = 0; r.battle.monsters[i].alive = false; }
            r.battle.battlewornRanOutOfTime = ranOut;
            r.battle.outcome = Outcome::PLAYER_VICTORY;
            r.finish_combat();
        };
        auto pending_cards = [](const RunContext &r) {
            int n = 0; for (int i = 0; i < MAX_CARD_REWARDS; ++i) n += r.rewardCardPending[i]; return n; };

        // Battleworn Dummy: 3-turn limit; V1 victory gives a potion, timing out nothing.
        RunContext r = start("BATTLEWORN_DUMMY");
        check(event_option_count(r) == 3 && r.step({RunActionType::EVENT_CHOICE, 0}) && r.inBattle &&
              r.battle.monsters[0].power[static_cast<int>(PowerId::BATTLEWORN_DUMMY_TIME_LIMIT)] == 3,
              "setting 1 fights the 75 HP dummy with a 3-turn limit");
        win(r);
        int potions = 0;
        for (int i = 0; i < r.pendingPotionCount; ++i) potions += r.pendingPotions[i] != 0;
        // finish_combat() is called directly here; the step wrapper would open
        // the deferred custom rewards on the next action.
        check(r.deferredCustomRewards && potions == 1 && r.pendingGoldReward == 0 && !pending_cards(r),
              "V1 victory: only a potion, no room rewards");
        r = start("BATTLEWORN_DUMMY");
        check(r.step({RunActionType::EVENT_CHOICE, 2}), "setting 3");
        win(r, true);
        check(r.screen == RunScreen::MAP && r.pendingRelicCount == 0 && !r.deferredCustomRewards, "time out: no reward");
        r = start("BATTLEWORN_DUMMY");
        check(r.step({RunActionType::EVENT_CHOICE, 1}), "setting 2");
        win(r);
        int upgraded = 0;
        for (int i = 0; i < r.deckCount; ++i) upgraded += r.deck[i].upgraded;
        check(upgraded == 2 && r.screen == RunScreen::MAP, "V2 victory upgrades two cards");
        {
            BattleContext b;
            Card d[1] = {make_card(CardId::DEFEND_IRONCLAD, false, 1)};
            b.init(Encounter::SETUP_BATTLEWORN_DUMMY_V3, 3, d, 1, 0, 80, 80);
            for (int t = 0; t < 3 && b.outcome == Outcome::UNDECIDED; ++t) b.step({ActionType::END_TURN});
            check(b.outcome == Outcome::PLAYER_VICTORY && b.battlewornRanOutOfTime, "the dummy escapes after 3 enemy turns");
        }

        // The Lantern Key: return for 100 gold, or fight for room rewards + the key.
        r = start("THE_LANTERN_KEY", 0);
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.gold == 100, "return the key");
        r = start("THE_LANTERN_KEY", 0);
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && event_option_count(r) == 1 &&
              r.step({RunActionType::EVENT_CHOICE, 0}) && r.inBattle, "keep the key and fight");
        win(r);
        bool keyOffered = false;
        for (int i = 0; i < MAX_CARD_REWARDS; ++i)
            keyOffered |= r.rewardCardPending[i] && r.rewardCardCounts[i] == 1 && r.rewardCards[i][0].id == CardId::LANTERN_KEY;
        check(r.pendingGoldReward >= 10 && pending_cards(r) == 2 && keyOffered, "room rewards plus the Lantern Key");

        // Lantern Key in act 3: "?" rooms are events, and the event is War Historian Repy.
        RunContext k;
        k.init(42, 0);
        k.add_card_to_deck(k.make_run_card(CardId::LANTERN_KEY, false));
        k.act = 2;
        check(run_lantern_key_active(k) && event_modify_next(k, event("WELLSPRING")) == event("WAR_HISTORIAN_REPY"),
              "next event becomes War Historian Repy");
        k.act = 1;
        check(!run_lantern_key_active(k), "only in act 3");
        k.act = 2;
        k.gold = 0;
        event_begin(k, event("WAR_HISTORIAN_REPY"), false);
        check(k.step({RunActionType::EVENT_CHOICE, 0}) && run_has_relic(k, RelicId::HISTORY_COURSE) &&
              count_card(k, CardId::LANTERN_KEY) == 0 && k.screen == RunScreen::MAP, "unlock the cage with one key");
        RunContext two;
        two.init(42, 0);
        two.add_card_to_deck(two.make_run_card(CardId::LANTERN_KEY, false));
        two.add_card_to_deck(two.make_run_card(CardId::LANTERN_KEY, false));
        event_begin(two, event("WAR_HISTORIAN_REPY"), false);
        check(two.step({RunActionType::EVENT_CHOICE, 1}) && two.eventPage == 1 && count_card(two, CardId::LANTERN_KEY) == 1,
              "chest first; a second key allows the cage too");
        int chestPotions = 0;
        for (int i = 0; i < two.pendingPotionCount; ++i) chestPotions += two.pendingPotions[i] != 0;
        check(chestPotions == 2 && two.pendingRelicCount == 2, "chest: two potions, two relics");

        // Punch Off: Nab (Injury + relic) or fight (room rewards + relic + potion).
        r = start("PUNCH_OFF");
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && count_card(r, CardId::INJURY) == 1 && r.pendingRelicCount == 1,
              "nab");
        r = start("PUNCH_OFF");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.step({RunActionType::EVENT_CHOICE, 0}) &&
              r.inBattle && r.battle.monsterCount == 2, "fight two Punch Constructs");
        win(r);
        int fightPotions = 0;
        for (int i = 0; i < r.pendingPotionCount; ++i) fightPotions += r.pendingPotions[i] != 0;
        check(r.pendingRelicCount == 1 && fightPotions >= 1 && pending_cards(r) == 1 && r.pendingGoldReward >= 10,
              "room rewards plus a relic and a potion");
        check(r.step({RunActionType::LEAVE_REWARDS, 0}) && r.screen == RunScreen::MAP, "the room ends after rewards");
    }

    // --- batch 13: Fake Merchant --------------------------------------------------------
    {
        RunContext r;
        r.init(42, 0);
        r.act = 1;
        r.gold = 99;
        check(!event_is_allowed(r, event("FAKE_MERCHANT")), "needs 100 gold or a Foul Potion");
        r.potionSlots = 3;
        r.potions[0] = static_cast<int>(PotionId::FOUL_POTION);
        r.potionCount = 1;
        check(event_is_allowed(r, event("FAKE_MERCHANT")), "a Foul Potion is enough");
        auto foul_usable = [](const RunContext &c) {
            for (const RunAction &a : c.legal_actions()) if (a.type == RunActionType::USE_POTION && a.index == 0) return true;
            return false;
        };
        check(!foul_usable(r), "Foul Potion unusable on the map");
        r.gold = 200;
        r.hp = 50;
        const Rng shops = r.playerRng[PRNG_SHOPS];
        event_begin(r, event("FAKE_MERCHANT"), false);
        check(event_option_count(r) == 7 && r.playerRng[PRNG_SHOPS].counter == shops.counter + 6, "six priced relics + leave");
        for (int i = 0; i < 6; ++i)
            check(r.eventRelics[i] && r.eventData[i] >= 42 && r.eventData[i] <= 58, "fake relic for ~50 gold");
        const int price = r.eventData[2];
        const RelicId bought = static_cast<RelicId>(r.eventRelics[2]);
        check(r.step({RunActionType::EVENT_CHOICE, 2}) && r.gold == 200 - price && run_has_relic(r, bought) &&
              !event_option_available(r, 2) && r.screen == RunScreen::EVENT, "buy one; the slot empties");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot at the fake merchant");
        RunContext leave = r;
        check(leave.step({RunActionType::EVENT_CHOICE, 6}) && leave.screen == RunScreen::MAP, "leave");
        check(foul_usable(r) && r.step({RunActionType::USE_POTION, 0}) && r.inBattle && r.potionCount == 0 &&
              r.battle.monsters[0].id == MonsterId::FAKE_MERCHANT_MONSTER, "throwing the Foul Potion starts the fight");
        for (int i = 0; i < r.battle.monsterCount; ++i) { r.battle.monsters[i].hp = 0; r.battle.monsters[i].alive = false; }
        r.battle.outcome = Outcome::PLAYER_VICTORY;
        r.finish_combat();
        check(r.pendingGoldReward == 300 && r.pendingRelicCount == 6 &&
              r.pendingRelics[0] == static_cast<int>(RelicId::FAKE_MERCHANTS_RUG), "300 gold, the Rug and the five unsold relics");
        RunContext shop;
        shop.init(42, 0);
        shop.potionSlots = 3;
        shop.potions[0] = static_cast<int>(PotionId::FOUL_POTION);
        shop.potionCount = 1;
        shop.screen = RunScreen::SHOP;
        const int gold = shop.gold;
        check(foul_usable(shop) && shop.step({RunActionType::USE_POTION, 0}) && shop.gold == gold + 100,
              "in a merchant room the Foul Potion gives 100 gold");
    }

    // ---- batch 14: The Legends Were True / Spoils Map ---------------------
    {
        auto coord_of = [](const ActMap &m, int idx, int &row, int &col) {
            for (row = 0; row < MAP_MAX_ROWS; ++row)
                for (col = 0; col < MAP_WIDTH; ++col) if (m.index[row][col] == idx) return;
            row = col = -1;
        };
        auto same_map = [](const ActMap &x, const ActMap &y) {
            if (x.pointCount != y.pointCount || x.mapLength != y.mapLength) return false;
            for (int row = 0; row < MAP_MAX_ROWS; ++row)
                for (int col = 0; col < MAP_WIDTH; ++col) if (x.index[row][col] != y.index[row][col]) return false;
            for (int i = 0; i < x.pointCount; ++i) {
                const MapNode &p = x.nodes[i], &q = y.nodes[i];
                if (p.type != q.type || p.childCount != q.childCount || p.parentCount != q.parentCount) return false;
                for (int k = 0; k < p.childCount; ++k) if (p.children[k] != q.children[k]) return false;
            }
            return true;
        };
        const int T = static_cast<int>(MapPointType::TREASURE);
        for (std::uint64_t seed : {1ull, 42ull, 977ull, 123456789ull, 0xC0FFEEull}) {
            for (int asc : {0, 10}) {
                ActMap m, again;
                generate_spoils_act_map(m, seed, 1, asc);
                generate_spoils_act_map(again, seed, 1, asc);
                check(same_map(m, again), "Spoils map is a pure function of the run seed");
                const int tRow = m.mapLength - 7;
                check(m.mapLength == 15, "act 2 has 14 rooms");
                int treasures = 0;
                for (int row = 1; row < m.mapLength; ++row) {
                    int inRow = 0;
                    for (int col = 0; col < MAP_WIDTH; ++col) {
                        const int idx = m.at(row, col);
                        if (idx < 0) continue;
                        ++inRow;
                        const MapNode &node = m.nodes[idx];
                        treasures += node.type == T;
                        if (row == 1) check(node.type == static_cast<int>(MapPointType::MONSTER), "row 1 is monsters");
                        if (row == m.mapLength - 1) check(node.type == static_cast<int>(MapPointType::REST), "last row rests");
                        if (row == tRow) check(col == 3 && node.type == T, "the only treasure-row point is the centre Treasure");
                        if (row >= 2 && std::abs(row - tRow) <= 2 && row < m.mapLength - 1)
                            check(std::abs(col - 3) <= std::abs(row - tRow), "hourglass narrows toward the Treasure");
                        for (int k = 0; k < node.childCount; ++k) {
                            int cr, cc;
                            coord_of(m, node.children[k], cr, cc);
                            check(cr == row + 1 && std::abs(cc - col) <= 1, "edges step one row, at most one column");
                        }
                    }
                    if (row == tRow) check(inRow == 1, "one point on the treasure row");
                }
                check(treasures == 1, "exactly one Treasure");
            }
        }

        RunContext r;
        r.init(20261109, 0);
        r.hp = 50;
        const int legends = event("THE_LEGENDS_WERE_TRUE");
        check(event_info(legends)->status == EventStatus::IMPLEMENTED, "registered as implemented");
        check(event_is_allowed(r, legends), "allowed in act 1 with >= 10 HP");
        RunContext low = r;
        low.hp = 9;
        check(!event_is_allowed(low, legends), "not below 10 HP");
        RunContext later = r;
        later.act = 1;
        check(!event_is_allowed(later, legends), "act 1 only");
        event_begin(r, legends, false);
        check(event_option_count(r) == 2, "two options");
        RunContext exitRun = r;
        const int deck = r.deckCount;
        check(r.step({RunActionType::EVENT_CHOICE, 0}) && r.deckCount == deck + 1 &&
              r.deck[deck].id == CardId::SPOILS_MAP && r.spoils_map_count() == 1, "Nab the Map adds Spoils Map");
        const Rng rewards = exitRun.playerRng[PRNG_REWARDS];
        check(exitRun.step({RunActionType::EVENT_CHOICE, 1}) && exitRun.hp == 42 && exitRun.deckCount == deck &&
              exitRun.pendingPotions[0] != 0 && exitRun.playerRng[PRNG_REWARDS].counter == rewards.counter + 1,
              "Slowly Find an Exit: 8 damage and one Rewards-RNG potion");

        // No Spoils Map: act 2 keeps the standard map. With it: the Spoils map.
        RunContext plain;
        plain.init(20261109, 0);
        plain.start_act(1);
        ActMap standard;
        Rng mapRng(plain.seed, "act_2_map");
        generate_act_map(standard, mapRng, 1, plain.ascension);
        check(same_map(plain.map, standard) && !plain.spoils_quest_active() && plain.spoilsQuestRow == -1,
              "no card: standard act-2 map, no quest");
        RunContext a = r;
        a.start_act(1);
        ActMap spoils;
        generate_spoils_act_map(spoils, a.seed, 1, a.ascension);
        check(same_map(a.map, spoils), "card in deck: act 2 uses the Spoils map");
        check(a.spoils_quest_active() && a.spoilsQuestRow == a.map.mapLength - 7 && a.spoilsQuestCol == 3,
              "quest on the Treasure");
        const auto obs = public_observation(a);
        check(obs[PUBLIC_RUN_DIM - 3] == 1.0f && obs[PUBLIC_RUN_DIM - 2] > 0.0f && obs[PUBLIC_RUN_DIM - 1] == 0.5f,
              "quest marker observed");
        RunContext saved;
        check(RunContext::restore(a.serialize(), saved) && saved.spoilsQuestRow == a.spoilsQuestRow &&
              saved.spoils_quest_active(), "quest survives a snapshot");

        // Reaching the Treasure pays 600 after the chest gold and removes the card.
        RunContext pay = a;
        pay.curRow = pay.spoilsQuestRow;
        pay.curCol = pay.spoilsQuestCol;
        pay.screen = RunScreen::TREASURE;
        const int gold = pay.gold;
        check(pay.step({RunActionType::COLLECT, 0}), "open the chest");
        check(pay.gold - gold >= 600 + 42 && pay.gold - gold <= 600 + 52 && pay.spoils_map_count() == 0 &&
              !pay.spoils_quest_active() && pay.pendingRelicCount == 1, "600 gold, card removed, relic still offered");
        // A different treasure pays nothing extra.
        RunContext other = a;
        other.curRow = static_cast<std::int8_t>(other.spoilsQuestRow - 1);
        other.curCol = 3;
        other.screen = RunScreen::TREASURE;
        const int otherGold = other.gold;
        check(other.step({RunActionType::COLLECT, 0}) && other.gold - otherGold <= 52 &&
              other.spoils_map_count() == 1, "only the quest point pays");
        // Removing the card in act 2 takes the quest off the map.
        RunContext removed = a;
        for (int i = 0; i < removed.deckCount; ++i)
            if (removed.deck[i].id == CardId::SPOILS_MAP) {
                for (int j = i; j + 1 < removed.deckCount; ++j) removed.deck[j] = removed.deck[j + 1];
                --removed.deckCount;
                break;
            }
        check(!removed.spoils_quest_active(), "removed card: no quest");
        removed.curRow = removed.spoilsQuestRow;
        removed.curCol = removed.spoilsQuestCol;
        removed.screen = RunScreen::TREASURE;
        const int removedGold = removed.gold;
        check(removed.step({RunActionType::COLLECT, 0}) && removed.gold - removedGold <= 52, "and no payout");
        // Golden Compass (a relic) runs after the card: golden path wins and the
        // quest moves to its first Treasure (row 8).
        RunContext golden = r;
        golden.goldenPathAct = 1;
        golden.start_act(1);
        ActMap goldenMap;
        generate_golden_path_map(goldenMap);
        check(same_map(golden.map, goldenMap) && golden.spoils_quest_active() && golden.spoilsQuestRow == 8 &&
              golden.spoilsQuestCol == 3, "Golden Compass replaces the Spoils map; quest on golden row 8");
        // Act 3 (index 2) is unaffected by an unspent Spoils Map.
        RunContext act3 = r;
        act3.start_act(2);
        check(!act3.spoils_quest_active() && act3.spoilsQuestRow == -1, "no quest outside act 2");
    }

    // ---- batch 15: Byrdonis Nest ------------------------------------------
    {
        RunContext r;
        r.init(20261110, 0);
        const int nest = event("BYRDONIS_NEST");
        check(event_info(nest)->status == EventStatus::IMPLEMENTED && event_is_allowed(r, nest), "allowed without a pet");
        RunContext withEgg = r;
        withEgg.add_card_to_deck(withEgg.make_run_card(CardId::BYRDONIS_EGG, false));
        check(!event_is_allowed(withEgg, nest), "an egg in the deck counts as an event pet");
        RunContext withPip = r;
        withPip.relics[withPip.relicCount++] = static_cast<int>(RelicId::BYRDPIP);
        check(!event_is_allowed(withPip, nest), "Byrdpip blocks the nest");
        event_begin(r, nest, false);
        check(event_option_count(r) == 2, "Eat / Take");
        RunContext eat = r;
        const int hp = eat.hp, maxHp = eat.maxHp, deck = eat.deckCount;
        check(eat.step({RunActionType::EVENT_CHOICE, 0}) && eat.maxHp == maxHp + 7 && eat.hp == hp + 7 &&
              eat.deckCount == deck && eat.screen == RunScreen::MAP, "Eat: +7 max HP");
        check(r.step({RunActionType::EVENT_CHOICE, 1}) && r.deckCount == deck + 1 &&
              r.deck[deck].id == CardId::BYRDONIS_EGG, "Take: Byrdonis Egg");
        // The egg offers HATCH at a rest site: Byrdpip, egg becomes Byrd Swoop.
        r.screen = RunScreen::REST;
        bool hatch = false;
        for (const RunAction &a : r.legal_actions()) hatch |= a.type == RunActionType::REST_HATCH;
        check(hatch, "rest site offers Hatch");
        check(r.step({RunActionType::REST_HATCH, 0}) && run_has_relic(r, RelicId::BYRDPIP), "hatch gives Byrdpip");
        int swoops = 0, eggs = 0;
        for (int i = 0; i < r.deckCount; ++i) {
            swoops += r.deck[i].id == CardId::BYRD_SWOOP;
            eggs += r.deck[i].id == CardId::BYRDONIS_EGG;
        }
        check(swoops == 1 && eggs == 0, "egg transformed into Byrd Swoop");
        check(!event_is_allowed(r, nest), "no second nest once hatched");
    }

    // ---- batch 16: Aeonglass (Glory boss) ------------------------------------
    {
        const auto str = [](const Monster &m) { return m.strength; };  // monster_power(STRENGTH)
        Card deck[20];
        for (int i = 0; i < 20; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
        for (int asc : {0, 8, 9}) {
            BattleContext b;
            b.init(Encounter::SETUP_AEONGLASS_BOSS, 77, deck, 20, asc, 5000, 5000);
            check(b.monsterCount == 1 && b.monsters[0].id == MonsterId::AEONGLASS, "single Aeonglass");
            const Monster &m = b.monsters[0];
            check(m.maxHp == (asc >= 8 ? 535 : 512) && m.hp == m.maxHp, "HP 512 / 535 at Tough Enemies");
            check(m.power[static_cast<int>(PowerId::ARTIFACT)] == 3, "Artifact 3");
            check(b.player_power(PowerId::WITHERING_PRESENCE) == 6, "Withering Presence: 6 cards left");
            check(m.move == 0 && m.intentDamage == (asc >= 9 ? 26 : 22), "opens with Ebb");
        }
        BattleContext b;
        b.init(Encounter::SETUP_AEONGLASS_BOSS, 77, deck, 20, 0, 5000, 5000);
        // Six played cards put a Wither in hand and reset the counter.
        int played = 0;
        for (int k = 0; k < 6; ++k) {
            b.player.energy = 99;
            int idx = -1;
            for (int i = 0; i < b.handCount; ++i) if (b.hand[i].id == CardId::DEFEND_IRONCLAD) { idx = i; break; }
            if (idx < 0) break;
            Action a;
            a.type = ActionType::PLAY_CARD;
            a.hand = static_cast<std::uint8_t>(idx);
            a.uid = b.hand[idx].uid;
            if (!b.step(a)) break;
            ++played;
            if (k < 5) check(b.player_power(PowerId::WITHERING_PRESENCE) == 5 - k, "counter ticks down per card");
        }
        if (played < 6) {  // the opening hand is 5 cards: draw one more Defend
            b.hand[b.handCount++] = make_card(CardId::DEFEND_IRONCLAD, false, b.require_card_uid());
            b.player.energy = 99;
            Action a;
            a.type = ActionType::PLAY_CARD;
            a.hand = static_cast<std::uint8_t>(b.handCount - 1);
            a.uid = b.hand[b.handCount - 1].uid;
            check(b.step(a), "sixth card");
        }
        int withers = 0;
        for (int i = 0; i < b.handCount; ++i) withers += b.hand[i].id == CardId::WITHER;
        check(withers == 1 && b.player_power(PowerId::WITHERING_PRESENCE) == 6, "sixth card: Wither to hand, counter back to 6");
        // Ebb: 22 damage then 33 Block. Withers in hand deal 3 at turn end.
        b.player.block = 0;
        const int hp0 = b.player.hp;
        b.end_player_turn();
        check(hp0 - b.player.hp == 3 + 22 && b.monsters[0].block == 33, "Wither 3 + Ebb 22, Aeonglass blocks 33");
        check(b.monsters[0].move == 1, "then Eye Lasers");
        b.player.block = 0;
        const int hp1 = b.player.hp;
        b.end_player_turn();
        check(hp1 - b.player.hp == 22 && b.monsters[0].move == 2, "Eye Lasers 11 x2");
        // Increasing Intensity: every Wither +3, a new +3 Wither to discard, Strength 3.
        const auto witherBonus = [&](double &minBonus, double &maxBonus, int &n) {
            minBonus = 1e9; maxBonus = -1; n = 0;
            Card *piles[] = {b.hand, b.draw, b.discard, b.exhaust};
            const int counts[] = {b.handCount, b.drawCount, b.discardCount, b.exhaustCount};
            for (int p = 0; p < 4; ++p)
                for (int i = 0; i < counts[p]; ++i)
                    if (piles[p][i].id == CardId::WITHER) {
                        minBonus = std::min(minBonus, piles[p][i].bonusDamage);
                        maxBonus = std::max(maxBonus, piles[p][i].bonusDamage);
                        ++n;
                    }
        };
        double lo, hi;
        int n;
        b.end_player_turn();
        witherBonus(lo, hi, n);
        check(n == 2 && lo == 3 && hi == 3 && str(b.monsters[0]) == 3 && b.monsters[0].aux[0] == 1,
              "first Intensity: both Withers +3, Strength 3");
        check(b.monsters[0].move == 0, "cycle returns to Ebb");
        b.end_player_turn();
        b.end_player_turn();
        b.end_player_turn();
        witherBonus(lo, hi, n);
        check(n == 3 && lo == 6 && hi == 6 && str(b.monsters[0]) == 3 + 4 && b.monsters[0].aux[0] == 2,
              "second Intensity: Withers +6, Strength +4 (7)");
        // A Wither generated later matches the current upgrade count.
        add_withers(b, 1, true);
        check(b.hand[b.handCount - 1].id == CardId::WITHER && b.hand[b.handCount - 1].bonusDamage == 6,
              "new Wither matches WitherUpgradeCount");
        BattleContext a9;
        a9.init(Encounter::SETUP_AEONGLASS_BOSS, 77, deck, 20, 9, 5000, 5000);
        a9.end_player_turn();
        a9.end_player_turn();
        a9.end_player_turn();
        witherBonus(lo, hi, n);
        int a9Withers = 0;
        for (int i = 0; i < a9.discardCount; ++i) a9Withers += a9.discard[i].id == CardId::WITHER;
        for (int i = 0; i < a9.drawCount; ++i) a9Withers += a9.draw[i].id == CardId::WITHER;
        for (int i = 0; i < a9.handCount; ++i) a9Withers += a9.hand[i].id == CardId::WITHER;
        check(a9Withers == 2 && str(a9.monsters[0]) == 4, "A9: two Withers, Strength 4");

        // Mid-fight snapshot with grown Withers and the boss counters.
        RunContext fight;
        fight.init(31337, 0);
        fight.start_act(2);
        fight.begin_combat(Encounter::SETUP_AEONGLASS_BOSS);
        fight.battle.player.maxHp = fight.battle.player.hp = 5000;  // survive six skipped turns
        for (int t = 0; t < 6 && fight.battle.outcome == Outcome::UNDECIDED; ++t)
            check(fight.battle.step(Action{}), "end turn via a real action");
        int grown = 0;
        for (int i = 0; i < fight.battle.discardCount; ++i)
            grown += fight.battle.discard[i].id == CardId::WITHER && fight.battle.discard[i].bonusDamage == 6;
        for (int i = 0; i < fight.battle.drawCount; ++i)
            grown += fight.battle.draw[i].id == CardId::WITHER && fight.battle.draw[i].bonusDamage == 6;
        for (int i = 0; i < fight.battle.handCount; ++i)
            grown += fight.battle.hand[i].id == CardId::WITHER && fight.battle.hand[i].bonusDamage == 6;
        RunContext restoredFight;
        check(grown == 2 && fight.battle.monsters[0].aux[0] == 2 &&
              RunContext::restore(fight.serialize(), restoredFight) &&
              restoredFight.battle.monsters[0].aux[0] == 2 && restoredFight.battle.monsters[0].aux[1] == 2 &&
              restoredFight.battle.player_power(PowerId::WITHERING_PRESENCE) == 6,
              "Aeonglass fight survives a snapshot with grown Withers");

        // Glory boss pool: Aeonglass replaces the legacy Doormaker slot.
        int counts[3] = {0, 0, 0};
        for (std::uint64_t seed = 1; seed <= 300; ++seed) {
            RunContext r;
            r.init(seed, 0);
            r.start_act(2);
            const auto boss = static_cast<Encounter>(r.bossEncounter);
            check(boss != Encounter::SETUP_DOORMAKER_BOSS, "Doormaker is not in the native Glory pool");
            counts[0] += boss == Encounter::SETUP_AEONGLASS_BOSS;
            counts[1] += boss == Encounter::SETUP_QUEEN_BOSS;
            counts[2] += boss == Encounter::SETUP_TEST_SUBJECT_BOSS;
        }
        check(counts[0] > 60 && counts[1] > 60 && counts[2] > 60 && counts[0] + counts[1] + counts[2] == 300,
              "Glory bosses: Aeonglass / Queen / TestSubject");
        // Discovery order Queen -> TestSubject -> Aeonglass.
        NativeProgressContext progress;
        progress.applyDiscoveryOrder = true;
        progress.numberOfRuns = 3;
        progress.aeonglassSeen = false;
        RunContext forced;
        forced.init_with_context(5, 0, 0, progress);
        forced.start_act(2);
        check(forced.bossEncounter == static_cast<int>(Encounter::SETUP_AEONGLASS_BOSS),
              "first Aeonglass discovery is forced (previously refused)");
    }

    // ---- batch 17: reward pools, Splash, Wongo's, shop filter ------------
    {
        const auto give = [](RunContext &r, RelicId id) { r.relics[r.relicCount++] = static_cast<int>(id); };
        const auto poolOf = [](const Card &c) { return card_def(c.id).pool; };
        // Prismatic Gem: every unlocked character pool, never Colorless.
        int other = 0, colorless = 0, total = 0;
        for (std::uint64_t seed = 1; seed <= 60; ++seed) {
            RunContext r;
            r.init(seed, 0);
            give(r, RelicId::PRISMATIC_GEM);
            r.roll_card_reward(false);
            for (int i = 0; i < r.offeredCount; ++i) {
                ++total;
                other += poolOf(r.offered[i]) != CardPool::IRONCLAD && poolOf(r.offered[i]) != CardPool::COLORLESS;
                colorless += poolOf(r.offered[i]) == CardPool::COLORLESS;
            }
        }
        check(total == 180 && other > 60 && colorless == 0, "Prismatic Gem: other characters' cards, no colorless");
        // Dingy Rug: Ironclad + Colorless in any slot.
        int rugColorless = 0, rugFirstSlots = 0, rugOther = 0;
        for (std::uint64_t seed = 1; seed <= 80; ++seed) {
            RunContext r;
            r.init(seed, 0);
            give(r, RelicId::DINGY_RUG);
            r.roll_card_reward(false);
            for (int i = 0; i < r.offeredCount; ++i) {
                const bool c = poolOf(r.offered[i]) == CardPool::COLORLESS;
                rugColorless += c;
                rugFirstSlots += c && i < 2;
                rugOther += poolOf(r.offered[i]) != CardPool::IRONCLAD && !c;
            }
        }
        check(rugColorless > 10 && rugFirstSlots > 0 && rugOther == 0, "Dingy Rug merges Colorless into every slot");
        RunContext lone;
        lone.init(5, 0);
        lone.nativeProgress.unlockedCharacterMask = 1;
        give(lone, RelicId::PRISMATIC_GEM);
        CardId widened[static_cast<int>(CardId::COUNT)], plain[static_cast<int>(CardId::COUNT)];
        RunContext bare;
        bare.init(5, 0);
        check(native_card_reward_pool(lone, CardPool::IRONCLAD, widened) ==
                  native_card_reward_pool(bare, CardPool::IRONCLAD, plain),
              "Prismatic Gem with only Ironclad unlocked changes nothing");
        // Unchanged without either relic (same RNG stream as before this batch).
        RunContext a, b2;
        a.init(77, 0);
        b2.init(77, 0);
        a.roll_card_reward(false);
        b2.roll_card_reward(false);
        check(a.offered[0].id == b2.offered[0].id && poolOf(a.offered[2]) == CardPool::IRONCLAD, "plain rewards unchanged");

        // Splash: attacks from the other unlocked characters.
        for (int mask : {31, 1}) {
            Card deck[10];
            for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::SPLASH, false, i + 1);
            BattleContext bc;
            bc.init(Encounter::SETUP_NIBBITS_WEAK, 9, deck, 10, 0, 80, 80);
            bc.unlockedCharacterMask = static_cast<std::uint8_t>(mask);
            bc.player.energy = 9;
            Action play;
            play.type = ActionType::PLAY_CARD;
            play.hand = 0;
            play.uid = bc.hand[0].uid;
            check(bc.step(play) && bc.pending.count == 3, "Splash offers three");
            bool ok = true;
            for (int i = 0; i < bc.pending.count; ++i) {
                const CardDef &d = card_def(bc.pending.cards[i].id);
                ok &= d.type == CardType::ATTACK && (mask == 1 ? d.pool == CardPool::IRONCLAD : d.pool != CardPool::IRONCLAD &&
                                                                                                d.pool != CardPool::COLORLESS);
            }
            check(ok, mask == 1 ? "Splash: only Ironclad unlocked -> Ironclad attacks" : "Splash: other characters' attacks");
        }

        // Shops never stock IsAllowedInShops == false relics.
        bool clean = true;
        for (std::uint64_t seed = 1; seed <= 150 && clean; ++seed) {
            RunContext r;
            r.init(seed, 0);
            for (int k = 0; k < 4; ++k) {
                r.roll_shop();
                for (int i = 0; i < r.shopRelicCount; ++i) clean &= relic_allowed_in_shops(static_cast<RelicId>(r.shopRelics[i]));
            }
        }
        check(clean, "shops skip Bowler Hat / Aubergine / Lucky Fysh / Old Coin / Courier");

        // Welcome to Wongo's.
        RunContext w;
        w.init(4242, 0);
        w.act = 1;
        w.gold = 999;
        const int wongo = event("WELCOME_TO_WONGOS");
        event_begin(w, wongo, false);
        const auto featured = static_cast<RelicId>(w.eventData[0]);
        check(relic_def(featured).rarity == Rarity::RARE && relic_allowed_in_shops(featured), "featured rare pulled on entry");
        RunContext buy = w;
        check(buy.step({RunActionType::EVENT_CHOICE, 1}) && run_has_relic(buy, featured) && buy.gold == 799 &&
              !run_has_relic(buy, RelicId::WONGO_CUSTOMER_APPRECIATION_BADGE), "featured item for 200");
        RunContext bin = w;
        const int relicsBefore = bin.relicCount;
        check(bin.step({RunActionType::EVENT_CHOICE, 0}) && bin.relicCount == relicsBefore + 1 && bin.gold == 899 &&
              relic_def(static_cast<RelicId>(bin.relics[bin.relicCount - 1])).rarity == Rarity::COMMON &&
              relic_allowed_in_shops(static_cast<RelicId>(bin.relics[bin.relicCount - 1])), "bargain bin: shop-allowed common");
        RunContext near;
        near.init(4242, 0);
        near.act = 1;
        near.gold = 999;
        near.nativeProgress.wongoPoints = 3990;  // 1990 toward the next badge
        event_begin(near, wongo, false);
        check(near.step({RunActionType::EVENT_CHOICE, 0}) &&
              run_has_relic(near, RelicId::WONGO_CUSTOMER_APPRECIATION_BADGE), "32 points cross 2000: badge");
        RunContext ticket = w;
        check(ticket.step({RunActionType::EVENT_CHOICE, 2}) && run_has_relic(ticket, RelicId::WONGOS_MYSTERY_TICKET) &&
              ticket.gold == 699, "mystery box for 300");

        // Mystery Ticket: the fifth finished combat's reward set gets three relics, once.
        RunContext t;
        t.init(99, 0);
        give(t, RelicId::WONGOS_MYSTERY_TICKET);
        t.wongoCombats = 4;
        const auto win = [](RunContext &r) {
            r.begin_combat(Encounter::SETUP_NIBBITS_WEAK);
            for (int i = 0; i < r.battle.monsterCount; ++i) { r.battle.monsters[i].hp = 0; r.battle.monsters[i].alive = false; }
            r.battle.outcome = Outcome::PLAYER_VICTORY;
            r.finish_combat();
        };
        win(t);
        check(t.pendingRelicCount == 3 && t.wongoCombats == 6, "fifth combat: three relics");
        t.pendingRelicCount = 0;
        t.screen = RunScreen::MAP;
        win(t);
        check(t.pendingRelicCount == 0 && t.wongoCombats == 6, "only once");
    }

    // ---- batch 18: room generation timing ---------------------------------
    // C++-internal check only (not a native comparison): HP is raised to 30000 so
    // runs reach act 3; it shows gameplay between acts never draws UpFront.
    // Native generates every act's rooms at run start from Rng.UpFront; C++
    // does it on entering each act. Nothing else draws UpFront mid-run, so the
    // per-act results must equal back-to-back generation.
    {
        struct Rooms {
            int normalN, eliteN, eventN, boss, second, ancient;
            std::uint16_t normal[32], elite[16], events[128];
            std::uint64_t upFront;
        };
        const auto snap = [](const RunContext &r) {
            Rooms x{};
            x.normalN = r.normalBagN; x.eliteN = r.eliteBagN; x.eventN = r.eventBagN;
            x.boss = r.bossEncounter; x.second = r.secondBossEncounter; x.ancient = r.ancientId;
            for (int i = 0; i < r.normalBagN; ++i) x.normal[i] = r.normalBag[i];
            for (int i = 0; i < r.eliteBagN; ++i) x.elite[i] = r.eliteBag[i];
            for (int i = 0; i < r.eventBagN; ++i) x.events[i] = r.eventBag[i];
            x.upFront = r.runRng[RNG_UP_FRONT].counter;
            return x;
        };
        const auto same = [](const Rooms &a, const Rooms &b) {
            if (a.normalN != b.normalN || a.eliteN != b.eliteN || a.eventN != b.eventN || a.boss != b.boss ||
                a.second != b.second || a.ancient != b.ancient || a.upFront != b.upFront) return false;
            for (int i = 0; i < a.normalN; ++i) if (a.normal[i] != b.normal[i]) return false;
            for (int i = 0; i < a.eliteN; ++i) if (a.elite[i] != b.elite[i]) return false;
            for (int i = 0; i < a.eventN; ++i) if (a.events[i] != b.events[i]) return false;
            return true;
        };
        int reachedAct3 = 0;
        for (std::uint32_t seed = 1; seed <= 12; ++seed) {
            for (int asc : {0, 10}) {
                RunContext ref;
                ref.init(seed, asc);
                Rooms expected[3];
                expected[0] = snap(ref);
                for (int act = 1; act < 3; ++act) { ref.start_act(act); expected[act] = snap(ref); }

                RunContext rc;
                rc.init(seed, asc);
                check(same(snap(rc), expected[0]), "act 1 rooms");
                rc.maxHp = rc.hp = 30000;
                Rng rng(seed * 7919u + 3u);
                int seenAct = 0, guard = 0;
                while (!rc.is_over() && guard++ < 40000 && seenAct < 2) {
                    if (rc.act != seenAct) {
                        seenAct = rc.act;
                        check(same(snap(rc), expected[seenAct]), "rooms after real play equal up-front generation");
                    }
                    if (rc.screen == RunScreen::COMBAT) {
                        if (!rc.step_combat(greedy_action(rc.battle, rng, 0.05))) break;
                        continue;
                    }
                    const std::vector<RunAction> legal = rc.legal_actions();
                    if (legal.empty()) break;
                    RunAction pick = legal[rng.next_int(0, static_cast<int>(legal.size()) - 1)];
                    if (rc.cardGrid.kind && pick.type != RunActionType::CONFIRM_GRID_CARDS) {
                        for (const RunAction &a : legal)
                            if (a.type == RunActionType::SELECT_GRID_CARD && !rc.cardGrid.selected[a.index]) { pick = a; break; }
                    }
                    if (!rc.step(pick)) break;
                }
                if (rc.act == 2 && seenAct == 2) ++reachedAct3;
            }
        }
        check(reachedAct3 >= 12, "most runs reach act 3 for the comparison");
    }

    // ---- batch 19: epoch content gating -----------------------------------
    {
        const auto epochBit = [](const char *name) {
            for (int i = 0; i < native_epoch_count(); ++i)
                if (!std::strcmp(native_epoch_name(i), name)) return i;
            return -1;
        };
        const int ic2 = epochBit("Ironclad2Epoch"), ic3 = epochBit("Ironclad3Epoch"), relic1 = epochBit("Relic1Epoch"),
                  potion1 = epochBit("Potion1Epoch"), ic4 = epochBit("Ironclad4Epoch");
        check(native_epoch_count() == 57 && ic2 >= 0 && ic3 >= 0 && relic1 >= 0 && potion1 >= 0, "57 native epochs");
        check(card_unlock_epoch(CardId::MOLTEN_FIST) == ic2 && card_unlock_epoch(CardId::CRUELTY_CARD) == ic2 &&
              card_unlock_epoch(CardId::DOMINATE) == ic2 && card_unlock_epoch(CardId::STRIKE_IRONCLAD) == -1,
              "Ironclad2Epoch locks Molten Fist / Cruelty / Dominate");
        int lockedCards = 0, lockedRelics = 0, lockedPotions = 0;
        for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) lockedCards += card_unlock_epoch(static_cast<CardId>(i)) >= 0;
        for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) lockedRelics += relic_unlock_epoch(static_cast<RelicId>(i)) >= 0;
        for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) lockedPotions += potion_unlock_epoch(static_cast<PotionId>(i)) >= 0;
        check(lockedCards == 60 && lockedRelics == 45 && lockedPotions == 21, "all generated locks resolve");

        // A fresh account (only base epochs): locked content never appears.
        NativeProgressContext fresh;
        fresh.revealedEpochs = 0;
        bool cardsClean = true, relicsClean = true, potionsClean = true, sawReward = false;
        for (std::uint64_t seed = 1; seed <= 120; ++seed) {
            RunContext r;
            r.init_with_context(seed, 0, static_cast<int>(ActType::OVERGROWTH), fresh);
            r.roll_card_reward(false);
            for (int i = 0; i < r.offeredCount; ++i) {
                sawReward = true;
                cardsClean &= card_unlock_epoch(r.offered[i].id) < 0;
            }
            r.roll_shop();
            for (int i = 0; i < r.shopCount; ++i) cardsClean &= card_unlock_epoch(r.shopCards[i].id) < 0;
            for (int i = 0; i < r.shopRelicCount; ++i)
                relicsClean &= relic_unlock_epoch(static_cast<RelicId>(r.shopRelics[i])) < 0;
            for (int i = 0; i < r.shopPotionCount; ++i)
                potionsClean &= potion_unlock_epoch(static_cast<PotionId>(r.shopPotions[i])) < 0;
            for (int s = 0; s < RELIC_BAG_SLOTS; ++s)
                for (int i = 0; i < r.playerRelicBag.counts[s]; ++i)
                    relicsClean &= relic_unlock_epoch(static_cast<RelicId>(r.playerRelicBag.entries[s][i])) < 0;
            r.begin_combat(Encounter::SETUP_NIBBITS_WEAK);
            check(r.battle.revealedEpochs == 0, "battle inherits the epoch mask");
        }
        check(sawReward && cardsClean && relicsClean && potionsClean, "fresh account: no epoch-locked cards/relics/potions");
        // Revealing one epoch brings exactly its content back.
        NativeProgressContext partial = fresh;
        partial.revealedEpochs = (std::uint64_t{1} << ic2) | (std::uint64_t{1} << ic3) | (std::uint64_t{1} << relic1) |
                                 (std::uint64_t{1} << potion1) | (std::uint64_t{1} << ic4);
        bool sawIc2 = false;
        for (std::uint64_t seed = 1; seed <= 400 && !sawIc2; ++seed) {
            RunContext r;
            r.init_with_context(seed, 0, static_cast<int>(ActType::OVERGROWTH), partial);
            r.roll_card_reward(false);
            for (int i = 0; i < r.offeredCount; ++i) {
                const int e = card_unlock_epoch(r.offered[i].id);
                check(e < 0 || e == ic2, "only revealed epochs' cards");
                sawIc2 |= e == ic2;
            }
        }
        check(sawIc2, "Ironclad2Epoch cards return once revealed");
        // Default progress is fully revealed: identical to the pre-gating behaviour.
        RunContext d1, d2;
        d1.init(31, 0);
        d2.init_with_context(31, 0, static_cast<int>(ActType::OVERGROWTH), NativeProgressContext{});
        d1.roll_card_reward(false);
        d2.roll_card_reward(false);
        check(d1.offered[0].id == d2.offered[0].id && d1.nativeProgress.revealedEpochs == ~std::uint64_t{0},
              "default: every epoch revealed");
    }

    // ---- batch 20: cost stack, death, forced choices, Shackles, Royalties --
    {
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
        // Frantic Escape (+1 this combat) vs free-this-combat: native insertion order.
        Card fe = make_card(CardId::FRANTIC_ESCAPE, false, 500);
        const int base = card_cost(fe);
        card_modify_cost(fe, 0, true, 0);   // made free first
        card_modify_cost(fe, 1, false, 0);  // then Frantic Escape played
        check(card_cost(fe) == 1, "free then +1 -> 1");
        Card fe2 = make_card(CardId::FRANTIC_ESCAPE, false, 501);
        card_modify_cost(fe2, 1, false, 0);
        card_modify_cost(fe2, 0, true, 0);
        check(card_cost(fe2) == 0 && base >= 0, "+1 then free -> 0");
        // Snecko (absolute, combat) survives an in-combat upgrade of the base.
        Card bash = make_card(CardId::BASH, false, 502);
        card_modify_cost(bash, 3, true, 0);
        card_apply_upgrade(bash);
        check(card_cost(bash) == 3 || card_def(CardId::BASH).costUp < 3, "Snecko cost kept across upgrade");
        Card fe3 = make_card(CardId::FRANTIC_ESCAPE, false, 503);
        card_modify_cost(fe3, 1, false, 0);
        card_apply_downgrade(fe3);
        check(card_cost(fe3) == card_def(CardId::FRANTIC_ESCAPE).cost + 1, "relative +1 kept across downgrade");
        // Per-draw Snecko re-rolls stay within capacity.
        Card snecko = make_card(CardId::STRIKE_IRONCLAD, false, 504);
        for (int k = 0; k < 200; ++k) card_modify_cost(snecko, k % 4, true, 0);
        check(snecko.costModifierCount == 1 && card_cost(snecko) == 199 % 4, "combat absolute compacts the stack");
        // Snecko Oil: this turn or until played.
        BattleContext oil;
        oil.init(Encounter::SETUP_NIBBITS_WEAK, 3, deck, 10, 0, 80, 80);
        Card &h0 = oil.hand[0];
        card_modify_cost(h0, 3, true, 2 | 4);
        check(card_cost(h0) == 3, "Snecko Oil cost applies");
        oil.player.block = 0;
        check(oil.step(Action{}), "end turn");
        bool reset = true;
        for (int i = 0; i < oil.handCount; ++i) reset &= card_cost(oil.hand[i]) == 1;
        for (int i = 0; i < oil.drawCount; ++i) reset &= oil.draw[i].costModifierCount == 0;
        for (int i = 0; i < oil.discardCount; ++i) reset &= oil.discard[i].costModifierCount == 0;
        check(reset, "EndOfTurnCleanup clears turn modifiers on every pile");

        // Death clears the player's powers.
        BattleContext dead;
        dead.init(Encounter::SETUP_NIBBITS_WEAK, 3, deck, 10, 0, 5, 80);
        dead.add_player_power(PowerId::STRENGTH, 4);
        dead.add_player_power(PowerId::METALLICIZE, 3);
        dead.lose_hp(50);
        check(dead.outcome == Outcome::PLAYER_LOSS && dead.player_power(PowerId::STRENGTH) == 0 &&
              dead.player_power(PowerId::METALLICIZE) == 0, "RemoveAllPowersAfterDeath");

        // A forced single-candidate choice outside the play loop (potion) is taken.
        BattleContext pot;
        pot.init(Encounter::SETUP_NIBBITS_WEAK, 3, deck, 10, 0, 80, 80);
        pot.discard[pot.discardCount++] = make_card(CardId::BASH, false, pot.require_card_uid());
        pot.add_potion(PotionId::LIQUID_MEMORIES);
        Action use;
        use.type = ActionType::USE_POTION;
        use.hand = 0;
        const int handBefore = pot.handCount;
        check(pot.step(use) && pot.pending.op == ChoiceOp::NONE && pot.handCount == handBefore + 1 &&
              pot.hand[pot.handCount - 1].id == CardId::BASH && card_cost(pot.hand[pot.handCount - 1]) == 0,
              "Liquid Memories with one discard card resolves without asking");

        // Dark Shackles: own power, Artifact blocks it, Strength back after the enemy turn.
        Card sh[10];
        for (int i = 0; i < 10; ++i) sh[i] = make_card(CardId::DARK_SHACKLES, false, i + 1);
        BattleContext d;
        d.init(Encounter::SETUP_NIBBITS_WEAK, 3, sh, 10, 0, 500, 500);
        int target = 0;
        while (target < d.monsterCount && !d.monsters[target].alive) ++target;
        const int strBefore = d.monster_power(target, PowerId::STRENGTH);
        Action play;
        play.type = ActionType::PLAY_CARD;
        play.hand = 0;
        play.target = static_cast<std::uint8_t>(target);
        play.uid = d.hand[0].uid;
        check(d.step(play) && d.monster_power(target, PowerId::DARK_SHACKLES) > 0 &&
              d.monster_power(target, PowerId::STRENGTH) == strBefore - d.monster_power(target, PowerId::DARK_SHACKLES),
              "Dark Shackles lowers Strength via its own power");
        d.step(Action{});
        check(d.monster_power(target, PowerId::DARK_SHACKLES) == 0 &&
              d.monster_power(target, PowerId::STRENGTH) == strBefore, "restored after the enemy turn");
        BattleContext art;
        art.init(Encounter::SETUP_NIBBITS_WEAK, 3, sh, 10, 0, 500, 500);
        art.monsters[target].power[static_cast<int>(PowerId::ARTIFACT)] = 1;
        play.uid = art.hand[0].uid;
        const int artStr = art.monster_power(target, PowerId::STRENGTH);
        check(art.step(play) && art.monster_power(target, PowerId::STRENGTH) == artStr &&
              art.monster_power(target, PowerId::ARTIFACT) == 0, "Artifact blocks Dark Shackles entirely");

        // Royalties: an extra gold reward after the combat.
        RunContext roy;
        roy.init(12, 0);
        roy.begin_combat(Encounter::SETUP_NIBBITS_WEAK);
        roy.battle.add_player_power(PowerId::ROYALTIES, 30);
        for (int i = 0; i < roy.battle.monsterCount; ++i) { roy.battle.monsters[i].hp = 0; roy.battle.monsters[i].alive = false; }
        roy.battle.outcome = Outcome::PLAYER_VICTORY;
        roy.finish_combat();
        check(roy.extraGoldRewards[0] == 30 && roy.screen == RunScreen::REWARDS, "Royalties gold reward");
    }

    // ---- batch 21: remaining cost writers on the modifier stack -----------
    {
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
        const auto playHand = [](BattleContext &b, int idx) {
            Action a;
            a.type = ActionType::PLAY_CARD;
            a.hand = static_cast<std::uint8_t>(idx);
            a.uid = b.hand[idx].uid;
            for (int t = 0; t < b.monsterCount; ++t) if (b.monsters[t].alive) { a.target = static_cast<std::uint8_t>(t); break; }
            return b.step(a);
        };
        // Enlightenment: reduce-only 1; this turn (base) / this combat (upgraded).
        for (bool up : {false, true}) {
            BattleContext b;
            b.init(Encounter::SETUP_NIBBITS_WEAK, 5, deck, 10, 0, 500, 500);
            b.hand[0] = make_card(CardId::ENLIGHTENMENT, up, b.require_card_uid());
            b.hand[1] = make_card(CardId::BASH, false, b.require_card_uid());            // 2 -> 1
            b.hand[2] = make_card(CardId::ANGER, false, b.require_card_uid());           // 0 stays 0
            const std::uint16_t bashUid = b.hand[1].uid, angerUid = b.hand[2].uid;
            b.player.energy = 9;
            check(playHand(b, 0), "play Enlightenment");
            const auto cost_of = [&](std::uint16_t uid) {
                const Card *piles[] = {b.hand, b.draw, b.discard};
                const int counts[] = {b.handCount, b.drawCount, b.discardCount};
                for (int p = 0; p < 3; ++p)
                    for (int i = 0; i < counts[p]; ++i) if (piles[p][i].uid == uid) return card_cost(piles[p][i]);
                return -9;
            };
            check(cost_of(bashUid) == 1 && cost_of(angerUid) == 0, "reduce-only Set(1)");
            int keepIdx = -1;
            for (int i = 0; i < b.handCount; ++i) if (b.hand[i].uid == bashUid) keepIdx = i;
            b.hand[keepIdx].retainThisCombat = true;  // keep Bash in hand across the turn
            check(b.step(Action{}), "end turn");
            int bash = -1;
            for (int i = 0; i < b.handCount; ++i) if (b.hand[i].uid == bashUid) bash = i;
            check(bash >= 0 && card_cost(b.hand[bash]) == (up ? 1 : 2), up ? "Enlightenment+ lasts the combat" : "Enlightenment expires at turn end");
        }
        // Stomp: -1 per attack this turn wherever it sits, catch-up on entering combat, expires at turn end.
        {
            BattleContext b;
            b.init(Encounter::SETUP_NIBBITS_WEAK, 5, deck, 10, 0, 500, 500);
            b.draw[b.drawCount++] = make_card(CardId::STOMP, false, b.require_card_uid());
            const std::uint16_t stompUid = b.draw[b.drawCount - 1].uid;
            b.hand[0] = make_card(CardId::STRIKE_IRONCLAD, false, b.require_card_uid());
            b.hand[1] = make_card(CardId::STRIKE_IRONCLAD, false, b.require_card_uid());
            b.player.energy = 9;
            check(playHand(b, 0) && playHand(b, 0), "two attacks");
            int s = -1;
            for (int i = 0; i < b.drawCount; ++i) if (b.draw[i].uid == stompUid) s = i;
            check(s >= 0 && card_cost(b.draw[s]) == 1, "Stomp in the draw pile: 3 - 2");
            Card fresh = make_card(CardId::STOMP, false, b.require_card_uid());
            b.add_card_to_hand(fresh);
            check(card_cost(b.hand[b.handCount - 1]) == 1, "generated Stomp catches up on this turn's attacks");
            Card moved = b.draw[s];
            b.remove_draw_at(s);
            b.add_card_to_hand(moved);
            check(card_cost(b.hand[b.handCount - 1]) == 1, "drawn Stomp is not reduced twice");
            check(b.step(Action{}), "end turn");
            bool reset = true;
            int stomps = 0;
            const Card *piles[] = {b.hand, b.draw, b.discard};
            const int counts[] = {b.handCount, b.drawCount, b.discardCount};
            for (int p = 0; p < 3; ++p)
                for (int i = 0; i < counts[p]; ++i)
                    if (piles[p][i].id == CardId::STOMP) { ++stomps; reset &= card_cost(piles[p][i]) == 3; }
            reset &= stomps == 2;  // the drawn one and the generated one
            check(reset, "Stomp reductions expire at turn end");
        }
        // Mummified Hand: base cost > 0 counts even when a local modifier made it 0.
        {
            const int relic[] = {static_cast<int>(RelicId::MUMMIFIED_HAND)};
            BattleContext b;
            b.init(Encounter::SETUP_NIBBITS_WEAK, 5, deck, 10, 0, 500, 500, relic, 1);
            b.handCount = 0;
            b.hand[b.handCount++] = make_card(CardId::INFLAME, false, b.require_card_uid());
            b.hand[b.handCount++] = make_card(CardId::BASH, false, b.require_card_uid());
            card_modify_cost(b.hand[1], 0, true, 0);  // e.g. Snecko rolled 0
            const int before = b.hand[1].costModifierCount;
            const auto selection = b.cardSelectionRng.counter;
            b.player.energy = 9;
            check(playHand(b, 0), "play a Power");
            check(b.handCount == 1 && b.hand[0].costModifierCount == before + 1 &&
                  b.cardSelectionRng.counter == selection + 1, "third pass (base cost > 0) picks the Bash");
        }
    }

    // ---- batch 22: Imbued / Electric Shrymp ---------------------------------
    {
        Card skill = make_card(CardId::DEFEND_IRONCLAD, false, 1), attack = make_card(CardId::STRIKE_IRONCLAD, false, 2);
        check(card_can_enchant(skill, EnchantmentId::IMBUED) && !card_can_enchant(attack, EnchantmentId::IMBUED),
              "Imbued enchants Skills only");
        // Electric Shrymp: pick one Skill from the deck to Imbue.
        RunContext r;
        r.init(808, 0);
        check(r.add_relic(RelicId::ELECTRIC_SHRYMP) && r.cardGrid.kind == 15 && r.cardGrid.minSelect == 1 &&
              r.cardGrid.maxSelect == 1, "Electric Shrymp opens a one-card enchant pick");
        int defend = -1;
        for (int i = 0; i < r.deckCount && defend < 0; ++i) if (r.deck[i].id == CardId::DEFEND_IRONCLAD) defend = i;
        bool strikeSelectable = false;
        for (const RunAction &a : r.legal_actions())
            strikeSelectable |= a.type == RunActionType::SELECT_GRID_CARD && r.deck[a.index].id == CardId::STRIKE_IRONCLAD;
        check(!strikeSelectable, "Strikes are not selectable");
        check(r.step({RunActionType::SELECT_GRID_CARD, defend}) && r.step({RunActionType::CONFIRM_GRID_CARDS, 0}) &&
              r.deck[defend].enchantment == EnchantmentId::IMBUED && r.cardGrid.kind == 0, "Defend Imbued");
        RunContext saved;
        check(RunContext::restore(r.serialize(), saved), "snapshot with an Imbued card");
        // One eligible Skill: the selector is skipped.
        RunContext one;
        one.init(808, 0);
        for (int i = 0; i < one.deckCount;)
            if (one.deck[i].id == CardId::DEFEND_IRONCLAD && i != defend) {
                for (int j = i; j + 1 < one.deckCount; ++j) one.deck[j] = one.deck[j + 1];
                --one.deckCount;
            } else ++i;
        int skills = 0;
        for (int i = 0; i < one.deckCount; ++i) skills += card_type(one.deck[i]) == CardType::SKILL;
        check(skills == 1 && one.add_relic(RelicId::ELECTRIC_SHRYMP) && one.cardGrid.kind == 0, "single Skill auto-picked");
        // In combat: starts at the bottom of the draw pile, auto-plays on turn 1 only.
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        deck[0] = make_card(CardId::DEFEND_IRONCLAD, false, 1);
        card_apply_enchantment(deck[0], EnchantmentId::IMBUED, 1);
        BattleContext b;
        b.init(Encounter::SETUP_NIBBITS_WEAK, 21, deck, 10, 0, 500, 500);
        bool inHand = false, inDiscard = false;
        for (int i = 0; i < b.handCount; ++i) inHand |= b.hand[i].uid == 1;
        for (int i = 0; i < b.discardCount; ++i) inDiscard |= b.discard[i].uid == 1;
        check(!inHand && inDiscard && b.player.block == 5, "Imbued Defend auto-played on turn 1");
        Card deck2[10];
        for (int i = 0; i < 10; ++i) deck2[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        for (int i = 0; i < 3; ++i) {
            deck2[i] = make_card(CardId::DEFEND_IRONCLAD, false, i + 1);
            card_apply_enchantment(deck2[i], EnchantmentId::IMBUED, 1);
        }
        BattleContext b2;
        b2.init(Encounter::SETUP_NIBBITS_WEAK, 22, deck2, 10, 0, 500, 500);
        int imbuedLeft = 0;
        for (int i = 0; i < b2.drawCount; ++i) imbuedLeft += b2.draw[i].enchantment == EnchantmentId::IMBUED;
        for (int i = 0; i < b2.handCount; ++i) imbuedLeft += b2.hand[i].enchantment == EnchantmentId::IMBUED;
        check(imbuedLeft == 0 && b2.player.block == 15, "every Imbued card plays on turn 1");
    }

    // ---- batch 23: transforms create new entities ---------------------------
    {
        Card deck[10];
        for (int i = 0; i < 10; ++i) deck[i] = make_card(CardId::STRIKE_IRONCLAD, false, i + 1);
        BattleContext b;
        b.init(Encounter::SETUP_NIBBITS_WEAK, 31, deck, 10, 0, 500, 500);
        b.hand[0] = make_card(CardId::PRIMAL_FORCE, false, b.require_card_uid());
        std::uint16_t before[MAX_HAND];
        const int n = b.handCount;
        for (int i = 0; i < n; ++i) before[i] = b.hand[i].uid;
        b.player.energy = 9;
        Action a;
        a.type = ActionType::PLAY_CARD;
        a.hand = 0;
        a.uid = b.hand[0].uid;
        check(b.step(a), "play Primal Force");
        bool fresh = true;
        int rocks = 0;
        for (int i = 0; i < b.handCount; ++i) {
            if (b.hand[i].id != CardId::GIANT_ROCK) continue;
            ++rocks;
            for (int j = 0; j < n; ++j) fresh &= b.hand[i].uid != before[j];
            for (int j = 0; j < b.originalDeckCount; ++j) fresh &= b.originalDeckUids[j] != b.hand[i].uid;
        }
        check(rocks == n - 1 && fresh, "Giant Rocks are new entities without a deck link");
    }

    // ---- batch 24: combat reward option hooks / Lasting Candy -------------
    {
        const auto win = [](RunContext &r, Encounter enc) {
            r.screen = RunScreen::MAP;
            r.begin_combat(enc);
            for (int i = 0; i < r.battle.monsterCount; ++i) { r.battle.monsters[i].hp = 0; r.battle.monsters[i].alive = false; }
            r.battle.outcome = Outcome::PLAYER_VICTORY;
            r.finish_combat();
        };
        const auto give = [](RunContext &r, RelicId id) {
            r.relics[r.relicCount] = static_cast<int>(id);
            r.relicAux[r.relicCount++] = 0;
        };
        RunContext c;
        c.init(4040, 0);
        give(c, RelicId::LASTING_CANDY);
        win(c, Encounter::SETUP_NIBBITS_WEAK);
        check(c.offeredCount == 3 && c.relicAux[c.relicCount - 1] == 1, "first combat reward: 3 options, counter 1");
        win(c, Encounter::SETUP_NIBBITS_WEAK);
        bool distinctPower = c.offeredCount == 4 && card_type(c.offered[3]) == CardType::POWER;
        for (int i = 0; i < 3; ++i) distinctPower &= c.offered[i].id != c.offered[3].id;
        check(distinctPower && c.rewardCardCounts[0] == 4 && c.relicAux[c.relicCount - 1] == 2,
              "second combat: a fourth, distinct Power option");
        RunContext saved;
        check(RunContext::restore(c.serialize(), saved) && saved.offeredCount == 4, "4-option reward survives a snapshot");
        win(c, Encounter::SETUP_NIBBITS_WEAK);
        check(c.offeredCount == 3 && c.relicAux[c.relicCount - 1] == 3, "third combat: back to 3");
        // Late hooks now reach combat rewards (Glitter) and relic card rewards (Lost Coffer).
        RunContext g;
        g.init(4041, 0);
        give(g, RelicId::GLITTER);
        win(g, Encounter::SETUP_NIBBITS_WEAK);
        bool glam = g.offeredCount == 3;
        for (int i = 0; i < g.offeredCount; ++i) glam &= g.offered[i].enchantment == EnchantmentId::GLAM;
        check(glam, "Glitter enchants combat card rewards");
        RunContext lc;
        lc.init(4042, 0);
        give(lc, RelicId::GLITTER);
        check(lc.queue_card_reward(Rarity::COMMON, true), "Lost Coffer-style reward");
        bool glam2 = lc.rewardCardCounts[0] == 3;
        for (int i = 0; i < 3; ++i) glam2 &= lc.rewardCards[0][i].enchantment == EnchantmentId::GLAM;
        check(glam2, "Glitter enchants custom card rewards too");
    }

    // ---- batch 25: RollWithBaseOdds uncommon threshold (rare + 0.37) -----
    {
        int band = 0;
        for (std::uint64_t seed = 1; seed <= 3000 && band < 5; ++seed) {
            RunContext r;
            r.init(seed, 0);
            Rng peek = r.playerRng[PRNG_REWARDS];
            const float roll = peek.next_float();
            if (roll < 0.37f || roll >= 0.40f) continue;  // the band the old code got wrong
            ++band;
            check(r.queue_card_reward(Rarity::COMMON, true) &&
                  card_def(r.rewardCards[0][0].id).rarity == Rarity::UNCOMMON,
                  "Lost Coffer: roll in [0.37, 0.40) is Uncommon (37% band above the 3% rare)");
            RunContext g;
            g.init(seed, 0);
            Card out[5];
            check(make_noncombat_card_candidates(g, out, 1, CardPool::IRONCLAD, false) == 1 &&
                  card_def(out[0].id).rarity == Rarity::UNCOMMON, "non-combat candidates use the same threshold");
        }
        check(band == 5, "found seeds in the corrected band");
    }

    std::cout << "native step3 events batch1-25: " << checks << " checks, 0 failures\n";
    return 0;
}
