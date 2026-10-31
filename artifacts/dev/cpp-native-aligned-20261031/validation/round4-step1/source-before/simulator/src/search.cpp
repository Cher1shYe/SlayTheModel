#include "sts2/search.h"

#include <algorithm>
#include <cmath>

namespace sts2 {

static int card_score(const BattleContext &bc, const Action &a) {
    if (a.type == ActionType::END_TURN || a.type == ActionType::CONFIRM) return 0;
    if (a.type == ActionType::CHOOSE) return 5;
    if (a.type == ActionType::USE_POTION) return 0;
    if (a.hand >= bc.handCount) return 0;
    const Card &c = bc.hand[a.hand];
    const CardDef &d = card_def(c.id);
    int score = 0;
    if (d.type == CardType::ATTACK) {
        int dmg = card_damage(c) + bc.player.strength;
        if (bc.player.weak > 0) dmg = static_cast<int>(dmg * 0.75f);
        int hits = 1;
        if (c.id == CardId::TWIN_STRIKE) hits = card_var(c, VarId::HITS);
        if (c.id == CardId::SWORD_BOOMERANG) hits = card_var(c, VarId::REPEAT);
        if (c.id == CardId::WHIRLWIND) hits = bc.player.energy;
        if (d.target == TargetType::ALL_ENEMIES) {
            int total = 0;
            for (int m = 0; m < bc.monsterCount; ++m) {
                if (bc.monsters[m].alive) total += dmg;
            }
            score += total * hits;
        } else {
            int vuln = (a.target < bc.monsterCount) ? bc.monsters[a.target].vulnerable : 0;
            if (vuln > 0) dmg = static_cast<int>(dmg * 1.5f);
            score += dmg * hits;
        }
    }
    if (d.type == CardType::SKILL) {
        score += card_block(c) + bc.player.dexterity + 2;
        score += card_var(c, VarId::POWER);
    }
    if (d.type == CardType::POWER) score += 60;
    if (c.id == CardId::OFFERING || c.id == CardId::BATTLE_TRANCE ||
        c.id == CardId::BLOODLETTING) score += 20;
    if (c.id == CardId::BLOOD_WALL || c.id == CardId::BREAKTHROUGH) score -= 8;
    // Greedy otherwise re-casts True Grit forever and exhausts its own deck.
    if (c.id == CardId::TRUE_GRIT) score -= 10;
    return score;
}

Action greedy_action(const BattleContext &bc, Rng &rng, double epsilon) {
    std::vector<Action> actions = bc.legal_actions();
    if (actions.empty()) return Action{};
    if (actions.size() == 1) return actions[0];
    if (epsilon > 0.0f && rng.next_double() < static_cast<float>(epsilon)) {
        return actions[rng.next_int(0, static_cast<int>(actions.size()) - 1)];
    }

    // Prefer a lethal attack.
    for (const Action &a : actions) {
        if (a.type != ActionType::PLAY_CARD || a.target >= bc.monsterCount) continue;
        const Card &c = bc.hand[a.hand];
        if (!card_is_attack(c)) continue;
        if (card_def(c.id).target == TargetType::ENEMY) {
            int dmg = bc.calc_player_damage(card_damage(c), a.target);
            const Monster &m = bc.monsters[a.target];
            if (m.alive && dmg >= m.hp + m.block) return a;
        }
    }

    int best = -1;
    int best_score = -1;
    for (int i = 0; i < static_cast<int>(actions.size()); ++i) {
        const int score = card_score(bc, actions[i]);
        if (score > best_score) {
            best_score = score;
            best = i;
        }
    }
    if (best < 0 || actions[best].type == ActionType::END_TURN) {
        for (const Action &a : actions) {
            if (a.type == ActionType::END_TURN) return a;
        }
        return actions[0];
    }
    return actions[best];
}

double rollout(BattleContext &bc, Rng &rng, double epsilon, int maxSteps) {
    for (int step = 0; step < maxSteps && bc.outcome == Outcome::UNDECIDED; ++step) {
        Action a = greedy_action(bc, rng, epsilon);
        if (!bc.step(a)) break;
    }
    const double hp = static_cast<double>(bc.player.hp) / static_cast<double>(std::max(1, bc.player.maxHp));
    if (bc.outcome == Outcome::PLAYER_VICTORY) return 1.0 + hp;
    if (bc.outcome == Outcome::PLAYER_LOSS) return 0.0;
    return 0.5 * hp;  // cutoff
}

static SearchResult search_impl(const BattleContext &root, int simulations, double c,
                                double epsilon, std::uint32_t seed,
                                const std::vector<double> *priors,
                                bool resample_hidden) {
    SearchResult result;
    result.actions = root.legal_actions();
    result.visits.assign(result.actions.size(), 0);
    result.values.assign(result.actions.size(), 0.0);
    if (result.actions.size() <= 1 || simulations <= 0) return result;

    Rng rng(seed);
    int total = 0;
    // With priors, UCB alone never visits an action the prior has not already
    // sent a simulation to: q=0 for unvisited actions, so a peaked softmax
    // collapses the whole budget onto one action. Seed one visit per action in
    // descending prior order first, then run PUCT over the visited set.
    std::vector<int> init_order;
    if (priors) {
        init_order.resize(result.actions.size());
        for (int i = 0; i < static_cast<int>(init_order.size()); ++i) init_order[i] = i;
        std::stable_sort(init_order.begin(), init_order.end(), [&](int a, int b) {
            const double pa = a < static_cast<int>(priors->size()) ? (*priors)[a] : 0.0;
            const double pb = b < static_cast<int>(priors->size()) ? (*priors)[b] : 0.0;
            return pa > pb;
        });
    }
    int next_init = 0;
    for (int sim = 0; sim < simulations; ++sim) {
        int pick = -1;
        if (!priors) {
            for (int i = 0; i < static_cast<int>(result.visits.size()); ++i) {
                if (result.visits[i] == 0) { pick = i; break; }
            }
        }
        if (pick < 0 && next_init < static_cast<int>(init_order.size())) {
            pick = init_order[next_init++];
        }
        if (pick < 0) {
            double best = -1e18;
            for (int i = 0; i < static_cast<int>(result.visits.size()); ++i) {
                const int n = result.visits[i];
                const double q = n > 0 ? result.values[i] / n : 0.0;
                double u;
                if (priors && i < static_cast<int>(priors->size())) {
                    u = c * (*priors)[i] * std::sqrt(static_cast<double>(total) + 1.0) / (1.0 + n);
                } else {
                    if (n == 0) continue;
                    u = c * std::sqrt(std::log(static_cast<double>(total) + 1.0) / n);
                }
                if (q + u > best) { best = q + u; pick = i; }
            }
        }
        if (pick < 0) pick = 0;
        BattleContext bc = root;
        if (resample_hidden) {
            bc.resample_hidden(static_cast<std::uint32_t>(
                rng.next_int(0, 1000000000)));
        }
        if (!bc.step(result.actions[pick])) continue;
        const double v = rollout(bc, rng, epsilon);
        result.values[pick] += v;
        result.visits[pick] += 1;
        ++total;
    }
    result.simulations = total;
    return result;
}

SearchResult search(const BattleContext &root, int simulations, double c, double epsilon,
                    std::uint32_t seed, bool resample_hidden) {
    return search_impl(root, simulations, c, epsilon, seed, nullptr, resample_hidden);
}

SearchResult search_priors(const BattleContext &root, int simulations,
                           const std::vector<double> &priors, double c, double epsilon,
                           std::uint32_t seed, bool resample_hidden) {
    return search_impl(root, simulations, c, epsilon, seed, &priors, resample_hidden);
}

}  // namespace sts2
