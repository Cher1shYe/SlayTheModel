// Full-run state for a standard A0 Ironclad climb (STS2 v0.111.0 contract).
#pragma once

#include <string>
#include <vector>

#include "sts2/battle.h"
#include "sts2/map.h"

namespace sts2 {

enum class RoomType : std::uint8_t { MONSTER, ELITE, EVENT, REST, SHOP, TREASURE, BOSS };
enum class RunScreen : std::uint8_t {
    MAP, COMBAT, CARD_REWARD, REST, SHOP, EVENT, TREASURE, RUN_OVER
};
enum class RunActionType : std::uint8_t {
    MOVE, TAKE_CARD, SKIP_CARD, REST_HEAL, REST_UPGRADE, REST_DIG, REST_LIFT,
    BUY_CARD, BUY_RELIC, BUY_POTION, REMOVE_CARD, LEAVE_SHOP,
    EVENT_CHOICE, COLLECT, USE_POTION
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

struct RunContext {
    // --- identity -----------------------------------------------------------
    std::uint32_t seed = 0;
    int ascension = 0;

    // --- progression --------------------------------------------------------
    int hp = 80;
    int maxHp = 80;
    int gold = 99;
    int act = 0;        // 0..2
    int actFloor = 0;   // 1-based row within the act (Ancient == 1)
    int floor = 0;      // total floors entered
    bool won = false;

    ActMap map;
    std::int8_t curRow = -1;
    std::int8_t curCol = -1;
    std::uint64_t visitedLo = 0;
    std::uint64_t visitedHi = 0;
    std::int8_t lastPointType = 0;

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

    // --- screens ------------------------------------------------------------
    RunScreen screen = RunScreen::MAP;
    Card offered[3]{};
    int offeredCount = 0;
    bool rewardIsBoss = false;

    // --- shop ---------------------------------------------------------------
    Card shopCards[MAX_SHOP_CARDS]{};
    int shopPrices[MAX_SHOP_CARDS]{};
    bool shopSold[MAX_SHOP_CARDS]{};
    int shopCount = 0;
    int shopRelics[MAX_SHOP_RELICS]{};
    int shopRelicPrices[MAX_SHOP_RELICS]{};
    bool shopRelicSold[MAX_SHOP_RELICS]{};
    int shopRelicCount = 0;
    int shopPotions[MAX_SHOP_POTIONS]{};
    int shopPotionPrices[MAX_SHOP_POTIONS]{};
    bool shopPotionSold[MAX_SHOP_POTIONS]{};
    int shopPotionCount = 0;
    bool removalUsed = false;
    int removalPrice = 75;
    int cardShopRemovalsUsed = 0;

    // --- events -------------------------------------------------------------
    std::int8_t eventId = -1;
    std::int8_t eventPage = 0;
    std::int8_t eventChoiceCount = 0;
    int eventData[4]{};
    int eventRelics[MAX_EVENT_CHOICES]{};
    bool eventCombat = false;         // current room is a combat inside an event
    std::int8_t eventReturnPage = 0;  // page to return to after event combat

    // --- potions / relics ---------------------------------------------------
    int potions[MAX_POTIONS]{};
    int potionCount = 0;
    int potionSlots = BASE_POTION_SLOTS;

    int relics[MAX_RELICS]{};
    int relicCount = 0;
    int relicAux[MAX_RELICS]{};  // persistent run-level relic counters

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
    std::uint16_t eventBag[64]{};
    int eventBagN = 0;
    int eventBagPos = 0;

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
    void init(std::uint32_t seedValue, int ascensionLevel);

    void add_card_to_deck(Card c);
    Card make_run_card(CardId id, bool upgraded);
    void add_potion(PotionId id);
    bool use_potion_out_of_combat(int idx);
    void sync_potions_from_battle();
    bool add_relic(RelicId id);
    void sync_relics_from_battle();

    // --- progression --------------------------------------------------------
    void start_act(int actIndex);
    void begin_combat(Encounter enc);
    void finish_combat();
    void finish_room();
    void enter_map_point(int nodeIdx);
    void roll_card_reward(bool boss);
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

bool card_upgradable(const Card &c);
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
int event_count();
int event_pool_for_act(int act, int *out, int maxOut);  // implemented-only ids
int event_ancient_for_act(int act);
void event_begin(RunContext &rc, int eventId, bool ancient);
int event_option_count(const RunContext &rc);
bool event_option_available(const RunContext &rc, int option);
bool event_choose(RunContext &rc, int option);
void event_resume_after_combat(RunContext &rc);

}  // namespace sts2
