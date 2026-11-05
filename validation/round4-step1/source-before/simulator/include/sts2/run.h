// Full-run state for a standard A0 Ironclad climb (STS2 v0.111.0 contract).
#pragma once

#include <string>
#include <vector>

#include "sts2/battle.h"
#include "sts2/map.h"

namespace sts2 {

enum class RoomType : std::uint8_t { MONSTER, ELITE, EVENT, REST, SHOP, TREASURE, BOSS };
enum class RunScreen : std::uint8_t {
    MAP, COMBAT, CARD_REWARD, REST, SHOP, EVENT, TREASURE, RUN_OVER, REWARDS
};
enum class RunActionType : std::uint8_t {
    MOVE, TAKE_CARD, SKIP_CARD, REST_HEAL, REST_UPGRADE, REST_DIG, REST_LIFT,
    BUY_CARD, BUY_RELIC, BUY_POTION, REMOVE_CARD, LEAVE_SHOP,
    EVENT_CHOICE, COLLECT, USE_POTION,
    TAKE_GOLD_REWARD, TAKE_POTION_REWARD, TAKE_RELIC_REWARD, OPEN_CARD_REWARD,
    LEAVE_REWARDS, DISCARD_POTION, SACRIFICE_CARD_REWARD, EVENT_SELECT_CARD,
    TAKE_STOLEN_CARD_REWARD, SKIP_STOLEN_CARD_REWARD,
    SELECT_GRID_CARD, CONFIRM_GRID_CARDS, CANCEL_GRID_PREVIEW, REST_CLONE
};

struct RunAction {
    RunActionType type = RunActionType::MOVE;
    int index = 0;
};

// RunRngSet order matches MegaCrit.Sts2.Core.Entities.Rngs.RunRngType.
enum RunRngType : int {
    RNG_UP_FRONT, RNG_SHUFFLE, RNG_UNKNOWN_MAP_POINT, RNG_COMBAT_CARD_GENERATION,
    RNG_COMBAT_POTION_GENERATION, RNG_COMBAT_CARD_SELECTION, RNG_COMBAT_ENERGY_COSTS,
    RNG_COMBAT_TARGETS, RNG_MONSTER_AI, RNG_NICHE, RNG_COMBAT_ORBS,
    RNG_TREASURE_ROOM_RELICS, RNG_COUNT
};
// PlayerRngSet order matches PlayerRngType.
enum PlayerRngType : int { PRNG_REWARDS, PRNG_SHOPS, PRNG_TRANSFORMATIONS, PRNG_COUNT };

constexpr int MAX_DECK = 128;
constexpr int MAX_SHOP_CARDS = 7;      // 5 character + 2 colorless
constexpr int MAX_SHOP_RELICS = 3;
constexpr int MAX_SHOP_POTIONS = 3;
constexpr int MAX_ACTS = 3;
constexpr int MAX_EVENT_CHOICES = 4;
constexpr int MAX_REWARD_RELICS = 8;
constexpr int MAX_REWARD_POTIONS = 12;
constexpr int MAX_CARD_REWARDS = 8;
constexpr int RELIC_BAG_SLOTS = 4;  // common, uncommon, rare, shop
constexpr int RELIC_BAG_CAPACITY = static_cast<int>(RelicId::COUNT);

struct RelicBagState {
    std::uint16_t entries[RELIC_BAG_SLOTS][RELIC_BAG_CAPACITY]{};
    int counts[RELIC_BAG_SLOTS]{};
};

// Deliberately limited native progress context. Card/relic/event epoch filtering
// remains outside this API; those pools use the simulator's implemented content.
constexpr int SEEN_ENCOUNTER_WORDS = (static_cast<int>(Encounter::COUNT) + 63) / 64;
struct NativeProgressContext {
    bool applyDiscoveryOrder = false;
    int numberOfRuns = 1;
    bool neowUnlocked = true;
    bool orobasUnlocked = true;
    bool darvUnlocked = true;
    bool underdocksUnlocked = false;
    bool underdocksDiscovered = true;
    bool aeonglassSeen = true; // Not represented by the legacy encounter enum.
    std::uint64_t seenEncounters[SEEN_ENCOUNTER_WORDS]{};

    NativeProgressContext() {
        for (auto &word : seenEncounters) word = ~std::uint64_t{0};
    }
    bool has_seen(Encounter encounter) const {
        const int i = static_cast<int>(encounter);
        return i >= 0 && i < static_cast<int>(Encounter::COUNT) &&
               ((seenEncounters[i / 64] >> (i % 64)) & 1u) != 0;
    }
};

// A visible card grid can suspend any run screen (e.g. Claws obtained in a shop).
struct RunCardGrid {
    std::uint8_t kind = 0; // 1 Brain Leech, 2 Cheese, 3 Claws, 4 Pael's Growth, 5 Scroll Boxes;
                           // 6 remove, 7 transform, 8 transform+upgrade, 9 upgrade,
                           // 10 Pael's Tooth, 11 Spiral, 12 Steady enchantment
    Card cards[8]{};
    int count = 0;
    bool selected[MAX_DECK]{};
    int selectedCount = 0;
    int minSelect = 0;
    int maxSelect = 0;
    bool preview = false;
    int orderSlots[8] = {-1, -1, -1, -1, -1, -1, -1, -1};
    int freeNext[8] = {-1, -1, -1, -1, -1, -1, -1, -1};
    int slotCount = 0;
    int freeHead = -1;
    int damageAfterSelection = 0;
    CardId curseAfterSelection = CardId::INVALID;
};

struct RunContext {
    // --- identity -----------------------------------------------------------
    std::uint64_t seed = 0;
    int ascension = 0;
    ActType actTypes[MAX_ACTS]{ActType::OVERGROWTH, ActType::HIVE, ActType::GLORY};
    NativeProgressContext nativeProgress;
    int goldenPathAct = -1;
    int unknownMapPointsVisited = 0;

    // --- progression --------------------------------------------------------
    int hp = 80;
    int maxHp = 80;
    int gold = 99;
    int act = 0;        // 0..2
    int actFloor = 0;   // 1-based row within the act (Ancient == 1)
    int floor = 0;      // total floors entered
    bool won = false;
    bool truncated = false;  // safety cutoff; not a game loss

    ActMap map;
    std::int8_t curRow = -1;
    std::int8_t curCol = -1;
    std::uint64_t visitedLo = 0;
    std::uint64_t visitedHi = 0;
    std::int8_t lastPointType = 0;
    std::int8_t ancientId = 0;              // EventId of this act's Ancient
    bool sharedAncientInAct[MAX_ACTS]{};    // Darv assignment (C# GenerateRooms)

    // --- deck ---------------------------------------------------------------
    Card deck[MAX_DECK]{};
    int deckCount = 0;
    std::uint16_t nextUid = 1;

    // --- battle -------------------------------------------------------------
    BattleContext battle;
    bool inBattle = false;
    bool combatIsElite = false;
    bool combatIsBoss = false;
    int combatsFought = 0;
    int elitesFought = 0;
    int bossesFought = 0;
    Card stolenOriginals[MAX_PILE]{};
    bool stolenOriginalPresent[MAX_PILE]{};
    bool stolenRewardPending[MAX_PILE]{};
    int stolenSyncCount = 0;

    // --- screens ------------------------------------------------------------
    RunScreen screen = RunScreen::MAP;
    Card offered[3]{};
    int offeredCount = 0;
    bool rewardIsBoss = false;
    int pendingGoldReward = 0;
    int pendingRecoveredGold = 0;
    int pendingPotionReward = 0;  // PotionId::INVALID means none
    int pendingPotions[MAX_REWARD_POTIONS]{};
    int pendingPotionCount = 0;
    int pendingRelics[MAX_REWARD_RELICS]{};
    int pendingRelicCount = 0;
    bool pendingRelicClaimed[MAX_REWARD_RELICS]{};
    bool pendingCardReward = false;
    Card rewardCards[MAX_CARD_REWARDS][3]{};
    int rewardCardCounts[MAX_CARD_REWARDS]{};
    bool rewardCardPending[MAX_CARD_REWARDS]{};
    int activeCardReward = -1;
    bool rewardReturnToRewards = false;
    bool pendingReturnToEvent = false;
    bool lavaRockTriggered = false;
    RunScreen rewardResumeScreen = RunScreen::MAP;
    bool deferredCustomRewards = false;
    bool processingAction = false;

    // --- shop ---------------------------------------------------------------
    Card shopCards[MAX_SHOP_CARDS]{};
    int shopPrices[MAX_SHOP_CARDS]{};
    int shopBasePrices[MAX_SHOP_CARDS]{};
    bool shopSold[MAX_SHOP_CARDS]{};
    int shopCount = 0;
    int shopRelics[MAX_SHOP_RELICS]{};
    int shopRelicPrices[MAX_SHOP_RELICS]{};
    int shopRelicBasePrices[MAX_SHOP_RELICS]{};
    bool shopRelicSold[MAX_SHOP_RELICS]{};
    int shopRelicCount = 0;
    int shopPotions[MAX_SHOP_POTIONS]{};
    int shopPotionPrices[MAX_SHOP_POTIONS]{};
    int shopPotionBasePrices[MAX_SHOP_POTIONS]{};
    bool shopPotionSold[MAX_SHOP_POTIONS]{};
    int shopPotionCount = 0;
    bool removalUsed = false;
    int removalPrice = 75;
    int removalBasePrice = 75;
    int cardShopRemovalsUsed = 0;

    // --- events -------------------------------------------------------------
    std::int8_t eventId = -1;
    std::int8_t eventPage = 0;
    std::uint8_t eventCardSelection = 0;  // 1 upgrade, 2 Sown, 3 Vigorous
    RunCardGrid cardGrid;
    Card paelsToothCards[5]{};
    int paelsToothCount = 0;
    // Native awaits each obtain before starting the next. These acquisitions
    // are suspended while a previous relic is waiting for a deck choice.
    int pendingRelicObtains[MAX_RELICS]{};
    int pendingRelicObtainCount = 0;
    std::int8_t eventChoiceCount = 0;
    int eventData[4]{};
    int eventRelics[MAX_EVENT_CHOICES]{};
    bool eventCombat = false;         // current room is a combat inside an event
    std::int8_t eventReturnPage = 0;  // page to return to after event combat
    Rng eventRng;                    // persistent across pages of the active event

    // --- potions / relics ---------------------------------------------------
    int potions[MAX_POTIONS]{};
    int potionCount = 0;
    int potionSlots = BASE_POTION_SLOTS;

    int relics[MAX_RELICS]{};
    int relicCount = 0;
    int relicAux[MAX_RELICS]{};  // persistent run-level relic counters
    RelicBagState playerRelicBag;
    RelicBagState sharedRelicBag;
    bool relicBagsInitialized = false;

    // --- RNG streams and odds ----------------------------------------------
    Rng runRng[RNG_COUNT];
    Rng playerRng[PRNG_COUNT];
    float cardRarityOdds = -0.05f;   // rarity offset (grows by 0.01, rare resets)
    float potionRewardOdds = 0.4f;
    float unknownMonsterOdds = 0.1f;
    float unknownEliteOdds = -1.0f;
    float unknownTreasureOdds = 0.02f;
    float unknownShopOdds = 0.03f;

    // --- act room bags ------------------------------------------------------
    std::uint16_t normalBag[32]{};
    int normalBagN = 0;
    int normalBagPos = 0;
    std::uint16_t eliteBag[16]{};
    int eliteBagN = 0;
    int eliteBagPos = 0;
    int bossEncounter = -1;
    int secondBossEncounter = -1;
    std::uint16_t eventBag[64]{};
    int eventBagN = 0;
    int eventBagPos = 0;
    std::uint64_t visitedEvents = 0;  // persists across acts

    // --- event/ancient relic bookkeeping (pre-existing hooks) ---------------
    bool teaSetPending = false;
    int cardsAdded = 0;
    int nextCombatEnergy = 0;
    bool nextCombatUpgradeHand = false;
    int nextCombatDazed = 0;
    int emberTeaCombats = 0;
    int furCoatCombats = 0;
    int toyBoxCombats = 0;
    int wongoCombats = 0;
    int swordOfStoneWins = 0;
    int paelsWingSkips = 0;
    int silverCrucibleUses = 0;
    bool mawBankPurchased = false;
    bool treasureSkipped = false;
    int eventRelicsLegacy[3]{};

    // --- lifecycle ----------------------------------------------------------
    // Numeric input is the raw 64-bit RNG seed; strings use native canonicalization/hash.
    void init(std::uint64_t seedValue, int ascensionLevel);
    void init_seed(const std::string &seedText, int ascensionLevel);
    void init_with_context(std::uint64_t seedValue, int ascensionLevel, int firstAct,
                           const NativeProgressContext &progress);
    void init_seed_with_context(const std::string &seedText, int ascensionLevel, int firstAct,
                                const NativeProgressContext &progress);
    void init_relic_bags();

    bool add_card_to_deck(Card c);
    std::uint16_t allocate_card_uid();
    Card make_run_card(CardId id, bool upgraded);
    void add_potion(PotionId id);
    bool use_potion_out_of_combat(int idx);
    void sync_potions_from_battle();
    bool add_relic(RelicId id);
    void resume_pending_relic_obtains();
    void sync_relics_from_battle();
    void sync_stolen_cards();

    // --- progression --------------------------------------------------------
    void start_act(int actIndex);
    void apply_golden_compass();
    void begin_combat(Encounter enc);
    void finish_combat();
    void finish_room();
    void enter_map_point(int nodeIdx);
    void roll_card_reward(bool boss);
    bool queue_random_relic_reward(Rng &rng, bool shared = false);
    bool queue_relic_reward(Rarity rarity);
    bool queue_potion_rewards(int count);
    void queue_rest_site_rewards();
    bool queue_card_reward(Rarity fixedRarity, bool useBaseOdds, CardPool pool = CardPool::IRONCLAD);
    RelicId pull_relic(Rarity rarity, bool fromBack = false, bool shared = false,
                       const int *blacklist = nullptr, int blacklistCount = 0);
    void roll_shop();
    void roll_treasure();
    int roll_unknown_room_type();
    void roll_act_rooms();

    [[nodiscard]] std::vector<RunAction> legal_actions() const;
    [[nodiscard]] std::vector<int> available_map_nodes() const;
    bool step(const RunAction &action);
    bool step_combat(const Action &action);

    [[nodiscard]] bool is_over() const { return screen == RunScreen::RUN_OVER; }
    [[nodiscard]] int alive_floor() const { return floor; }
    [[nodiscard]] int current_point_type() const;

    // --- training API -------------------------------------------------------
    [[nodiscard]] std::string serialize() const;
    static bool restore(const std::string &blob, RunContext &out);
    [[nodiscard]] std::uint64_t state_hash() const;
    [[nodiscard]] double terminal_reward() const;
};

const char *room_name(RoomType r);

// --- events (events.cpp) ----------------------------------------------------
constexpr int MAX_EVENTS = 64;
enum class EventStatus : std::uint8_t { IMPLEMENTED, APPROXIMATE, UNSUPPORTED };
struct EventInfo {
    const char *name;
    EventStatus status;
    int act;  // -1 shared, 0..2 act-specific, 3 ancient
};
const EventInfo *event_info(int id);
int event_pool_for_act_type(ActType actType, int *out, int maxOut);
int event_count();
bool event_is_allowed(const RunContext &rc, int id);
int event_pool_for_act(int act, int *out, int maxOut);  // implemented-only ids
int event_ancient_for_act(int act);  // legacy: act 1 -> Neow
int event_ancient_for_act(const RunContext &rc);
void event_plan_shared_ancients(RunContext &rc);
int event_pick_ancient(RunContext &rc);
void event_begin(RunContext &rc, int eventId, bool ancient);
int event_option_count(const RunContext &rc);
bool event_option_available(const RunContext &rc, int option);
bool event_choose(RunContext &rc, int option);
bool event_card_selectable(const RunContext &rc, int index);
bool event_card_selection_valid(const RunContext &rc);
bool event_select_card(RunContext &rc, int index);
bool event_can_remove_potions(const RunContext &rc);
void event_finish_card_grid(RunContext &rc);
void event_resume_after_combat(RunContext &rc);

}  // namespace sts2
