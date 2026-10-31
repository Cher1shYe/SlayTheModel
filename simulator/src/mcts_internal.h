#pragma once

#include <cmath>

namespace sts2 { struct BattleContext; }
namespace sts2::detail {

// Per-search reward for remaining potions, exposed internally for regression tests.
double mcts_terminal_score(const BattleContext &bc, double potion_weight);

// STS1 normalizes the accumulated edge value by the global score range.
// Equal scores have no useful exploitation signal: use zero instead of
// amplifying a nearly-zero divisor or producing NaN.
inline double mcts_quality(double sum, int visits, double best, double worst) {
    const double range = best - worst;
    return std::isfinite(range) && range > 1e-9
        ? (sum / (visits + 1.0)) / range : 0.0;
}

}  // namespace sts2::detail
