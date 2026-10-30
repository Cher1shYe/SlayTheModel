#include <algorithm>
#include <cassert>
#include <iostream>
#include <limits>
#include <stdexcept>
#include "sts2/search.h"
#include "sts2/monsters.h"
#include "../src/mcts_internal.h"

using namespace sts2;

static BattleContext setup() {
    BattleContext b;
    b.player.hp = b.player.maxHp = 80;
    b.player.energy = 2;
    spawn_monster(b, MonsterId::CEREMONIAL_BEAST, 0);
    b.monsterCount = 1;
    b.monsters[0].hp = b.monsters[0].maxHp = 12;
    b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 1);
    b.hand[b.handCount++] = make_card(CardId::STRIKE_IRONCLAD, false, 2);
    return b;
}

static bool legal(const BattleContext &b, const Action &a) {
    const auto actions = b.legal_actions();
    return std::find(actions.begin(), actions.end(), a) != actions.end();
}

int main() {
    // Identical results must leave action selection to the exploration term;
    // a tiny divisor previously locked the tree to the first positive edge.
    assert(detail::mcts_quality(500.0, 1, 500.0, 500.0) == 0.0);
    assert(detail::mcts_quality(-500.0, 1, -500.0, -500.0) == 0.0);
    assert(detail::mcts_quality(20.0, 1, 15.0, 5.0) == 1.0);
    BattleContext original = setup();
    const auto first = mcts(original, 64, 4.242640687, 123, false, false, 0.05);
    const auto again = mcts(original, 64, 4.242640687, 123, false, false, 0.05);
    assert(first.simulations == 64 && first.victory && first.actions.size() >= 2);
    assert(first.actions == again.actions && first.simulations == again.simulations);
    assert(original.monsters[0].hp == 12 && original.handCount == 2);
    const auto root_actions = original.legal_actions();
    assert(root_actions.size() > 1);
    for (std::size_t i = 0; i < root_actions.size(); ++i) {
        std::vector<double> one_hot(root_actions.size(), 0.0);
        one_hot[i] = 1.0;
        const auto selected = mcts_priors(original, 1, root_actions, one_hot, 3.0, 123);
        assert(selected.simulations == 1 && !selected.actions.empty());
        assert(selected.actions[0] == root_actions[i]);
    }
    const std::vector<double> uniform(root_actions.size(), 1.0);
    const std::vector<double> scaled(root_actions.size(), 10.0);
    const auto prior_a = mcts_priors(original, 64, root_actions, uniform, 3.0, 123);
    const auto prior_b = mcts_priors(original, 64, root_actions, scaled, 3.0, 123);
    assert(prior_a.actions == prior_b.actions && prior_a.simulations == prior_b.simulations);
    auto rejects = [&](const std::vector<Action> &actions, const std::vector<double> &p) {
        try { mcts_priors(original, 8, actions, p); }
        catch (const std::invalid_argument &) { return true; }
        return false;
    };
    auto wrong_order = root_actions;
    std::reverse(wrong_order.begin(), wrong_order.end());
    assert(rejects(wrong_order, uniform));
    assert(rejects(root_actions, std::vector<double>(root_actions.size(), 0.0)));
    assert(rejects(root_actions, std::vector<double>(root_actions.size() - 1, 1.0)));
    auto invalid = uniform;
    invalid[0] = std::numeric_limits<double>::quiet_NaN();
    assert(rejects(root_actions, invalid));
    invalid[0] = -1.0;
    assert(rejects(root_actions, invalid));
    BattleContext replay = original;
    for (const auto &action : first.actions) {
        assert(legal(replay, action));
        assert(replay.step(action));
        if (replay.outcome != Outcome::UNDECIDED) break;
    }
    assert(replay.outcome == Outcome::PLAYER_VICTORY);

    // Hidden draw orders produce different hands and pending choices in
    // deeper nodes; search must refresh legality and leave the source intact.
    original.draw[original.drawCount++] = make_card(CardId::DEFEND_IRONCLAD, false, 3);
    original.draw[original.drawCount++] = make_card(CardId::BASH, false, 4);
    for (int seed = 0; seed < 10; ++seed) {
        const auto sampled = mcts(original, 64, 4.242640687, seed, true, false, 0.05);
        assert(sampled.simulations == 64 && !sampled.actions.empty());
        assert(legal(original, sampled.actions[0]));
    }
    assert(original.drawCount == 2 && original.handCount == 2);

    // A simulated terminal state must use the exact win+HP training target,
    // without asking the value network to extrapolate a terminal observation.
    BattleContext terminal_case = setup();
    terminal_case.monsters[0].hp = 1;
    terminal_case.player.maxHp = 100;
    int value_calls = 0;
    MctsPriorFn choose_attack = [](const BattleContext &, const std::vector<Action> &actions) {
        std::vector<double> priors(actions.size(), 0.0);
        const auto it = std::find_if(actions.begin(), actions.end(), [](const Action &action) {
            return action.type == ActionType::PLAY_CARD;
        });
        assert(it != actions.end());
        priors[static_cast<std::size_t>(it - actions.begin())] = 1.0;
        return priors;
    };
    MctsValueFn terminal_value = [&](const BattleContext &state) {
        assert(state.outcome == Outcome::UNDECIDED);
        ++value_calls;
        return 0.0;
    };
    const auto immediate_win = mcts_depth_priors(terminal_case, 1, choose_attack, 500,
        3.0, 123, false, 0.05, true, &terminal_value);
    assert(immediate_win.simulations == 1 && value_calls == 0);
    assert(immediate_win.actions.size() == 1 &&
           immediate_win.actions[0].type == ActionType::PLAY_CARD);

    original.outcome = Outcome::PLAYER_LOSS;
    assert(mcts(original, 16).actions.empty());
    std::cout << "mcts regression passed\n";
}
