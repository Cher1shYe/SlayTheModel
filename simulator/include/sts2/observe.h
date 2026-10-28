#pragma once

#include "sts2/run.h"

namespace sts2 {

// Legacy compact observations (kept for the original nets/checkpoints).
constexpr int RUN_OBS_DIM = 7 + 8 + static_cast<int>(CardId::COUNT);
constexpr int CARD_FEAT_DIM = static_cast<int>(CardId::COUNT) + 14;
constexpr int COMBAT_OBS_DIM = 21 + MAX_MONSTERS * 10;

// Versioned public schema.  Anything a player can see is encoded; RNG state,
// draw order and future intents are not.  Bump both versions when the layout
// changes and keep old checkpoints loadable only by their matching version.
constexpr int PUBLIC_OBS_VERSION = 3;
constexpr int ACTION_SCHEMA_VERSION = 2;

constexpr int PUB_BASE = 20;
constexpr int PUB_SCREENS = 8;
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

constexpr int PUBLIC_RUN_DIM =
    PUB_BASE + PUB_SCREENS + static_cast<int>(CardId::COUNT) + 2 * RELIC_COUNT +
    POTION_COUNT + MAP_MAX_POINTS * PUB_MAP_FEAT + PUB_EVENT_N +
    PUB_EVENT_CHOICES * (PUB_EVENT_FEAT + RELIC_COUNT) + 4 +
    PUB_CARD_REWARD_N * CARD_FEAT_DIM + MAX_SHOP_CARDS * (CARD_FEAT_DIM + 2) +
    MAX_SHOP_RELICS * (RELIC_COUNT + 2) + MAX_SHOP_POTIONS * (POTION_COUNT + 2) + PUB_SHOP_META;

constexpr int PUB_COMBAT_BASE = 12 + POWER_COUNT;
constexpr int PUB_HAND_FEAT = CARD_FEAT_DIM + 2;  // + playable, effective cost
constexpr int PUB_MON_FEAT = 1 + MONSTER_COUNT + 11 + POWER_COUNT + 4;
constexpr int PUB_PENDING_FEAT = 1 + MAX_HAND * (CARD_FEAT_DIM + 1) + 4;
constexpr int PUBLIC_COMBAT_OBS_DIM =
    PUB_COMBAT_BASE + MAX_HAND * PUB_HAND_FEAT + 4 + 3 * static_cast<int>(CardId::COUNT) +
    MAX_MONSTERS * PUB_MON_FEAT + PUB_PENDING_FEAT;
constexpr int PUBLIC_OBS_DIM = PUBLIC_RUN_DIM + PUBLIC_COMBAT_OBS_DIM;

constexpr int ACTION_FEAT_DIM = 5 + static_cast<int>(CardId::COUNT) + POTION_COUNT + 12;

std::vector<float> run_observation(const RunContext &rc);
std::vector<float> card_features(const Card &c, int price = -1);
std::vector<float> combat_observation(const BattleContext &bc);
std::vector<float> combat_action_features(const BattleContext &bc, const Action &a);

// Versioned public observations.
std::vector<float> public_combat_observation(const BattleContext &bc);
std::vector<float> public_observation(const RunContext &rc);

}  // namespace sts2
