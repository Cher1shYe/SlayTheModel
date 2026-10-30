#include "sts2/search.h"
#include "sts2/observe.h"
#include "mcts_internal.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <cstring>
#include <map>
#include <stdexcept>

namespace sts2 {
namespace {

// An exact sparse representation of the observation and legal-action features.
// Hidden card UIDs and RNG state are deliberately excluded.  Legal actions are
// part of what the player can observe even if the observation schema aliases
// two states that happen to have different legal choices.
using PublicKey = std::vector<std::pair<std::uint32_t, std::uint32_t>>;
std::uint32_t float_bits(float x) {
    std::uint32_t bits;
    std::memcpy(&bits, &x, sizeof(bits));
    return bits;
}
PublicKey public_key(const BattleContext &bc) {
    PublicKey key;
    key.emplace_back(0, static_cast<std::uint32_t>(bc.outcome));
    const auto obs = public_combat_observation(bc);
    for (std::size_t i = 0; i < obs.size(); ++i)
        if (obs[i] != 0.0f) key.emplace_back(static_cast<std::uint32_t>(i + 1), float_bits(obs[i]));
    std::vector<std::vector<float>> options;
    if (bc.outcome == Outcome::UNDECIDED)
        for (const auto &a : bc.legal_actions()) options.push_back(combat_action_features(bc, a));
    std::sort(options.begin(), options.end());
    std::uint32_t offset = static_cast<std::uint32_t>(obs.size() + 1);
    key.emplace_back(offset++, static_cast<std::uint32_t>(options.size()));
    for (const auto &option : options) {
        for (std::size_t i = 0; i < option.size(); ++i)
            if (option[i] != 0.0f) key.emplace_back(offset + static_cast<std::uint32_t>(i), float_bits(option[i]));
        offset += static_cast<std::uint32_t>(option.size());
    }
    return key;
}

// When hidden cards are resampled, a hand index can denote a different card
// on another visit. Key card actions by identity, while retaining the current
// concrete action for execution. Each node is an information-set approximation:
// legal actions are refreshed for every determinization.
Action action_key(const BattleContext &bc, Action a) {
    if (a.type == ActionType::PLAY_CARD && a.hand < bc.handCount) {
        a.uid = bc.hand[a.hand].uid;
        a.hand = 0;
    }
    return a;
}

struct Edge {
    Action key;
    Action lastAction;
    int child = -1;
    double prior = 0.0;
    std::vector<float> visibleAction;
    int duplicate = 0;
    int visits = 0;
    double valueSum = 0;
    std::map<PublicKey, int> publicChildren;
};
struct Node {
    std::vector<Edge> edges;
    int visits = 0;
    double valueSum = 0;
};

// STS1 prioritizes a winning rollout and its absolute remaining HP, potions,
// and turn count. STS2 does not track STS1's total energy wasted/cards drawn,
// so the losing-state heuristic necessarily differs.
double terminal_score(const BattleContext &bc) {
    if (bc.outcome == Outcome::PLAYER_VICTORY)
        return 100.0 * (35.0 + bc.player.hp + 4.0 * bc.potionCount - bc.turn * 0.01);
    double hp = 0.0, maxHp = 0.0;
    int alive = 0;
    for (int i = 0; i < bc.monsterCount; ++i) {
        const Monster &m = bc.monsters[i];
        if (m.power[static_cast<int>(PowerId::MINION)] > 0) continue;
        if (m.maxHp <= 0) continue;
        maxHp += m.maxHp;
        hp += std::max(0, m.hp);
        if (m.alive) ++alive;
    }
    const double damage = maxHp > 0 ? 10.0 * (1.0 - hp / maxHp) : 0.0;
    return damage - alive + 2.0 * bc.potionCount + bc.turn * 0.2;
}

}  // namespace

static MctsResult mcts_impl(const BattleContext &root, int simulations, double c,
                            std::uint32_t seed, bool resample_hidden, bool greedy_rollout,
                            double epsilon, const std::vector<double> *root_priors,
                            double c_puct, const MctsPriorFn *prior_fn = nullptr,
                            int max_prior_depth = 0,
                            const MctsValueFn *value_fn = nullptr) {
    MctsResult result;
    const auto rootActions = root.legal_actions();
    if (rootActions.empty()) return result;
    if (rootActions.size() == 1 || simulations <= 0) {
        result.actions.push_back(rootActions[0]);
        return result;
    }
    Rng rng(seed);
    std::vector<Node> nodes(1);
    nodes.reserve(static_cast<std::size_t>(simulations) + 1);
    std::vector<int> path;
    std::vector<std::pair<int, int>> edgePath;
    std::vector<Action> actions;
    std::vector<Action> bestLine;
    double bestScore = -std::numeric_limits<double>::infinity();
    double minScore = std::numeric_limits<double>::infinity();
    bool bestVictory = false;

    for (int s = 0; s < simulations; ++s) {
        BattleContext bc = root;
        if (resample_hidden)
            bc.resample_hidden(static_cast<std::uint32_t>(rng.next_int(0, 1000000000)));
        path.clear(); edgePath.clear(); actions.clear(); path.push_back(0);
        int nodeId = 0;
        int depth = 0;
        bool invalid = false;
        while (bc.outcome == Outcome::UNDECIDED && depth < 500) {
            auto legal = bc.legal_actions();
            if (legal.empty()) { invalid = true; break; }
            const bool leaf = nodes[nodeId].edges.empty();
            // Legal actions may vary after hidden-state resampling. Only select
            // currently legal edges and add newly observed choices.
            std::vector<int> legalEdge;
            legalEdge.reserve(legal.size());
            std::vector<std::vector<float>> seenVisible;
            bool newEdge = false;
            for (const Action &action : legal) {
                const Action key = action_key(bc, action);
                const auto visible = resample_hidden ? combat_action_features(bc, action) : std::vector<float>{};
                const int duplicate = resample_hidden ? static_cast<int>(std::count(seenVisible.begin(), seenVisible.end(), visible)) : 0;
                if (resample_hidden) seenVisible.push_back(visible);
                auto &edges = nodes[nodeId].edges;
                auto it = std::find_if(edges.begin(), edges.end(),
                    [&](const Edge &edge) { return resample_hidden ?
                        edge.visibleAction == visible && edge.duplicate == duplicate : edge.key == key; });
                if (it == edges.end()) {
                    edges.push_back({key, action, -1});
                    if (resample_hidden) {
                        edges.back().visibleAction = visible;
                        edges.back().duplicate = duplicate;
                    }
                    newEdge = true;
                    legalEdge.push_back(static_cast<int>(edges.size()) - 1);
                } else {
                    const int e = static_cast<int>(it - edges.begin());
                    edges[e].lastAction = action;
                    legalEdge.push_back(e);
                }
            }
            const bool depth_puct = prior_fn && depth < max_prior_depth;
            if ((leaf || (resample_hidden && newEdge)) && depth_puct) {
                auto priors = legal.size() == 1 ? std::vector<double>{1.0}
                                                : (*prior_fn)(bc, legal);
                if (priors.size() != legal.size())
                    throw std::invalid_argument("node priors must match legal actions");
                double sum = 0.0;
                for (double p : priors) {
                    if (!std::isfinite(p) || p < 0.0)
                        throw std::invalid_argument("node priors must be finite and nonnegative");
                    sum += p;
                }
                if (!std::isfinite(sum) || sum <= 0.0)
                    throw std::invalid_argument("node priors must have a positive finite sum");
                for (std::size_t i = 0; i < priors.size(); ++i)
                    nodes[nodeId].edges[legalEdge[i]].prior = priors[i] / sum;
            }
            int choice = 0;
            if (leaf) {
                if (depth_puct || (nodeId == 0 && root_priors)) {
                    // Match STS1: the initial root expansion is sampled from
                    // the network prior; later leaf expansions stay uniform.
                    double draw = rng.sample();
                    choice = static_cast<int>(legal.size()) - 1;
                    for (int i = 0; i < static_cast<int>(legal.size()); ++i) {
                        if (depth_puct) {
                            draw -= nodes[nodeId].edges[legalEdge[i]].prior;
                        } else {
                            const auto found = std::find(rootActions.begin(), rootActions.end(), legal[i]);
                            if (found == rootActions.end())
                                throw std::logic_error("resampled root legal actions changed");
                            draw -= (*root_priors)[static_cast<std::size_t>(found - rootActions.begin())];
                        }
                        if (draw < 0.0) { choice = i; break; }
                    }
                } else {
                    choice = rng.next_int(0, static_cast<int>(legal.size()) - 1);
                }
            } else {
                double top = -std::numeric_limits<double>::infinity();
                for (int i = 0; i < static_cast<int>(legal.size()); ++i) {
                    const Edge &edge = nodes[nodeId].edges[legalEdge[i]];
                    const int n = resample_hidden ? edge.visits : (edge.child < 0 ? 0 : nodes[edge.child].visits);
                    const double sum = resample_hidden ? edge.valueSum : (edge.child < 0 ? 0.0 : nodes[edge.child].valueSum);
                    const double quality = detail::mcts_quality(sum, n, bestScore, minScore);
                    double explore;
                    if (depth_puct) {
                        explore = c_puct * edge.prior * std::sqrt(nodes[nodeId].visits + 1.0) / (n + 1.0);
                    } else if (nodeId == 0 && root_priors) {
                        const auto found = std::find(rootActions.begin(), rootActions.end(), legal[i]);
                        if (found == rootActions.end())
                            throw std::logic_error("resampled root legal actions changed");
                        const double prior = (*root_priors)[static_cast<std::size_t>(found - rootActions.begin())];
                        explore = c_puct * prior * std::sqrt(nodes[nodeId].visits + 1.0) / (n + 1.0);
                    } else {
                        explore = c * std::sqrt(std::log(nodes[nodeId].visits + 1.0) / (n + 1.0));
                    }
                    if (quality + explore > top) { top = quality + explore; choice = i; }
                }
            }
            const int edgeIndex = legalEdge[choice];
            if (!bc.step(legal[choice])) { invalid = true; break; }
            int child = -1;
            if (resample_hidden) {
                auto key = public_key(bc);
                auto &children = nodes[nodeId].edges[edgeIndex].publicChildren;
                auto found = children.find(key);
                if (found == children.end()) {
                    child = static_cast<int>(nodes.size());
                    children.emplace(std::move(key), child);
                    nodes.emplace_back();
                } else child = found->second;
                edgePath.emplace_back(nodeId, edgeIndex);
            } else {
                child = nodes[nodeId].edges[edgeIndex].child;
                if (child < 0) {
                    child = static_cast<int>(nodes.size());
                    nodes[nodeId].edges[edgeIndex].child = child;
                    nodes.emplace_back();
                }
            }
            actions.push_back(legal[choice]);
            path.push_back(child);
            nodeId = child;
            ++depth;
            if (leaf) break;
        }
        if (invalid) continue;
        while (!value_fn && bc.outcome == Outcome::UNDECIDED && depth < 500) {
            auto legal = bc.legal_actions();
            if (legal.empty()) { invalid = true; break; }
            Action a = greedy_rollout ? greedy_action(bc, rng, epsilon)
                                      : legal[rng.next_int(0, static_cast<int>(legal.size()) - 1)];
            if (!bc.step(a)) { invalid = true; break; }
            actions.push_back(a);
            ++depth;
        }
        if (invalid) continue;
        double score;
        if (!value_fn) {
            score = terminal_score(bc);
        } else if (bc.outcome == Outcome::UNDECIDED) {
            score = (*value_fn)(bc);
            if (!std::isfinite(score))
                throw std::invalid_argument("leaf value must be finite");
        } else {
            // CombatValue.main is trained on battle-win + final HP fraction.
            const double hp = bc.player.maxHp > 0
                ? std::clamp(static_cast<double>(bc.player.hp) / bc.player.maxHp, 0.0, 1.0)
                : 0.0;
            score = (bc.outcome == Outcome::PLAYER_VICTORY ? 1.0 : 0.0) + hp;
        }
        if (score > bestScore) {
            bestScore = score;
            bestLine = actions;
            bestVictory = bc.outcome == Outcome::PLAYER_VICTORY;
        }
        minScore = std::min(minScore, score);
        for (int id : path) { ++nodes[id].visits; nodes[id].valueSum += score; }
        for (const auto &p : edgePath) {
            Edge &edge = nodes[p.first].edges[p.second];
            ++edge.visits;
            edge.valueSum += score;
        }
        ++result.simulations;
    }
    if (resample_hidden || value_fn) {
        // Never select the best lucky determinization or reuse its future line.
        // Aggregate all sampled outcomes and execute only the root action.
        const Edge *best = nullptr;
        int bestVisits = -1;
        for (const Edge &edge : nodes[0].edges) {
            const int visits = resample_hidden ? edge.visits :
                (edge.child < 0 ? 0 : nodes[edge.child].visits);
            if (visits > bestVisits) { best = &edge; bestVisits = visits; }
        }
        result.actions.push_back(best ? best->lastAction : rootActions[0]);
    } else if (bestVictory && !bestLine.empty()) {
        result.actions = std::move(bestLine);
        result.victory = true;
    } else {
        int node = 0;
        while (result.actions.size() < 5 && !nodes[node].edges.empty()) {
            const Edge *best = nullptr;
            int visits = -1;
            for (const Edge &e : nodes[node].edges) {
                const int n = e.child < 0 ? 0 : nodes[e.child].visits;
                if (n > visits) { visits = n; best = &e; }
            }
            if (!best || best->child < 0) break;
            result.actions.push_back(best->lastAction);
            node = best->child;
        }
        if (result.actions.empty()) result.actions.push_back(rootActions[0]);
    }
    return result;
}

MctsResult mcts(const BattleContext &root, int simulations, double c,
                std::uint32_t seed, bool resample_hidden, bool greedy_rollout,
                double epsilon) {
    return mcts_impl(root, simulations, c, seed, resample_hidden, greedy_rollout,
                     epsilon, nullptr, 0.0);
}

MctsResult mcts_priors(const BattleContext &root, int simulations,
                       const std::vector<Action> &expected_actions,
                       const std::vector<double> &priors, double c_puct,
                       std::uint32_t seed, bool resample_hidden, bool greedy_rollout,
                       double epsilon) {
    const auto actual = root.legal_actions();
    if (actual != expected_actions || priors.size() != actual.size())
        throw std::invalid_argument("priors and actions must match current legal actions in order");
    if (simulations < 0 || !std::isfinite(c_puct) || c_puct < 0.0 ||
        !std::isfinite(epsilon) || epsilon < 0.0 || epsilon > 1.0)
        throw std::invalid_argument("invalid MCTS budget, exploration or epsilon");
    std::vector<double> normalized = priors;
    double sum = 0.0;
    for (double p : normalized) {
        if (!std::isfinite(p) || p < 0.0)
            throw std::invalid_argument("priors must be finite and nonnegative");
        sum += p;
    }
    if (!std::isfinite(sum) || sum <= 0.0)
        throw std::invalid_argument("priors must have a positive finite sum");
    for (double &p : normalized) p /= sum;
    return mcts_impl(root, simulations, 4.242640687119285, seed, resample_hidden,
                     greedy_rollout, epsilon, &normalized, c_puct);
}

MctsResult mcts_depth_priors(const BattleContext &root, int simulations,
                             const MctsPriorFn &prior_fn, int max_depth,
                             double c_puct, std::uint32_t seed,
                             bool greedy_rollout, double epsilon, bool resample_hidden,
                             const MctsValueFn *value_fn) {
    if (!prior_fn || max_depth < 1 || simulations < 0 || !std::isfinite(c_puct) || c_puct < 0.0 ||
        !std::isfinite(epsilon) || epsilon < 0.0 || epsilon > 1.0)
        throw std::invalid_argument("invalid MCTS callback, depth, budget, exploration or epsilon");
    return mcts_impl(root, simulations, 4.242640687119285, seed, resample_hidden,
                     greedy_rollout, epsilon, nullptr, c_puct, &prior_fn, max_depth, value_fn);
}
}  // namespace sts2
