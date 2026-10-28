#pragma once

#include "sts2/run.h"

namespace sts2 {

constexpr int RUN_OBS_DIM = 7 + 8 + static_cast<int>(CardId::COUNT);
constexpr int CARD_FEAT_DIM = static_cast<int>(CardId::COUNT) + 14;
constexpr int COMBAT_OBS_DIM = 21 + MAX_MONSTERS * 10;
constexpr int ACTION_FEAT_DIM = 4 + static_cast<int>(CardId::COUNT) + 7;

std::vector<float> run_observation(const RunContext &rc);
std::vector<float> card_features(const Card &c, int price = -1);
std::vector<float> combat_observation(const BattleContext &bc);
std::vector<float> combat_action_features(const BattleContext &bc, const Action &a);

}  // namespace sts2
