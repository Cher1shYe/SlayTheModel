#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>

#include "sts2/battle.h"
#include "sts2/run.h"
#include "sts2/search.h"

using namespace sts2;

static int make_deck(Card *deck) {
    int n = 0;
    for (int i = 0; i < 5; ++i) deck[n++] = make_card(CardId::STRIKE_IRONCLAD, false, static_cast<std::uint16_t>(n + 1));
    for (int i = 0; i < 4; ++i) deck[n++] = make_card(CardId::DEFEND_IRONCLAD, false, static_cast<std::uint16_t>(n + 1));
    deck[n++] = make_card(CardId::BASH, false, static_cast<std::uint16_t>(n + 1));
    return n;
}

static void bench_combat(int playouts, int enc, int sims) {
    Card deck[16];
    const int deckN = make_deck(deck);

    int wins = 0;
    long long turns = 0;
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < playouts; ++i) {
        BattleContext bc;
        bc.init(static_cast<Encounter>(enc), static_cast<std::uint32_t>(i + 1), deck, deckN, 0);
        Rng rng(static_cast<std::uint32_t>(i * 7919 + 13));
        while (bc.outcome == Outcome::UNDECIDED) {
            if (sims > 0) {
                SearchResult r = search(bc, sims, 1.5, 0.05, static_cast<std::uint32_t>(i + 99));
                if (r.actions.empty()) break;
                int best = 0;
                for (int k = 1; k < static_cast<int>(r.visits.size()); ++k) {
                    if (r.visits[k] > r.visits[best]) best = k;
                }
                bc.step(r.actions[best]);
            } else {
                Action a = greedy_action(bc, rng, 0.05);
                if (!bc.step(a)) break;
            }
        }
        if (bc.outcome == Outcome::PLAYER_VICTORY) ++wins;
        turns += bc.turn;
    }
    const auto end = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(end - start).count();
    std::printf("combats=%d encounter=%d sims=%d seconds=%.3f combats_per_s=%.1f "
                "avg_turns=%.2f win_rate=%.3f\n",
                playouts, enc, sims, seconds, playouts / seconds,
                static_cast<double>(turns) / playouts, static_cast<double>(wins) / playouts);
}

static void bench_runs(int runs) {
    int wins = 0;
    long long floors = 0;
    long long combats = 0;
    const auto start = std::chrono::steady_clock::now();
    double initSec = 0.0;
    double combatSec = 0.0;
    long long combatSteps = 0;
    for (int i = 0; i < runs; ++i) {
        RunContext rc;
        auto t0 = std::chrono::steady_clock::now();
        rc.init(static_cast<std::uint32_t>(i + 1), 0);
        initSec += std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        Rng rng(static_cast<std::uint32_t>(i * 31337 + 7));
        int guard = 0;
        while (!rc.is_over() && guard++ < 10000) {
            if (rc.screen == RunScreen::COMBAT) {
                t0 = std::chrono::steady_clock::now();
                Action a = greedy_action(rc.battle, rng, 0.05);
                if (!rc.step_combat(a)) break;
                combatSec += std::chrono::duration<double>(
                    std::chrono::steady_clock::now() - t0).count();
                ++combatSteps;
                if (rc.screen != RunScreen::COMBAT) ++combats;
                continue;
            }
            const std::vector<RunAction> legal = rc.legal_actions();
            if (legal.empty()) break;
            RunAction pick = legal[0];
            switch (rc.screen) {
                case RunScreen::CARD_REWARD:
                    pick = rc.deckCount < 25 ? legal[0] : legal.back();
                    break;
                case RunScreen::REST:
                    pick = rc.hp * 10 < rc.maxHp * 6 && !legal.empty()
                               ? RunAction{RunActionType::REST_HEAL, 0}
                               : legal.back();
                    break;
                case RunScreen::SHOP:
                    pick = legal.back();
                    break;
                default:
                    break;
            }
            if (!rc.step(pick)) break;
        }
        if (rc.won) ++wins;
        floors += rc.floor;
    }
    const auto end = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(end - start).count();
    std::printf("runs=%d seconds=%.3f runs_per_s=%.1f avg_floor=%.1f win_rate=%.3f combats=%lld\n",
                runs, seconds, runs / seconds, static_cast<double>(floors) / runs,
                static_cast<double>(wins) / runs, combats);
    std::printf("init=%.2fms/run combat=%.3fs (%lld steps, %.1f us/step) other=%.2fms/run\n",
                1000.0 * initSec / runs, combatSec, combatSteps,
                1e6 * combatSec / (combatSteps > 0 ? combatSteps : 1),
                1000.0 * (seconds - initSec - combatSec) / runs);
}

static void bench_maps(int count) {
    const auto start = std::chrono::steady_clock::now();
    std::size_t nodes = 0;
    for (int i = 0; i < count; ++i) {
        ActMap map;
        Rng rng(static_cast<std::uint32_t>(i + 1), "act_1_map");
        generate_act_map(map, rng, i % 3);
        nodes += map.pointCount;
    }
    const auto end = std::chrono::steady_clock::now();
    const double seconds = std::chrono::duration<double>(end - start).count();
    std::printf("maps=%d seconds=%.3f maps_per_s=%.1f avg_nodes=%.1f\n",
                count, seconds, count / seconds, static_cast<double>(nodes) / count);
}

int main(int argc, char **argv) {
    if (argc > 1 && std::strcmp(argv[1], "run") == 0) {
        bench_runs(argc > 2 ? std::atoi(argv[2]) : 1000);
        return 0;
    }
    if (argc > 1 && std::strcmp(argv[1], "map") == 0) {
        bench_maps(argc > 2 ? std::atoi(argv[2]) : 1000);
        return 0;
    }
    const int playouts = argc > 1 ? std::atoi(argv[1]) : 10000;
    const int enc = argc > 2 ? std::atoi(argv[2]) : 23;  // Shrinker Beetle (weak)
    const int sims = argc > 3 ? std::atoi(argv[3]) : 0;
    bench_combat(playouts, enc, sims);
    return 0;
}
