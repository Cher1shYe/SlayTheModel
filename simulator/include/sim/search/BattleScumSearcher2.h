//
// Created by keega on 9/17/2021.
//

#ifndef STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H
#define STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H

#include "sim/search/Action.h"

#include <functional>
#include <memory>
#include <random>
#include <unordered_map>
#include <iostream>
#include <limits>
#include <vector>

namespace sts::search {

    // When enabled, potion actions are only enumerated in boss encounters so
    // that the search stops spending potions on hallway fights.
    void setSavePotions(bool v);

    // 0: greedy playouts attack the highest-index targetable monster (legacy).
    // 1: greedy playouts focus the lowest-HP targetable monster.
    void setPlayoutTarget(int mode);
    int playoutTarget();

    // 0: static expert card ordering.  1: when no incoming damage would get
    // through, deprioritise skills so attacks (the win condition) come first.
    void setPlayoutOrder(int mode);
    void setDeterminize(int mode);
    void setPlayoutGuard(int mode);
    int playoutOrder();
    // >0: cycle the greedy rollout through `count` policy variants (target /
    // ordering / guard), one per simulation, so the search explores different
    // lines instead of replaying the same deterministic one.  0 = single policy.
    void setPlayoutVariants(int count);
    // Diagnostics: how often each portfolio variant produced the best line.
    void resetVariantStats();
    std::vector<std::int64_t> variantStats();

    // Weight of remaining HP inside a won battle (default 1.0).  Larger values
    // make the search trade win probability for health, smaller values make it
    // trade health for win probability.
    void setWinHpWeight(double w);
    double winHpWeight();

    // Value of one unused potion at the end of a won battle (default 4.0).
    void setWinPotionWeight(double w);
    double winPotionWeight();
    bool savePotionsEnabled();

    typedef std::function<double (const BattleContext&)> EvalFnc;

    // to find a solution to a battle with tree pruning
    struct BattleScumSearcher2 {
        struct Edge;
        struct Node {
            std::int64_t simulationCount = 0;
            double evaluationSum = 0;
            // virtual loss: simulations currently in flight below this node
            int pending = 0;
            // number of playouts through this node that ended in a won battle
            std::int64_t winCount = 0;
            std::vector<Edge> edges;
        };

        struct Edge {
            Action action;
            Node node;
        };

        std::unique_ptr<const BattleContext> rootState;
        Node root;

        EvalFnc evalFnc;
        double explorationParameter = 3*sqrt(2);

        // Root-prior PUCT: when usePuct is set, root edges are selected by
        // Q + cPuct * prior * sqrt(N) / (1 + n) and new root children are
        // sampled proportional to the prior instead of uniformly.
        bool usePuct = false;
        double cPuct = 3.0;
        // >0: blend the PUCT sqrt term toward classic UCB as the root
        // accumulates simulations (prior early, diversity late).
        double annealCount = 0.0;
        // 1: keep the UCB log schedule but allocate exploration by prior.
        int priorMode = 0;
        // 0: random playouts (native); 1: expert-greedy with epsilon noise.
        int playoutMode = 0;
        double playoutEpsilon = 0.0;
        // portfolio: which rollout variant the current step uses
        std::int64_t stepCounter = 0;
        int curVariant = 0;
        std::unordered_map<std::uint32_t, double> rootPriors;

        double bestActionValue = std::numeric_limits<double>::min();
        double minActionValue = std::numeric_limits<double>::max();
        int outcomePlayerHp = 0;

        std::vector<Action> bestActionSequence;
        std::default_random_engine randGen;

        std::vector<Node*> searchStack;
        std::vector<Action> actionStack;

        explicit BattleScumSearcher2(const BattleContext &bc, EvalFnc evalFnc=&evaluateEndState);

        // Root-parallel search: independent searchers must not share an RNG
        // stream, otherwise every thread explores the same tree.
        void setSeed(std::uint32_t s) { randGen.seed(s); }

        // public methods
        void search(int64_t simulations);
        void step();

        // private helpers
        void updateFromPlayout(const std::vector<Node*> &stack, const std::vector<Action> &actionStack, const BattleContext &endState);
        [[nodiscard]] bool isTerminalState(const BattleContext &bc) const;

        double evaluateEdge(const Node &parent, int edgeIdx);
        int selectBestEdgeToSearch(const Node &cur);
        int selectFirstActionForLeafNode(const Node &leafNode);

        void playoutRandom(BattleContext &state, std::vector<Action> &actionStack);
        void playoutGreedy(BattleContext &state, std::vector<Action> &actionStack);

        void enumerateActionsForNode(Node &node, const BattleContext &bc);
        void enumerateCardActions(Node &node, const BattleContext &bc);
        void enumeratePotionActions(Node &node, const BattleContext &bc);
        void enumerateCardSelectActions(Node &node, const BattleContext &bc);
        static double evaluateEndState(const BattleContext &bc);

        void printSearchTree(std::ostream &os, int levels);
        void printSearchStack(std::ostream &os, bool skipLast=false);
    };

    extern thread_local BattleScumSearcher2 *g_debug_scum_search;

}


#endif //STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H
