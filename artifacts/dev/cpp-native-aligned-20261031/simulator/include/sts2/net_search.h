#pragma once
// Resumable hidden-information PUCT search whose priors and leaf values come from
// an external network, evaluated in batches by the caller:
//
//   NetSearch s(root, simulations, seed, cfg);
//   while (s.advance()) {                 // stops at a leaf that needs the network
//       obs = combat_entity_observation(s.pending_state());
//       s.provide(priors_over_pending_legal_actions, value);
//   }
//   s.root_visits(); s.best_action();
//
// Every simulation resamples the hidden state at the root (as play_combat_mcts
// does) and nodes are keyed by the public observation and visible legal-action
// features, so the tree never conditions on hidden information. Each node is
// evaluated once, from the determinization that first reached it (its public
// observation is the same for every determinization reaching it). Terminal
// states use combat_terminal_value(); there are no random rollouts.
#include "sts2/battle.h"

#include <cstdint>
#include <map>
#include <memory>
#include <vector>

namespace sts2 {

struct NetSearchConfig {
    double cPuct = 1.5;
    double fpuReduction = 0.2;     // unvisited edge Q = parent mean - this
    double dirichletAlpha = 0.3;   // root noise (only when dirichletFrac > 0)
    double dirichletFrac = 0.0;
    double potionWeight = 4.0;     // a kept potion is worth this many HP
    double winBase = 0.4;          // value of winning at 0 HP (death = 0, full HP = 1)
    bool resampleHidden = true;
    // 2026-11-16 (unified net, off by default = previous behaviour):
    // normalizeQ: select with Q rescaled to [0, 1] by the min / max value backed up in this
    // tree (MuZero), so small value differences inside one fight still guide the search.
    bool normalizeQ = false;
    // evalTerminalWins: a won fight is a leaf the caller evaluates (provide with no priors),
    // instead of combat_terminal_value(); a lost fight is still worth 0.
    bool evalTerminalWins = false;
};

// Combat value of a finished battle: 0 on defeat, otherwise
// winBase + (1 - winBase) * (hp + potionWeight * potions) / maxHp.
double combat_terminal_value(const BattleContext &bc, double winBase, double potionWeight);

class NetSearch {
public:
    NetSearch(const BattleContext &root, int simulations, std::uint32_t seed, const NetSearchConfig &cfg);
    ~NetSearch();
    NetSearch(const NetSearch &) = delete;
    NetSearch &operator=(const NetSearch &) = delete;

    // Runs simulations until a node needs an evaluation (true) or the budget is spent (false).
    bool advance();
    bool waiting() const;
    const BattleContext &pending_state() const;
    // Priors over pending_state().legal_actions() (in that order) and the value of the state.
    void provide(const std::vector<double> &priors, double value);

    int simulations_done() const;
    const std::vector<Action> &root_actions() const;
    std::vector<int> root_visits() const;     // in root_actions() order
    std::vector<double> root_q() const;       // mean value per root action (NaN if unvisited)
    std::vector<double> root_priors() const;
    double root_value() const;                // network value of the root (after the first provide)
    Action best_action() const;               // most visited root action (ties: higher prior)

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace sts2
