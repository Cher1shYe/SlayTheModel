#pragma once

#include "sts2/battle.h"

namespace sts2 {

struct SearchResult {
    std::vector<Action> actions;
    std::vector<int> visits;
    std::vector<double> values;
    int simulations = 0;
};

Action greedy_action(const BattleContext &bc, Rng &rng, double epsilon = 0.0);
double rollout(BattleContext &bc, Rng &rng, double epsilon = 0.05, int maxSteps = 500);
SearchResult search(const BattleContext &root, int simulations, double c = 1.5,
                    double epsilon = 0.05, std::uint32_t seed = 0);
SearchResult search_priors(const BattleContext &root, int simulations,
                           const std::vector<double> &priors, double c = 1.5,
                           double epsilon = 0.05, std::uint32_t seed = 0);

}  // namespace sts2
