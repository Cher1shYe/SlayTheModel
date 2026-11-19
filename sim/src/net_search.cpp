#include "sts2/net_search.h"

#include "sts2/observe.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <random>
#include <stdexcept>

namespace sts2 {
namespace {

// Same exact public key as mcts.cpp: public observation + sorted visible legal actions.
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

struct Edge {
    std::vector<float> visible;
    int duplicate = 0;
    double prior = 0.0;
    int visits = 0;
    double valueSum = 0.0;
    std::map<PublicKey, int> children;
};
struct Node {
    bool expanded = false;
    double netValue = 0.0;
    int visits = 0;
    double valueSum = 0.0;
    std::vector<Edge> edges;
};

// Visible identity (features, duplicate rank) of each legal action of bc.
std::vector<std::pair<std::vector<float>, int>> visible_actions(const BattleContext &bc,
                                                                const std::vector<Action> &legal) {
    std::vector<std::pair<std::vector<float>, int>> out;
    out.reserve(legal.size());
    for (const Action &a : legal) {
        auto f = combat_action_features(bc, a);
        int dup = 0;
        for (const auto &o : out) dup += o.first == f ? 1 : 0;
        out.emplace_back(std::move(f), dup);
    }
    return out;
}

}  // namespace

double combat_terminal_value(const BattleContext &bc, double winBase, double potionWeight) {
    if (bc.outcome != Outcome::PLAYER_VICTORY) return 0.0;
    const double maxHp = std::max(1, bc.player.maxHp);
    const double hp = std::max(0, bc.player.hp);
    return winBase + (1.0 - winBase) * (hp + potionWeight * bc.potionCount) / maxHp;
}

struct NetSearch::Impl {
    BattleContext root;
    std::vector<Action> rootActions;
    int simulations = 0;
    int done = 0;
    NetSearchConfig cfg;
    Rng rng;
    std::mt19937 noiseRng;
    std::vector<Node> nodes;
    bool waiting = false;
    BattleContext work;       // per-simulation determinization (kept off the stack: it is large)
    BattleContext pending;
    int pendingNode = -1;
    std::vector<int> nodePath;
    std::vector<std::pair<int, int>> edgePath;
    double qMin = std::numeric_limits<double>::infinity();
    double qMax = -std::numeric_limits<double>::infinity();

    Impl(const BattleContext &r, int sims, std::uint32_t seed, const NetSearchConfig &c)
        : root(r), rootActions(r.legal_actions()), simulations(sims), cfg(c), rng(seed), noiseRng(seed ^ 0x9e3779b9u) {
        nodes.emplace_back();
    }

    void backup(double v) {
        qMin = std::min(qMin, v);
        qMax = std::max(qMax, v);
        for (int id : nodePath) { ++nodes[id].visits; nodes[id].valueSum += v; }
        for (const auto &p : edgePath) {
            Edge &e = nodes[p.first].edges[p.second];
            ++e.visits;
            e.valueSum += v;
        }
        ++done;
    }

    void expand(int nodeId, const BattleContext &bc, const std::vector<double> &priors) {
        const auto legal = bc.legal_actions();
        const auto vis = visible_actions(bc, legal);
        Node &n = nodes[nodeId];
        n.edges.clear();
        for (std::size_t i = 0; i < legal.size(); ++i) {
            Edge e;
            e.visible = vis[i].first;
            e.duplicate = vis[i].second;
            e.prior = priors[i];
            n.edges.push_back(std::move(e));
        }
        n.expanded = true;
    }

    // Edge index of each legal action of bc at node n; adds unseen ones with a uniform prior.
    std::vector<int> match(int nodeId, const BattleContext &bc, const std::vector<Action> &legal) {
        const auto vis = visible_actions(bc, legal);
        std::vector<int> out;
        out.reserve(legal.size());
        for (std::size_t i = 0; i < legal.size(); ++i) {
            auto &edges = nodes[nodeId].edges;
            int found = -1;
            for (std::size_t e = 0; e < edges.size(); ++e)
                if (edges[e].duplicate == vis[i].second && edges[e].visible == vis[i].first) { found = static_cast<int>(e); break; }
            if (found < 0) {
                Edge e;
                e.visible = vis[i].first;
                e.duplicate = vis[i].second;
                e.prior = 1.0 / static_cast<double>(legal.size());
                edges.push_back(std::move(e));
                found = static_cast<int>(edges.size()) - 1;
            }
            out.push_back(found);
        }
        return out;
    }

    int select(int nodeId, const std::vector<int> &legalEdge) const {
        const Node &n = nodes[nodeId];
        const bool norm = cfg.normalizeQ && qMax > qMin;
        const auto scale = [&](double v) { return norm ? (v - qMin) / (qMax - qMin) : v; };
        const double parentQ = scale(n.visits > 0 ? n.valueSum / n.visits : n.netValue);
        const double sqrtN = std::sqrt(std::max(1, n.visits));
        int best = 0;
        double top = -1e300;
        for (std::size_t i = 0; i < legalEdge.size(); ++i) {
            const Edge &e = n.edges[static_cast<std::size_t>(legalEdge[i])];
            const double q = e.visits > 0 ? scale(e.valueSum / e.visits) : parentQ - cfg.fpuReduction;
            const double u = cfg.cPuct * e.prior * sqrtN / (1.0 + e.visits);
            if (q + u > top) { top = q + u; best = static_cast<int>(i); }
        }
        return best;
    }

    bool advance() {
        if (waiting) return true;
        if (rootActions.empty()) return false;
        while (done < simulations) {
            work = root;
            BattleContext &bc = work;
            if (cfg.resampleHidden)
                bc.resample_hidden(static_cast<std::uint32_t>(rng.next_int(0, 1000000000)));
            nodePath.assign(1, 0);
            edgePath.clear();
            int node = 0;
            bool invalid = false, finished = false;
            for (int depth = 0; depth < 2000; ++depth) {
                if (bc.outcome != Outcome::UNDECIDED) {
                    if (cfg.evalTerminalWins && bc.outcome == Outcome::PLAYER_VICTORY) {
                        if (!nodes[node].expanded) {          // first visit: the caller values it
                            pending = bc;
                            pendingNode = node;
                            waiting = true;
                            return true;
                        }
                        backup(nodes[node].netValue);
                    } else if (cfg.evalTerminalWins) {
                        backup(0.0);
                    } else {
                        backup(combat_terminal_value(bc, cfg.winBase, cfg.potionWeight));
                    }
                    finished = true;
                    break;
                }
                const auto legal = bc.legal_actions();
                if (legal.empty()) { invalid = true; break; }
                if (!nodes[node].expanded) {
                    if (legal.size() == 1 && node != 0) {
                        expand(node, bc, {1.0});      // forced step: no evaluation needed
                    } else {
                        pending = bc;
                        pendingNode = node;
                        waiting = true;
                        return true;
                    }
                }
                const auto legalEdge = match(node, bc, legal);
                const int choice = select(node, legalEdge);
                const int edgeIndex = legalEdge[static_cast<std::size_t>(choice)];
                if (!bc.step(legal[static_cast<std::size_t>(choice)])) { invalid = true; break; }
                auto key = public_key(bc);
                auto &children = nodes[node].edges[static_cast<std::size_t>(edgeIndex)].children;
                int child;
                auto it = children.find(key);
                if (it == children.end()) {
                    child = static_cast<int>(nodes.size());
                    children.emplace(std::move(key), child);
                    nodes.emplace_back();
                } else {
                    child = it->second;
                }
                edgePath.emplace_back(node, edgeIndex);
                nodePath.push_back(child);
                node = child;
            }
            // A broken state or the depth cap: count the simulation so it cannot loop forever.
            if (invalid || !finished) ++done;
        }
        return false;
    }

    void provide(const std::vector<double> &priorsIn, double value) {
        if (!waiting) throw std::logic_error("NetSearch::provide without a pending evaluation");
        if (!std::isfinite(value)) throw std::invalid_argument("network value must be finite");
        const auto legal = pending.legal_actions();
        if (priorsIn.size() != legal.size()) throw std::invalid_argument("priors must match pending legal actions");
        std::vector<double> priors = priorsIn;
        double sum = 0.0;
        for (double p : priors) {
            if (!std::isfinite(p) || p < 0.0) throw std::invalid_argument("priors must be finite and nonnegative");
            sum += p;
        }
        if (sum <= 0.0) { for (double &p : priors) p = 1.0; sum = static_cast<double>(priors.size()); }
        for (double &p : priors) p /= sum;
        if (pendingNode == 0 && cfg.dirichletFrac > 0.0 && priors.size() > 1) {
            std::gamma_distribution<double> gamma(cfg.dirichletAlpha, 1.0);
            std::vector<double> noise(priors.size());
            double ns = 0.0;
            for (double &x : noise) { x = gamma(noiseRng); ns += x; }
            for (std::size_t i = 0; i < priors.size(); ++i)
                priors[i] = (1.0 - cfg.dirichletFrac) * priors[i] + cfg.dirichletFrac * noise[i] / std::max(ns, 1e-12);
        }
        expand(pendingNode, pending, priors);
        nodes[static_cast<std::size_t>(pendingNode)].netValue = value;
        waiting = false;
        backup(value);
    }

    std::vector<int> rootEdges() const {
        std::vector<int> out(rootActions.size(), -1);
        if (!nodes[0].expanded) return out;
        const auto vis = visible_actions(root, rootActions);
        for (std::size_t i = 0; i < rootActions.size(); ++i)
            for (std::size_t e = 0; e < nodes[0].edges.size(); ++e)
                if (nodes[0].edges[e].duplicate == vis[i].second && nodes[0].edges[e].visible == vis[i].first) {
                    out[i] = static_cast<int>(e);
                    break;
                }
        return out;
    }
};

NetSearch::NetSearch(const BattleContext &root, int simulations, std::uint32_t seed, const NetSearchConfig &cfg)
    : impl_(std::make_unique<Impl>(root, simulations, seed, cfg)) {
    if (simulations < 1) throw std::invalid_argument("NetSearch needs at least one simulation");
}
NetSearch::~NetSearch() = default;
bool NetSearch::advance() { return impl_->advance(); }
bool NetSearch::waiting() const { return impl_->waiting; }
const BattleContext &NetSearch::pending_state() const {
    if (!impl_->waiting) throw std::logic_error("NetSearch has no pending evaluation");
    return impl_->pending;
}
void NetSearch::provide(const std::vector<double> &priors, double value) { impl_->provide(priors, value); }
int NetSearch::simulations_done() const { return impl_->done; }
const std::vector<Action> &NetSearch::root_actions() const { return impl_->rootActions; }
std::vector<int> NetSearch::root_visits() const {
    const auto idx = impl_->rootEdges();
    std::vector<int> out(idx.size(), 0);
    for (std::size_t i = 0; i < idx.size(); ++i)
        if (idx[i] >= 0) out[i] = impl_->nodes[0].edges[static_cast<std::size_t>(idx[i])].visits;
    return out;
}
std::vector<double> NetSearch::root_q() const {
    const auto idx = impl_->rootEdges();
    std::vector<double> out(idx.size(), std::nan(""));
    for (std::size_t i = 0; i < idx.size(); ++i)
        if (idx[i] >= 0) {
            const auto &e = impl_->nodes[0].edges[static_cast<std::size_t>(idx[i])];
            if (e.visits > 0) out[i] = e.valueSum / e.visits;
        }
    return out;
}
std::vector<double> NetSearch::root_priors() const {
    const auto idx = impl_->rootEdges();
    std::vector<double> out(idx.size(), 0.0);
    for (std::size_t i = 0; i < idx.size(); ++i)
        if (idx[i] >= 0) out[i] = impl_->nodes[0].edges[static_cast<std::size_t>(idx[i])].prior;
    return out;
}
double NetSearch::root_value() const { return impl_->nodes[0].netValue; }
Action NetSearch::best_action() const {
    const auto &acts = impl_->rootActions;
    if (acts.empty()) throw std::logic_error("NetSearch root has no legal action");
    const auto visits = root_visits();
    const auto priors = root_priors();
    std::size_t best = 0;
    for (std::size_t i = 1; i < acts.size(); ++i)
        if (visits[i] > visits[best] || (visits[i] == visits[best] && priors[i] > priors[best])) best = i;
    return acts[best];
}

}  // namespace sts2
