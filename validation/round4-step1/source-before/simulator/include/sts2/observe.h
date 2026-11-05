#pragma once

#include "sts2/run.h"

namespace sts2 {

// Legacy compact observations (kept for the original nets/checkpoints).
constexpr int RUN_OBS_DIM = 7 + 8 + static_cast<int>(CardId::COUNT);
// + cost, type x5, rarity x5, upgraded, price, hasPrice, replay, bonusReplay,
// freeCombat, costThisTurn, galvanized, combat damage/keywords and cost state.
constexpr int CARD_FEAT_DIM = static_cast<int>(CardId::COUNT) + 28;
constexpr int COMBAT_OBS_DIM = 21 + MAX_MONSTERS * 10;

// Versioned public schema.  Anything a player can see is encoded; RNG state,
// draw order and future intents are not.  Bump both versions when the layout
// changes and keep old checkpoints loadable only by their matching version.
constexpr int PUBLIC_OBS_VERSION = 12;
constexpr int ACTION_SCHEMA_VERSION = 11;
constexpr int PUB_CARD_INSTANCE_FEAT = 17;

constexpr int PUB_BASE = 38;
constexpr int PUB_SCREENS = 9;
constexpr int PUB_MAP_FEAT = 15;  // present, type x9, row, col, reachable, visited, childCount
constexpr int PUB_EVENT_N = 64;   // event-id space (ids are contiguous and < 64)
constexpr int PUB_EVENT_CHOICES = 4;
constexpr int PUB_EVENT_FEAT = 6;
constexpr int PUB_CARD_REWARD_N = 3;
constexpr int PUB_SHOP_META = 4;
constexpr int RELIC_COUNT = static_cast<int>(RelicId::COUNT);
constexpr int POTION_COUNT = static_cast<int>(PotionId::COUNT);
constexpr int MONSTER_COUNT = static_cast<int>(MonsterId::COUNT);
constexpr int POWER_COUNT = static_cast<int>(PowerId::COUNT);
constexpr int PUB_REWARD_META = 4 + POTION_COUNT + MAX_REWARD_RELICS * (2 + RELIC_COUNT) +
    MAX_REWARD_POTIONS + MAX_CARD_REWARDS + 1 + PUB_SCREENS + 1;

// v12 appends NotYet to the card vocabulary; v11 added this tail and the
// encounter identity. Old checkpoints require a reviewed layout migration.
constexpr int PUB_RUN_BOSS_OFFSET = PUB_BASE + PUB_SCREENS +
    static_cast<int>(CardId::COUNT) + 6 * MAX_DECK +
    24 + 8 * CARD_FEAT_DIM + MAX_DECK + 2 * RELIC_COUNT + POTION_COUNT + MAX_POTIONS;
constexpr int PUB_RUN_EXTENSION = 3 * 4 + 4 + 1 + 8 + static_cast<int>(Encounter::COUNT) +
    1 + 5 * PUB_CARD_INSTANCE_FEAT + 1 + MAX_RELICS + MAX_PILE;
constexpr int PUBLIC_RUN_DIM =
    PUB_BASE + PUB_SCREENS + static_cast<int>(CardId::COUNT) + 6 * MAX_DECK + 2 * RELIC_COUNT +
    POTION_COUNT + MAX_POTIONS + MAP_MAX_POINTS * PUB_MAP_FEAT + PUB_EVENT_N +
    PUB_EVENT_CHOICES * (PUB_EVENT_FEAT + RELIC_COUNT) + 4 +
    PUB_CARD_REWARD_N * CARD_FEAT_DIM + MAX_SHOP_CARDS * (CARD_FEAT_DIM + 2) +
    MAX_SHOP_RELICS * (RELIC_COUNT + 2) + MAX_SHOP_POTIONS * (POTION_COUNT + 2) + PUB_SHOP_META +
    PUB_REWARD_META + 2 * static_cast<int>(Encounter::COUNT) + 1 + MAX_PILE * 18 +
    24 + 8 * CARD_FEAT_DIM + MAX_DECK + PUB_RUN_EXTENSION;

// Visible per-turn counters (Panache cycles every 5 plays, Letter Opener every
// 3 skills) and known-top / Bomb state are part of the player's information.
// Player/history scalars, active play, powers, Automation and Toric instances.
constexpr int PUB_COMBAT_BASE =
    14 + 3 + 2 + 1 + BattleContext::MAX_AUTOMATION * 2 + POWER_COUNT +
    12 + 11 + CARD_FEAT_DIM + 1 + MAX_PILE * 2 + 2 + MAX_PILE * 4 + 1 + MAX_PILE * 18;
// Ordered identities of known top cards.  The capacity is explicit: a player
// can know more than 16 cards only through unusual innate/stacked effects; the
// count is always exposed and the first 16 use one-hot identities; remaining
// known cards use an identity scalar and upgrade flag. Bombs have no rule
// limit (TheBombPower.IsInstanced), so every stored instance gets a slot.
constexpr int PUB_KNOWN_TOP = 16;
constexpr int PUB_BOMB_SLOTS = MAX_PILE;
constexpr int PUB_COMBAT_EXTRA =
    1 + PUB_KNOWN_TOP * (static_cast<int>(CardId::COUNT) + 1) +
    (MAX_PILE - PUB_KNOWN_TOP) * 2 + MAX_PILE * PUB_CARD_INSTANCE_FEAT + 1 + PUB_BOMB_SLOTS * 2;
constexpr int PUB_HAND_FEAT = CARD_FEAT_DIM + 2;  // + playable, effective cost
constexpr int PUB_MON_FEAT = 1 + MONSTER_COUNT + 12 + POWER_COUNT + 4 + 9 + 1 + MAX_PILE;
constexpr int PUB_CHOICE_OP_N = static_cast<int>(ChoiceOp::DISCARD_ANY) + 1;
constexpr int PUB_CHOICE_PILE_N = 5;   // ChoicePile discriminants
// Combat relics (identity + counter) and potions are visible in combat.
constexpr int PUB_COMBAT_META = 2 * RELIC_COUNT + POTION_COUNT + MAX_POTIONS;
// Candidates can fill a whole pile.  Duplicates with the same identity are
// interchangeable, so the candidate set is encoded as three per-card bags
// (base / upgraded / temporarily cheaper) instead of one slot per card; the
// operation and source pile below distinguish e.g. "upgrade" from "exhaust".
constexpr int PUB_PENDING_BAGS = 3;
constexpr int PUB_PENDING_INSTANCE_FEAT = PUB_CARD_INSTANCE_FEAT;
constexpr int PUB_PENDING_FEAT =
    1 + PUB_PENDING_BAGS * static_cast<int>(CardId::COUNT) + 4 + PUB_CHOICE_OP_N +
    PUB_CHOICE_PILE_N + (1 + 1 + static_cast<int>(CardId::COUNT)) +
    MAX_PILE * PUB_PENDING_INSTANCE_FEAT;
// Visible piles are encoded per identity with a base/upgraded split (the card's
// upgrade state is visible in the pile viewer; the order is not).
constexpr int PUBLIC_COMBAT_OBS_DIM =
    PUB_COMBAT_BASE + MAX_HAND * PUB_HAND_FEAT + 4 + 6 * static_cast<int>(CardId::COUNT) +
    3 * MAX_PILE * PUB_CARD_INSTANCE_FEAT + PUB_COMBAT_EXTRA + MAX_MONSTERS * PUB_MON_FEAT +
    PUB_COMBAT_META + PUB_PENDING_FEAT + 1 + MAX_PILE;
constexpr int PUBLIC_OBS_DIM = PUBLIC_RUN_DIM + PUBLIC_COMBAT_OBS_DIM;

constexpr int ACTION_FEAT_DIM =
    5 + static_cast<int>(CardId::COUNT) + POTION_COUNT + 30 + PUB_CHOICE_OP_N +
    PUB_CHOICE_PILE_N + 2;

std::vector<float> run_observation(const RunContext &rc);
std::vector<float> card_features(const Card &c, int price = -1);
std::vector<float> combat_observation(const BattleContext &bc);
std::vector<float> combat_action_features(const BattleContext &bc, const Action &a);

// Versioned public observations.
std::vector<float> public_combat_observation(const BattleContext &bc);
std::vector<float> public_observation(const RunContext &rc);

}  // namespace sts2
