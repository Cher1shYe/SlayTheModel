#pragma once

#include "sts2/battle.h"
#include <functional>

namespace sts2 {

struct SearchResult {
    std::vector<Action> actions;
    std::vector<int> visits;
    std::vector<double> values;
    int simulations = 0;
};

struct MctsResult {
    std::vector<Action> actions;
    int simulations = 0;
    bool victory = false;
};

Action greedy_action(const BattleContext &bc, Rng &rng, double epsilon = 0.0);
double rollout(BattleContext &bc, Rng &rng, double epsilon = 0.05, int maxSteps = 500);
SearchResult search(const BattleContext &root, int simulations, double c = 1.5,
                    double epsilon = 0.05, std::uint32_t seed = 0,
                    bool resample_hidden = false);
SearchResult search_priors(const BattleContext &root, int simulations,
                           const std::vector<double> &priors, double c = 1.5,
                           double epsilon = 0.05, std::uint32_t seed = 0,
                           bool resample_hidden = false);
MctsResult mcts(const BattleContext &root, int simulations, double c = 4.242640687,
                std::uint32_t seed = 0, bool resample_hidden = false,
                bool greedy_rollout = false, double epsilon = 0.05);

// Root-only PUCT: expected_actions and priors are paired with the current
// legal actions. The remaining tree uses the same UCB rule as mcts().
MctsResult mcts_priors(const BattleContext &root, int simulations,
                       const std::vector<Action> &expected_actions,
                       const std::vector<double> &priors, double c_puct = 3.0,
                       std::uint32_t seed = 0, bool resample_hidden = false,
                       bool greedy_rollout = false, double epsilon = 0.05);

// Fresh priors for each newly expanded node in the first max_depth levels.
// The callback sees the current battle and its legal actions in order.
// With resampling enabled, nodes are keyed by public observation and legal
// action features, so priors are never shared across different public states.
using MctsPriorFn = std::function<std::vector<double>(const BattleContext &, const std::vector<Action> &)>;
using MctsValueFn = std::function<double(const BattleContext &)>;
MctsResult mcts_depth_priors(const BattleContext &root, int simulations,
                             const MctsPriorFn &prior_fn, int max_depth,
                             double c_puct = 3.0, std::uint32_t seed = 0,
                             bool greedy_rollout = false, double epsilon = 0.05,
                             bool resample_hidden = false,
                             const MctsValueFn *value_fn = nullptr);

}  // namespace sts2
