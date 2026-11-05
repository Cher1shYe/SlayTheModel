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
    SELECT_GRID_CARD, CONFIRM_GRID_CARDS, CANCEL_GRID_PREVIEW, REST_CLONE, REST_HATCH,
    REST_COOK, CRYSTAL_DIVINE, REROLL_CARD_REWARD,
    // MiniatureTent keeps the rest site open after an option is used, so the
    // visit needs an explicit leave action; every other rest site closes
    // automatically after its single option.
    REST_LEAVE
};

struct RunAction {
    RunActionType type = RunActionType::MOVE;
    int index = 0;
};

// Training/evaluation content profile. The default (ORIGINAL) is the complete
// native content set; SINGLE_PLAYER_TRAINING removes only content that cannot
// occur in a single-player Ironclad run so a simulated run never reaches an
// unsupported interactive event. It changes the native content distribution
// (one event is missing from the generated pool); every filter is applied when
// the pool is built, never by drawing an excluded entry and silently skipping.
enum class RunContentProfile : std::uint8_t {
    ORIGINAL = 0,
    // Excludes the CrystalSphere event (interactive mini-game outside the
    // current support scope). Multiplayer-only cards are already excluded from
    // every generation entry point in both profiles.
    SINGLE_PLAYER_TRAINING = 1,
};
constexpr int RUN_CONTENT_PROFILE_COUNT = 2;
const char *run_content_profile_name(RunContentProfile profile);

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
    // Native character unlock order: Ironclad, Silent, Regent, Necrobinder, Defect.
    std::uint8_t unlockedCharacterMask = 31;
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
    // Raw snapshots hash the object image and trivially-copyable assignment
    // copies the whole object, so stack padding must be deterministic.
    RunCardGrid() {
        std::memset(static_cast<void *>(this), 0, sizeof(*this));
        for (int &slot : orderSlots) slot = -1;
        for (int &slot : freeNext) slot = -1;
        freeHead = -1;
    }
    std::uint8_t kind = 0; // 1 Brain Leech, 2 Cheese, 3 Claws, 4 Pael's Growth, 5 Scroll Boxes;
                           // 6 remove, 7 transform, 8 transform+upgrade, 9 upgrade,
                           // 10 Pael's Tooth, 11 Spiral, 12 Steady enchantment
    Card cards[15]{};
    int count = 0;
    bool selected[MAX_DECK]{};
    int selectedCount = 0;
    int minSelect = 0;
    int maxSelect = 0;
    bool preview = false;
    int orderSlots[15] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
    int freeNext[15] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
    int slotCount = 0;
    int freeHead = -1;
    int damageAfterSelection = 0;
    CardId curseAfterSelection = CardId::INVALID;
};

struct RunContext {
    // --- identity -----------------------------------------------------------
    std::uint64_t seed = 0;
    int ascension = 0;
    // Single-player character. Selects the starting deck/relic, reward and shop
    // card pool, potion pool and relic bag. Ironclad remains the default so
    // existing callers and checkpoints keep their established behaviour.
    CardPool character = CardPool::IRONCLAD;
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
    // LastingCandy adds a fourth power-card option to every other combat card
    // reward; native CardReward option lists are not fixed at three.
    Card offered[4]{};
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
    bool pendingRelicWax[MAX_REWARD_RELICS]{};
    // NeowsBones uses RewardsSet.WithSkippingDisallowed: its own two relic
    // rewards cannot be skipped. Rewards they create (e.g. Small Capsule's
    // replacement relic) remain optional, so this is per offered relic.
    bool pendingRelicRequired[MAX_REWARD_RELICS]{};
    bool pendingCardReward = false;
    Card rewardCards[MAX_CARD_REWARDS][4]{};
    int rewardCardCounts[MAX_CARD_REWARDS]{};
    // Reroll support (Driftwood): remembers how each reward slot was generated
    // so Reroll() can repopulate it with the same options and RNG streams.
    bool rewardCardCanReroll[MAX_CARD_REWARDS]{};
    bool rewardCardCombat[MAX_CARD_REWARDS]{};
    std::uint8_t rewardCardRerollMode[MAX_CARD_REWARDS]{};  // 0 fixed, 1 regular, 2 elite, 3 boss
    std::uint8_t rewardCardRerollRarity[MAX_CARD_REWARDS]{};
    std::uint8_t rewardCardRerollPool[MAX_CARD_REWARDS]{};
    bool rewardCardRerollBaseOdds[MAX_CARD_REWARDS]{};
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
    // FakeMerchant event inventory: six custom relic entries (not the normal
    // three-slot shop). Prices are rolled from PlayerRng.Shops on creation.
    static constexpr int FAKE_MERCHANT_RELICS = 6;
    int fakeMerchantRelics[FAKE_MERCHANT_RELICS]{};
    int fakeMerchantPrices[FAKE_MERCHANT_RELICS]{};
    bool fakeMerchantSold[FAKE_MERCHANT_RELICS]{};

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
    bool pendingRelicObtainWax[MAX_RELICS]{};
    int pendingRelicObtainCount = 0;
    std::int8_t eventChoiceCount = 0;
    int eventData[4]{};
    int eventRelics[MAX_EVENT_CHOICES]{};
    CardPool preparedSeaGlassPool = CardPool::IRONCLAD;
    CardId preparedDustyTomeCard = CardId::INVALID;
    bool eventCombat = false;         // current room is a combat inside an event
    std::int8_t eventReturnPage = 0;  // page to return to after event combat
    Rng eventRng;                    // persistent across pages of the active event

    // --- CrystalSphere minigame ---------------------------------------------
    // 11x11 fog grid; item positions/types are visible in the native UI, the
    // hidden mask is what divination clears. Items are placed on hidden cells
    // only, in the native PopulateItems order.
    static constexpr int CRYSTAL_GRID_W = 11;
    static constexpr int CRYSTAL_GRID_H = 11;
    // One full PopulateItems pass is 15 items. The native retry loop can in
    // principle append more after a partial placement failure; the bounded
    // port stops after the first complete pass instead (grid has 121 cells for
    // 51 occupied, so the failure path is unreachable in practice).
    static constexpr int CRYSTAL_MAX_ITEMS = 15;
    struct CrystalItemState {
        std::uint8_t type = 0;      // CrystalSphereItemType ordering below
        std::uint8_t x = 255;       // 255 = placement failed (never reveals)
        std::uint8_t y = 255;
        bool placed = false;
        bool revealed = false;
    };
    std::uint8_t crystalHidden[CRYSTAL_GRID_W * CRYSTAL_GRID_H]{};
    std::int16_t crystalCellItem[CRYSTAL_GRID_W * CRYSTAL_GRID_H]{};
    CrystalItemState crystalItems[CRYSTAL_MAX_ITEMS]{};
    std::uint8_t crystalItemCount = 0;
    std::uint8_t crystalDivinations = 0;
    std::uint8_t crystalTool = 1;  // 1 = Big (3x3), 0 = Small (single cell)
    std::uint8_t crystalRevealed[CRYSTAL_MAX_ITEMS]{};
    std::uint8_t crystalRevealedCount = 0;

    // --- potions / relics ---------------------------------------------------
    int potions[MAX_POTIONS]{};
    int potionCount = 0;
    int potionSlots = BASE_POTION_SLOTS;

    int relics[MAX_RELICS]{};
    int relicCount = 0;
    int relicAux[MAX_RELICS]{};  // persistent run-level relic counters
    bool relicWax[MAX_RELICS]{};
    bool relicMelted[MAX_RELICS]{};
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
    int largeCapsuleRelicsRemaining = 0;
    bool largeCapsuleCardsPending = false;
    int wongoCombats = 0;
    int swordOfStoneWins = 0;
    int paelsWingSkips = 0;
    int silverCrucibleUses = 0;
    bool mawBankPurchased = false;
    bool treasureSkipped = false;
    int eventRelicsLegacy[3]{};

    // --- content profile ----------------------------------------------------
    RunContentProfile contentProfile = RunContentProfile::ORIGINAL;

    // --- lifecycle ----------------------------------------------------------
    // Numeric input is the raw 64-bit RNG seed; strings use native canonicalization/hash.
    void init(std::uint64_t seedValue, int ascensionLevel,
              CardPool character = CardPool::IRONCLAD,
              RunContentProfile profile = RunContentProfile::ORIGINAL);
    void init_seed(const std::string &seedText, int ascensionLevel,
                   CardPool character = CardPool::IRONCLAD,
                   RunContentProfile profile = RunContentProfile::ORIGINAL);
    void init_with_context(std::uint64_t seedValue, int ascensionLevel, int firstAct,
                           const NativeProgressContext &progress,
                           CardPool character = CardPool::IRONCLAD,
                           RunContentProfile profile = RunContentProfile::ORIGINAL);
    void init_seed_with_context(const std::string &seedText, int ascensionLevel, int firstAct,
                                const NativeProgressContext &progress,
                                CardPool character = CardPool::IRONCLAD,
                                RunContentProfile profile = RunContentProfile::ORIGINAL);
    void init_relic_bags();

    bool add_card_to_deck(Card c);
    std::uint16_t allocate_card_uid();
    Card make_run_card(CardId id, bool upgraded);
    void add_potion(PotionId id);
    bool use_potion_out_of_combat(int idx);
    void sync_potions_from_battle();
    bool add_relic(RelicId id, bool wax = false);
    bool remove_relic(int index);
    bool replace_starter_relic(int index, RelicId replacement);
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
    bool queue_random_relic_reward(Rng &rng, bool shared = false, bool wax = false);
    bool queue_exact_relic_reward(RelicId id, bool wax = false, bool required = false);
    bool queue_relic_reward(Rarity rarity);
    bool queue_potion_rewards(int count);
    void queue_rest_site_rewards();
    bool queue_card_reward(Rarity fixedRarity, bool useBaseOdds, CardPool pool = CardPool::IRONCLAD);
    // A CardReward generated through CardCreationOptions.ForRoom: `boss` is
    // 100% rare, `elite` switches the encounter rarity table. Used by Orrery
    // and White Star, whose native rewards are not fixed-rarity lists.
    bool queue_encounter_card_reward(bool elite, bool boss, int optionCount = 3);
    // Applies relic hooks that modify the freshly rolled combat card reward
    // options in `offered`.
    void apply_combat_card_reward_relics();
    // Driftwood's CardReward.Reroll: repopulates one pending reward slot.
    bool reroll_card_reward(int slot);
    RelicId pull_relic(Rarity rarity, bool fromBack = false, bool shared = false,
                       const int *blacklist = nullptr, int blacklistCount = 0,
                       bool shopsOnly = false);
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
// Content-profile gate applied while an act's event bag is built. Kept
// separate from event_allowed_now (which mirrors the native IsAllowed) so the
// profile's deviation from native content stays explicit.
bool event_allowed_by_profile(RunContentProfile profile, int id);
int event_pool_for_act(int act, int *out, int maxOut);  // implemented-only ids
int event_ancient_for_act(int act);  // legacy: act 1 -> Neow
int event_ancient_for_act(const RunContext &rc);
// RelicModel.IsAllowedAtNeow for the Neow option pool (single-player rules).
bool neow_relic_allowed(const RunContext &rc, RelicId id);
// Neow.AllPossibleOptions in native declaration order, filtered by
// IsAllowedAtNeow. excludeBones implements NeowsBones.GetValidRelics.
int neow_relic_options(const RunContext &rc, RelicId *out, int capacity, bool excludeBones);
void event_plan_shared_ancients(RunContext &rc);
int event_pick_ancient(RunContext &rc);
void event_begin(RunContext &rc, int eventId, bool ancient);
// LanternKey.ModifyNextEvent forces WarHistorianRepy on the next event.
int event_war_historian_repy_id();
int event_option_count(const RunContext &rc);
bool event_option_available(const RunContext &rc, int option);
bool event_choose(RunContext &rc, int option);
bool event_card_selectable(const RunContext &rc, int index);
bool event_card_selection_valid(const RunContext &rc);
bool event_select_card(RunContext &rc, int index);
bool event_can_remove_potions(const RunContext &rc);
void event_finish_card_grid(RunContext &rc);
// EncounterModel.ShouldGiveRewards: every event encounter except the
// BattlewornDummy variants keeps the room's normal monster rewards, and
// CombatRoom.ExtraRewards are appended after them.
bool event_combat_gives_standard_rewards(const RunContext &rc);
void event_combat_extra_rewards(RunContext &rc);
void event_resume_after_combat(RunContext &rc);
// FakeMerchant's custom inventory: purchase one stocked entry, or throw a
// FoulPotion to start the event combat.
bool event_is_fake_merchant(const RunContext &rc);
bool event_fake_merchant_buy(RunContext &rc, int index);
bool event_fake_merchant_throw(RunContext &rc);
// CrystalSphere divination: index = cell * 2 + tool (0 small, 1 big).
bool event_crystal_active(const RunContext &rc);
bool event_crystal_divine(RunContext &rc, int index);

}  // namespace sts2
