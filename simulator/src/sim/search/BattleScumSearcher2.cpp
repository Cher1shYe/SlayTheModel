//
// Created by keega on 9/18/2021.
//

#include <algorithm>
#include <cstdint>
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ExpertKnowledge.h"
#include "constants/MonsterEncounters.h"

#include <utility>
#include <string>
#include <memory>

using namespace sts;

thread_local std::int64_t simulationIdx = 0; // for debugging

namespace sts::search {
    thread_local search::BattleScumSearcher2 *g_debug_scum_search;

    static bool g_savePotions = false;
    static int g_playoutTarget = 0;
    static int g_playoutOrder = 0;
    static int g_determinize = 0;
    static int g_playoutGuard = 0;
    static int g_playoutVariants = 0;
    static thread_local std::int64_t g_variantWins[16] = {0};
    void setPlayoutTarget(int mode) { g_playoutTarget = mode; }
    int playoutTarget() { return g_playoutTarget; }
    void setPlayoutOrder(int mode) { g_playoutOrder = mode; }
    int playoutOrder() { return g_playoutOrder; }
    void setDeterminize(int mode) { g_determinize = mode; }
    int determinize() { return g_determinize; }
    // 0: off; 1: when the incoming damage alone would kill the player and no
    // block is up, demote attacks so a defensive card is played first;
    // 2: same, but the trigger is "incoming >= 60% of current HP".
    void setPlayoutGuard(int mode) { g_playoutGuard = mode; }
    void setPlayoutVariants(int count) { g_playoutVariants = count; }
    void resetVariantStats() { for (int i = 0; i < 16; ++i) g_variantWins[i] = 0; }
    std::vector<std::int64_t> variantStats() {
        return std::vector<std::int64_t>(g_variantWins, g_variantWins + 16);
    }
    int playoutGuard() { return g_playoutGuard; }
    static double g_winHpWeight = 1.0;
    static double g_winPotionWeight = 4.0;
    void setWinHpWeight(double w) { if (w > 0.0) g_winHpWeight = w; }
    double winHpWeight() { return g_winHpWeight; }
    void setWinPotionWeight(double w) { if (w >= 0.0) g_winPotionWeight = w; }
    double winPotionWeight() { return g_winPotionWeight; }
    void setSavePotions(bool v) { g_savePotions = v; }
    bool savePotionsEnabled() { return g_savePotions; }
}



search::BattleScumSearcher2::BattleScumSearcher2(const BattleContext &bc, search::EvalFnc _evalFnc)
    : rootState(new BattleContext(bc)), evalFnc(std::move(_evalFnc)), randGen(bc.seed+bc.floorNum) {
}

void search::BattleScumSearcher2::search(int64_t simulations) {
    g_debug_scum_search = this;

    if (isTerminalState(*rootState)) {
        auto evaluation = evaluateEndState(*rootState);
        outcomePlayerHp = rootState->player.curHp;
        bestActionSequence = {};

        root.evaluationSum = evaluation;
        root.simulationCount = 1;
    }

    for (std::int64_t simCount = 0; simCount < simulations; ++simCount) {
        step();
    }
}

void search::BattleScumSearcher2::step() {
    // Rollout portfolio: each simulation uses a different greedy variant so
    // that N simulations explore N distinct lines instead of one repeated line.
    const int nVariants = g_playoutVariants < 0 ? -g_playoutVariants : g_playoutVariants;
    const bool adaptiveVariants = g_playoutVariants < 0;
    const bool diversifyNow = nVariants > 0
            && (!adaptiveVariants || bestActionValue < 1000.0);
    curVariant = diversifyNow ? static_cast<int>(stepCounter % nVariants) : 0;
    ++stepCounter;
    searchStack = {&root};
    actionStack.clear();
    BattleContext curState;
    curState = *rootState;

    while (true) {
        auto &curNode = *searchStack.back();

        if (isTerminalState(curState)) {
            updateFromPlayout(searchStack, actionStack, curState);
            return;
        }

        const bool isLeaf = curNode.edges.empty();
        if (isLeaf) {

            ++simulationIdx;
            enumerateActionsForNode(curNode, curState);
            const auto selectIdx = selectFirstActionForLeafNode(curNode);
            auto &edgeTaken = curNode.edges[selectIdx];

//            edgeTaken.action.printDesc(std::cout, curState) << std::endl;
            edgeTaken.action.execute(curState);

            actionStack.push_back(edgeTaken.action);
            searchStack.push_back(&edgeTaken.node);

            if (playoutMode == 0) playoutRandom(curState, actionStack);
            else playoutGreedy(curState, actionStack);
            updateFromPlayout(searchStack, actionStack, curState);
            return;

        } else {
            const auto selectIdx = selectBestEdgeToSearch(curNode);
            auto &edgeTaken = curNode.edges[selectIdx];

//            edgeTaken.action.printDesc(std::cout, curState) << std::endl;
            edgeTaken.action.execute(curState);

            actionStack.push_back(edgeTaken.action);
            searchStack.push_back(&edgeTaken.node);
        }
    }
}

void search::BattleScumSearcher2::updateFromPlayout(const std::vector<Node *> &stack, const std::vector<Action> &actionStack, const BattleContext &endState) {
    const auto evaluation = evaluateEndState(endState);

    if (evaluation > bestActionValue) {
        bestActionSequence = actionStack;
        bestActionValue = evaluation;
        outcomePlayerHp = endState.player.curHp;
        const int vi = curVariant % 16;
        if (vi >= 0 && curVariant >= 0) ++g_variantWins[vi];
    }

    if (evaluation < minActionValue) {
        minActionValue = evaluation;
    }

    const bool won = evaluation > 1000.0;
    for (auto it = stack.rbegin(); it != stack.rend(); ++it) {
        auto &node = *(*it);
        ++node.simulationCount;
        node.evaluationSum += evaluation;
        if (won) ++node.winCount;
    }
}

bool search::BattleScumSearcher2::isTerminalState(const BattleContext &bc) const { // maybe can optimize by making this evaluate directly if score cannot possibly be higher than best
    return bc.outcome != Outcome::UNDECIDED;
}

double search::BattleScumSearcher2::evaluateEdge(const search::BattleScumSearcher2::Node &parent, int edgeIdx) {

    const auto &edge = parent.edges[edgeIdx];

    // Virtual loss: in-flight simulations below this edge count as visits with a
    // pessimistic value so parallel threads explore different lines.  With
    // pending == 0 this is identical to the single-threaded rule.
    const double evalRangeNow = bestActionValue - minActionValue;
    const double pendingLoss = evalRangeNow > 0 ? 0.4 * evalRangeNow : 0.0;
    const double effCount = static_cast<double>(edge.node.simulationCount) + edge.node.pending;
    const double effSum = edge.node.evaluationSum - pendingLoss * edge.node.pending;

    double qualityValue = 0;
    if (!bestActionSequence.empty()) {
        auto avgEvaluation = effSum / (effCount + 1.0);
        double evalRange = bestActionValue - minActionValue;
        qualityValue = avgEvaluation / evalRange;
    }

    if (usePuct && (&parent == &root)) {
        const double fallback = 1.0 / static_cast<double>(parent.edges.size());
        auto it = rootPriors.find(edge.action.bits);
        const double prior = (it != rootPriors.end() && it->second > 0.0) ? it->second : fallback;
        const double logTerm = std::sqrt(std::log(parent.simulationCount + 1.0)
                / (effCount + 1.0));
        if (priorMode == 1) {
            return qualityValue + explorationParameter
                    * (prior * static_cast<double>(parent.edges.size())) * logTerm;
        }
        const double puctTerm = cPuct * prior * std::sqrt(parent.simulationCount + 1.0)
                / (1.0 + effCount);
        if (priorMode == 4) {
            return qualityValue + explorationParameter * logTerm + puctTerm;
        }
        if (annealCount <= 0.0) {
            return qualityValue + puctTerm;
        }
        const double weight = annealCount / (annealCount + static_cast<double>(parent.simulationCount));
        return qualityValue + weight * puctTerm
                + (1.0 - weight) * explorationParameter * logTerm;
    }

    double explorationValue = explorationParameter *
            std::sqrt(std::log(parent.simulationCount+1) / (effCount+1.0));

    return qualityValue + explorationValue;
}

int search::BattleScumSearcher2::selectBestEdgeToSearch(const search::BattleScumSearcher2::Node &cur) {
    if (cur.edges.size() == 1) {
        return 0;
    }

    auto bestEdge = 0;
    auto bestEdgeValue = evaluateEdge(cur, bestEdge);

    for (int i = 1; i < cur.edges.size(); ++i) {
        const auto value = evaluateEdge(cur, i);
        if (value > bestEdgeValue) {
            bestEdge = i;
            bestEdgeValue = value;
        }
    }
    return bestEdge;
}

int search::BattleScumSearcher2::selectFirstActionForLeafNode(const search::BattleScumSearcher2::Node &leafNode) {
    if (usePuct && (&leafNode == &root) && !rootPriors.empty() && leafNode.edges.size() > 1) {
        std::vector<double> w(leafNode.edges.size());
        const double fallback = 0.01 / static_cast<double>(leafNode.edges.size());
        double total = 0.0;
        for (std::size_t i = 0; i < leafNode.edges.size(); ++i) {
            auto it = rootPriors.find(leafNode.edges[i].action.bits);
            double p = (it != rootPriors.end()) ? it->second : fallback;
            if (p < 0.0) p = 0.0;
            w[i] = p;
            total += p;
        }
        if (total > 0.0) {
            std::uniform_real_distribution<double> dist(0.0, total);
            double r = dist(randGen);
            for (std::size_t i = 0; i < w.size(); ++i) {
                r -= w[i];
                if (r <= 0.0) return static_cast<int>(i);
            }
            return static_cast<int>(w.size()) - 1;
        }
    }
    auto dist = std::uniform_int_distribution<int>(0, static_cast<int>(leafNode.edges.size())-1);
    return dist(randGen);
}

void search::BattleScumSearcher2::playoutRandom(BattleContext &state, std::vector<Action> &actionStack) {
    Node tempNode; // temp
    while (!isTerminalState(state)) {
        ++simulationIdx;
        enumerateActionsForNode(tempNode, state);
        if (tempNode.edges.empty()) {
            std::cerr << state.seed << " " << simulationIdx << std::endl;
            std::cerr << state.monsters.arr[0].getName() << " " << state.floorNum << " " << monsterEncounterStrings[static_cast<int>(state.encounter)] << std::endl;
            assert(false);
        }

        auto dist = std::uniform_int_distribution<int>(0, static_cast<int>(tempNode.edges.size())-1);
        const int selectedIdx = dist(randGen);

        const auto action = tempNode.edges[selectedIdx].action;
//        action.printDesc(std::cout, state) << std::endl;
        actionStack.push_back(action);
        action.execute(state);

        tempNode.edges.clear();
    }
}

void search::BattleScumSearcher2::playoutGreedy(BattleContext &state, std::vector<Action> &actionStack) {
    if (g_determinize != 0 && state.cards.drawPile.size() > 1) {
        // Determinized rollout ("perfect information Monte Carlo" with a fresh
        // sample of the unseen future): the real draw order is unknown to the
        // player, yet the simulator replays one fixed order in every playout.
        // Re-shuffling the remaining pile at the start of each playout makes
        // each rollout an independent draw rather than a repeat of the same
        // deterministic line, so extra search budget actually averages out
        // draw luck instead of resampling one branch.
        std::shuffle(state.cards.drawPile.begin(), state.cards.drawPile.end(), randGen);
    }
    // Fast path: the greedy playout plays the first card in expert order and never
    // chooses a potion (END_TURN precedes potions in the edge list), so the full
    // edge enumeration can be skipped in PLAYER_NORMAL states.  This is the hot
    // loop of the search.  Non-standard input states (card-select screens) still
    // use the generic enumeration and take its first option, exactly like the
    // generic greedy chooser does.
    int targetMode = playoutTarget();
    int orderMode = playoutOrder();
    int guardMode = playoutGuard();
    if (curVariant != 0) {
        switch (curVariant % 12) {
            case 1: targetMode = 3; break;   // focus the biggest incoming threat
            case 2: targetMode = 2; break;   // focus the lowest hp fraction
            case 3: targetMode = 0; break;   // legacy: highest slot
            case 4: orderMode = 1; break;    // attack-first ordering
            case 5: guardMode = 1; break;    // lethal-turn defensive guard
            case 6: orderMode = 2; break;    // block-first while damage is incoming
            case 7: targetMode = 4; break;   // finish off a killable target
            case 8: orderMode = 8; break;   // cheapest card first
            case 9: orderMode = 9; break;   // play a killer blow first
            case 10: orderMode = 10; break; // best damage per energy first
            case 11: targetMode = 3; orderMode = 9; break;  // threat + kill first
            default: break;                  // 0: configured policy
        }
    }
    while (!isTerminalState(state)) {
        ++simulationIdx;
        if (state.inputState != InputState::PLAYER_NORMAL) {
            Node tempNode;
            enumerateActionsForNode(tempNode, state);
            if (tempNode.edges.empty()) break;
            const auto a = tempNode.edges[0].action;
            actionStack.push_back(a);
            a.execute(state);
            continue;
        }
        Action chosen(ActionType::END_TURN);
        if (state.isCardPlayAllowed()) {
            if (playoutEpsilon > 0.0) {
                std::uniform_real_distribution<double> flip(0.0, 1.0);
                if (flip(randGen) < playoutEpsilon) {
                    std::vector<int> playable;
                    for (int h = 0; h < state.cards.cardsInHand; ++h) {
                        if (state.cards.hand[h].canUseOnAnyTarget(state)) playable.push_back(h);
                    }
                    if (!playable.empty()) {
                        std::uniform_int_distribution<int> pick(0, static_cast<int>(playable.size()) - 1);
                        const int h = playable[pick(randGen)];
                        const auto &c = state.cards.hand[h];
                        if (c.requiresTarget()) {
                            int tIdx = -1;
                            for (int i = state.monsters.monsterCount - 1; i >= 0; --i) {
                                if (state.monsters.arr[i].isTargetable()) { tIdx = i; break; }
                            }
                            if (tIdx >= 0) chosen = Action(ActionType::CARD, h, tIdx);
                        } else {
                            chosen = Action(ActionType::CARD, h);
                        }
                        actionStack.push_back(chosen);
                        chosen.execute(state);
                        continue;
                    }
                }
            }
            int bestHand = -1;
            int bestOrder = std::numeric_limits<int>::max();
            int incoming = 0;
            if (orderMode != 0 || guardMode != 0) {
                for (int i = 0; i < state.monsters.monsterCount; ++i) {
                    const auto &m = state.monsters.arr[i];
                    if (m.curHp <= 0) continue;
                    const auto d = m.getMoveBaseDamage(state);
                    incoming += d.damage * d.attackCount;
                }
            }
            const bool needDefense = incoming > state.player.block;
            // Lethal-turn guard: the greedy playout otherwise walks straight
            // into a killing blow when the expert order happens to rank its
            // attacks first, which makes every defensive line look lost.
            bool guardNow = false;
            if (guardMode != 0 && state.player.block <= 0 && incoming > 0) {
                const int hp = state.player.curHp;
                guardNow = guardMode == 1 ? (incoming >= hp)
                                               : (incoming * 10 >= hp * 6);
            }
            const int nHand = state.cards.cardsInHand;
            for (int h = 0; h < nHand; ++h) {
                const auto &c = state.cards.hand[h];
                if (!c.canUseOnAnyTarget(state)) continue;
                int ord = search::Expert::getPlayOrdering(c.getId());
                const int ctype = static_cast<int>(c.getType());
                if (orderMode == 8) {
                    // energy-aware: spend the cheap cards first
                    ord += static_cast<int>(c.cost) * 40;
                } else if (orderMode == 9) {
                    // if this card can finish a monster this turn, play it first
                    const int dmgc = Card(c.getId(), c.isUpgraded()).getBaseDamage();
                    if (dmgc > 0) {
                        for (int t = 0; t < state.monsters.monsterCount; ++t) {
                            const auto &m = state.monsters.arr[t];
                            if (m.isTargetable() && m.curHp <= dmgc) { ord -= 1000; break; }
                        }
                    }
                } else if (orderMode == 10) {
                    // damage per energy first
                    const int dmgc = Card(c.getId(), c.isUpgraded()).getBaseDamage();
                    const int costc = c.cost > 0 ? static_cast<int>(c.cost) : 0;
                    ord -= (dmgc * 10) / (costc + 1);
                }
                if (orderMode == 4 || orderMode == 5 || orderMode == 7) {
                    const int amp = (orderMode == 5) ? 60 : 20;
                    std::uniform_int_distribution<int> jd(-amp, amp);
                    ord += jd(randGen);
                }
                // orderMode 1: attacks first when nothing gets through.
                // orderMode 2: blocks/skills first while unblocked damage is coming.
                // orderMode 3: both.
                if ((orderMode == 1 || orderMode == 3) && !needDefense && ctype == 1) {
                    ord += 1000;
                }
                if ((orderMode == 2 || orderMode == 3) && needDefense && ctype == 0) {
                    ord += 1000;
                }
                if (guardNow && static_cast<int>(c.getType()) == 0) {
                    ord += 1000;
                }
                if (ord < bestOrder) { bestOrder = ord; bestHand = h; }
            }
            if (bestHand >= 0) {
                const auto &c = state.cards.hand[bestHand];
                if (c.requiresTarget()) {
                    int tIdx = -1;
                    const int mode = targetMode;
                    if (mode == 1) {
                        int bestHp = std::numeric_limits<int>::max();
                        for (int i = 0; i < state.monsters.monsterCount; ++i) {
                            if (!state.monsters.arr[i].isTargetable()) continue;
                            if (state.monsters.arr[i].curHp < bestHp) {
                                bestHp = state.monsters.arr[i].curHp;
                                tIdx = i;
                            }
                        }
                    } else if (mode == 2) {
                        std::int64_t bestNum = -1, bestDen = 1;
                        for (int i = 0; i < state.monsters.monsterCount; ++i) {
                            const auto &m = state.monsters.arr[i];
                            if (!m.isTargetable()) continue;
                            const std::int64_t num = m.curHp;
                            const std::int64_t den = std::max(1, m.maxHp);
                            if (bestNum < 0 || num * bestDen < bestNum * den) {
                                bestNum = num; bestDen = den; tIdx = i;
                            }
                        }
                    } else if (mode == 4) {
                        // finish off: prefer a monster this card can kill this turn
                        const int dmg = std::max(1,
                                Card(c.getId(), c.isUpgraded()).getBaseDamage());
                        int bestHp = std::numeric_limits<int>::max();
                        for (int i = 0; i < state.monsters.monsterCount; ++i) {
                            const auto &m = state.monsters.arr[i];
                            if (!m.isTargetable()) continue;
                            if (m.curHp <= dmg && m.curHp < bestHp) {
                                bestHp = m.curHp;
                                tIdx = i;
                            }
                        }
                        if (tIdx < 0) {
                            int lowHp = std::numeric_limits<int>::max();
                            for (int i = 0; i < state.monsters.monsterCount; ++i) {
                                if (!state.monsters.arr[i].isTargetable()) continue;
                                if (state.monsters.arr[i].curHp < lowHp) {
                                    lowHp = state.monsters.arr[i].curHp;
                                    tIdx = i;
                                }
                            }
                        }
                    } else if (mode == 5) {
                        // line diversity: hit a uniformly random target
                        std::vector<int> tgt;
                        for (int i = 0; i < state.monsters.monsterCount; ++i) {
                            if (state.monsters.arr[i].isTargetable()) tgt.push_back(i);
                        }
                        if (!tgt.empty()) {
                            std::uniform_int_distribution<int> td(0, static_cast<int>(tgt.size()) - 1);
                            tIdx = tgt[td(randGen)];
                        }
                    } else if (mode == 3) {
                        int bestThreat = -1, bestHp = std::numeric_limits<int>::max();
                        for (int i = 0; i < state.monsters.monsterCount; ++i) {
                            const auto &m = state.monsters.arr[i];
                            if (!m.isTargetable()) continue;
                            const auto dmg = m.getMoveBaseDamage(state);
                            const int threat = dmg.damage * dmg.attackCount;
                            if (threat > bestThreat || (threat == bestThreat && m.curHp < bestHp)) {
                                bestThreat = threat; bestHp = m.curHp; tIdx = i;
                            }
                        }
                    } else {
                        for (int i = state.monsters.monsterCount - 1; i >= 0; --i) {
                            if (state.monsters.arr[i].isTargetable()) { tIdx = i; break; }
                        }
                    }
                    if (tIdx >= 0) chosen = Action(ActionType::CARD, bestHand, tIdx);
                } else {
                    chosen = Action(ActionType::CARD, bestHand);
                }
            }
        }
        actionStack.push_back(chosen);
        chosen.execute(state);
    }
}

void search::BattleScumSearcher2::enumerateActionsForNode(search::BattleScumSearcher2::Node &node,
                                                               const BattleContext &bc) {
    switch (bc.inputState) {
        case InputState::PLAYER_NORMAL:
            enumerateCardActions(node, bc);
            enumeratePotionActions(node, bc);
            node.edges.push_back({Action(ActionType::END_TURN)});
            break;

        case InputState::CARD_SELECT:
            enumerateCardSelectActions(node, bc);
            break;

        default:
#ifdef sts_asserts
            std::cerr << "enumerateActionsForNode: invalid input state: " << static_cast<int>(bc.inputState) << std::endl;
            assert(false);
#endif
            break;
    }

#ifdef sts_print_debug
    std::cout << "{ (" << node.edges.size() << ") ";
    for (int i = 0; i < node.edges.size(); ++i) {
        node.edges[i].action.printDesc(std::cout, bc) << ", ";
    }
    std::cout << " }" << std::endl;
#endif
}

void search::BattleScumSearcher2::enumerateCardActions(search::BattleScumSearcher2::Node &node,
                                                            const BattleContext &bc) {
    if (!bc.isCardPlayAllowed()) {
        return;
    }

    fixed_list<std::pair<int,int>, 10> playableHandIdxs;
    for (int handIdx = 0; handIdx < bc.cards.cardsInHand; ++handIdx) {
        const auto &c = bc.cards.hand[handIdx];
        if (!c.canUseOnAnyTarget(bc)) {
            continue;
        }

        bool isUniqueAction = true;

        if (handIdx > 0) {
            const auto &lastCard = bc.cards.hand[handIdx-1];

            bool isEqualToLastCard = c.id == lastCard.id &&
                    c.getUpgradeCount() == lastCard.getUpgradeCount() &&
                    // both should be less than deck size c.uniqueId < bc.cards.deck
                    c.costForTurn == lastCard.costForTurn &&
                    c.cost == lastCard.cost &&
                    c.freeToPlayOnce == lastCard.freeToPlayOnce &&
                    c.specialData == lastCard.specialData;

            if (isEqualToLastCard) {
                isUniqueAction = false;
            }
        }

        if (isUniqueAction) {
            playableHandIdxs.push_back( {handIdx, search::Expert::getPlayOrdering(c.getId())} );
        }
    }

    std::sort(playableHandIdxs.begin(), playableHandIdxs.end(), [](auto a, auto b) { return a.second < b.second; });

    for (auto pair : playableHandIdxs) {
        const auto handIdx = pair.first;
        const auto &c = bc.cards.hand[handIdx];

        if (c.requiresTarget()) {
            for (int tIdx = bc.monsters.monsterCount-1; tIdx >= 0; --tIdx) {
                if (!bc.monsters.arr[tIdx].isTargetable()) {
                    continue;
                }
                node.edges.push_back({Action(ActionType::CARD, handIdx, tIdx)});
            }
        } else {
            node.edges.push_back({Action(ActionType::CARD, handIdx)});
        }
    }

}

void search::BattleScumSearcher2::enumeratePotionActions(search::BattleScumSearcher2::Node &node,
                                                              const BattleContext &bc) {

    if (savePotionsEnabled() && !sts::isBossEncounter(bc.encounter)) {
        return;
    }

    const auto hasValidTarget = bc.monsters.getTargetableCount() > 0;

    int foundPotions = 0;
    for (int pIdx = 0; pIdx < bc.potionCapacity; ++pIdx) {

        const auto p = bc.potions[pIdx];
        if (p == Potion::EMPTY_POTION_SLOT) {
            continue;
        }
        ++foundPotions;

        // not enumerating the discard of a potion if it can be used
        if (p == Potion::FAIRY_POTION) {
            node.edges.push_back({Action(ActionType::POTION, pIdx, -1)});
            continue;
        }

        if (!potionRequiresTarget(p)) {
            node.edges.push_back({Action(ActionType::POTION, pIdx)});
            continue;
        }

        // potion requires target
        if (!hasValidTarget) {
            node.edges.push_back({Action(ActionType::POTION, pIdx, -1)});
            continue;
        }

        // there is a valid target
        for (int tIdx = 0; tIdx < bc.monsters.monsterCount; ++tIdx) {
            if (bc.monsters.arr[tIdx].isTargetable()) {
                node.edges.push_back({Action(ActionType::POTION, pIdx, tIdx)});
            }
        }
    }
}

template <typename ForwardIt>
void setupCardOptionsHelper(search::BattleScumSearcher2::Node &node, const ForwardIt begin, const ForwardIt end, const std::function<bool(const CardInstance &)> &p= nullptr) {
    for (int i = 0; begin+i != end; ++i) {
        const auto &c = begin[i];
        if (!p || (p(c))) {
            node.edges.push_back(
                    {search::Action(search::ActionType::SINGLE_CARD_SELECT, i)}
                );
        }
    }
}

void search::BattleScumSearcher2::enumerateCardSelectActions(search::BattleScumSearcher2::Node &node,
                                                                  const BattleContext &bc) {

    switch (bc.cardSelectInfo.cardSelectTask) {
        case CardSelectTask::ARMAMENTS:
            setupCardOptionsHelper( node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand,
                                    [] (const CardInstance &c) { return c.canUpgrade(); });
            break;

        case CardSelectTask::CODEX:
            for (int i = 0; i < 4; ++i) { // i -> 3 action means skip
                node.edges.push_back({Action(search::ActionType::SINGLE_CARD_SELECT, i)});
            }
            break;

        case CardSelectTask::DISCOVERY:
            for (int i = 0; i < 3; ++i) {
                node.edges.push_back({Action(search::ActionType::SINGLE_CARD_SELECT, i)});
            }
            break;

        case CardSelectTask::DUAL_WIELD:
            setupCardOptionsHelper( node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand,
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::POWER || c.getType() == CardType::ATTACK;
                                    });
            break;

        case CardSelectTask::EXHUME:
            setupCardOptionsHelper(node, bc.cards.exhaustPile.begin(), bc.cards.exhaustPile.end(),
                                   [](const auto &c) { return c.getId() != CardId::EXHUME; });
            break;

        case CardSelectTask::EXHAUST_ONE:
            setupCardOptionsHelper(node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand);
            break;

        case CardSelectTask::FORETHOUGHT:
        case CardSelectTask::WARCRY:
            setupCardOptionsHelper(node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand);
            break;

        case CardSelectTask::HEADBUTT:
        case CardSelectTask::LIQUID_MEMORIES_POTION:
            setupCardOptionsHelper(node, bc.cards.discardPile.begin(), bc.cards.discardPile.end());
            break;

        case CardSelectTask::SECRET_TECHNIQUE:
            setupCardOptionsHelper(node, bc.cards.drawPile.begin(), bc.cards.drawPile.end(),
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::SKILL;
                                    });
            break;

        case CardSelectTask::SECRET_WEAPON:
            setupCardOptionsHelper(node, bc.cards.drawPile.begin(), bc.cards.drawPile.end(),
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::ATTACK;
                                    });
            break;

        case CardSelectTask::EXHAUST_MANY:
        case CardSelectTask::GAMBLE:
            // just dont deal with this right now
            node.edges.push_back({search::Action(search::ActionType::MULTI_CARD_SELECT, 0)});
            break;

        default:
#ifdef sts_asserts
            assert(false);
#endif
            break;
    }
}

double getNonMinionMonsterCurHpRatio(const BattleContext &bc) {
    int curHpTotal = 0;
    int maxHpTotal = 0;

    for (int i = 0; i < bc.monsters.monsterCount; ++i) {
        const auto &m = bc.monsters.arr[i];
        if (!m.hasStatus<MS::MINION>() && m.id != sts::MonsterId::INVALID) {
            curHpTotal += m.curHp;
            maxHpTotal += m.maxHp;
        }
    }

    if (curHpTotal == 0 || maxHpTotal == 0) {
        return 0;
    }

    return (double)curHpTotal / maxHpTotal;
}

double search::BattleScumSearcher2::evaluateEndState(const BattleContext &bc) {
    double potionScore = bc.potionCount * winPotionWeight();

    if (bc.outcome == Outcome::PLAYER_VICTORY) {
        return 100 * (35 + winHpWeight() * bc.player.curHp + potionScore - (bc.turn * 0.01));

    } else {
//        double statusScore =
//                (bc.player.getStatus<PS::STRENGTH>() * .5);
        const bool couldHaveSpikers = bc.encounter == MonsterEncounter::THREE_SHAPES || bc.encounter == MonsterEncounter::FOUR_SHAPES;
        double energyPenalty = bc.energyWasted * -0.2 * (couldHaveSpikers ? 0 : 1);
        double drawBonus = bc.cardsDrawn * 0.03;
        double aliveScore = bc.monsters.monstersAlive*-1;

        return (1-getNonMinionMonsterCurHpRatio(bc))*10 + aliveScore + energyPenalty + drawBonus + potionScore / 2 + (bc.turn * .2);
    }
}

struct LayerStruct {
    const search::BattleScumSearcher2::Node *node;
    BattleContext *bc;
    int edgeIdx;
};

typedef std::pair<search::BattleScumSearcher2::Edge, std::unique_ptr<const BattleContext>> EdgeInfo;

std::vector<EdgeInfo> getEdgesForLayer(const search::BattleScumSearcher2 &s, int layerNum) {
    if (layerNum <= 0) {
        return {};
    }

    std::vector<EdgeInfo> layerEdges;

    std::vector<LayerStruct> curStack { {&s.root, new BattleContext(*s.rootState), 0} };

    while (!curStack.empty()) {
        if (curStack.size() == layerNum) {
            for (const auto &edge : curStack.back().node->edges) {
                layerEdges.emplace_back(edge, new BattleContext(*curStack.back().bc));
            }
        }

       // curStack size less than layerNum
       const bool visitedAll = curStack.back().edgeIdx >= curStack.back().node->edges.size();
       if (visitedAll || curStack.size() == layerNum) {
           delete curStack.back().bc;
           curStack.pop_back();
           continue;
       }

        // visit next edge
        auto &nextIdx = curStack.back().edgeIdx;
        const auto action = curStack.back().node->edges[nextIdx].action;

        BattleContext bc(*curStack.back().bc);
        action.execute(bc);

        curStack.push_back( {&curStack.back().node->edges[nextIdx++].node, new BattleContext(bc), 0} );
    }

    return layerEdges;
}

void search::BattleScumSearcher2::printSearchTree(std::ostream &os, int levels) {
    std::vector<std::vector<EdgeInfo>> layerEdges;
    for (int depth = 1; depth <= levels; ++depth) {
        layerEdges.push_back(getEdgesForLayer(*this, depth));
    }

//    auto maxIt = std::max(layerEdges.begin(), layerEdges.end(), [](auto a, auto b) { return a->size() < b->size(); });
//    if (maxIt == layerEdges.end()) {
//        return;
//    }
//    // maxIt points to something
//    const auto maxSize = maxIt->size();
//    constexpr auto edgeWidth = 30;

    for (int depth = 0; depth < levels; ++depth) {
        for (const auto &x : layerEdges[depth]) {
            os << "(" << x.first.node.simulationCount << ")";
            x.first.action.printDesc(os, *x.second) << "\t";
        }
        std::cout << '\n';
    }

}

void search::BattleScumSearcher2::printSearchStack(std::ostream &os, bool skipLast) {
    for (int i = 0; i < actionStack.size(); ++i) {
        const auto &a = actionStack[i];
        os << std::hex << a.bits << '\n';
    }

    os.flush();

//    BattleContext curBc = *rootState;
//    os << "explorationParameter: " << explorationParameter << '\n';
//    os << "bestActionValue: " << bestActionValue << '\n';
//    os << "minActionValue: " << minActionValue << '\n';
//    os << "outcomePlayerHp: " << outcomePlayerHp << '\n';
//    os << "root node:\n";
//    os << curBc << "\n";
//
//    for (int i = 0; i < actionStack.size(); ++i) {
//        if (i < searchStack.size()) {
//            const auto &n = searchStack[i];
//            os << i << " nodeSearched: " << n->simulationCount << " { ";
//            for (const auto &edge : n->edges) {
//                os << "(" << edge.node.simulationCount << ")";
//                edge.action.printDesc(os, curBc) << " ";
//            }
//            os << "}\n";
//        }
//
//        const auto &a = actionStack[i];
//        os << i << " actionTaken: ";
//        a.printDesc(os, curBc) << '\n';
//
//        if (skipLast && (i + 1 >= actionStack.size())) {
//            break;
//        }
//
//        a.execute(curBc);
//        os << curBc << '\n';
//    }
//
//    os.flush();
}
