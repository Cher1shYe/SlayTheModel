// The self-damage rule state must survive search clones / snapshots and remain
// public without disclosing hidden RNG state or draw order.
#include "sts2/observe.h"
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstring>
#include <iostream>
#include <memory>

using namespace sts2;

static void rejects_atomically(const std::string &blob, RunContext &out) {
    const auto before = out.serialize();
    assert(!RunContext::restore(blob, out));
    assert(out.serialize() == before);
}

int main() {
    auto source = std::make_unique<RunContext>();
    source->init(42, 0);
    source->screen = RunScreen::COMBAT;
    source->inBattle = true;
    source->battle.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 42,
                       source->deck, source->deckCount, 0, 80, 80);
    auto &b = source->battle;
    b.add_player_power(PowerId::INFERNO, 18);
    b.add_player_power(PowerId::CRIMSON_MANTLE, 17);
    b.player.crimsonMantleSelfDamage = 2;
    b.player.infernoSelfDamage = 3;
    b.player.infernoBeforeCrimsonMantle = true;
    const auto observation = public_combat_observation(b);
    assert(observation.size() == PUBLIC_COMBAT_OBS_DIM);
    assert(observation[observation.size()-3] == 0.2f);
    assert(observation[observation.size()-2] == 0.3f);
    assert(observation.back() == 1.0f);
    const auto runObservation = public_observation(*source);
    assert(runObservation.size() == PUBLIC_OBS_DIM);
    assert(std::equal(observation.begin(), observation.end(),
                      runObservation.begin()+PUBLIC_RUN_DIM));

    for (int field = 0; field < 3; ++field) {
        BattleContext distinct = b;
        if (field == 0) ++distinct.player.crimsonMantleSelfDamage;
        if (field == 1) ++distinct.player.infernoSelfDamage;
        if (field == 2) distinct.player.infernoBeforeCrimsonMantle = false;
        const auto different = public_combat_observation(distinct);
        assert(different != observation);
        assert(std::equal(observation.begin(), observation.end()-3, different.begin()));
    }
    for (unsigned seed = 0; seed < 32; ++seed) {
        BattleContext sampled = b;
        sampled.resample_hidden(seed);
        assert(public_combat_observation(sampled) == observation);
    }

    auto restored = std::make_unique<RunContext>();
    const auto blob = source->serialize();
    assert(static_cast<unsigned char>(blob[4]) == 8);
    assert(RunContext::restore(blob, *restored));
    assert(restored->serialize() == blob);
    assert(public_observation(*restored) == runObservation);
    auto copied = std::make_unique<RunContext>(*source);
    source->battle.start_player_turn();
    restored->battle.start_player_turn();
    copied->battle.start_player_turn();
    assert(public_combat_observation(source->battle) == public_combat_observation(restored->battle));
    assert(public_combat_observation(source->battle) == public_combat_observation(copied->battle));

    auto old = blob; old[4] = 7;
    rejects_atomically(old, *restored);
    const auto playerOffset = 12 + reinterpret_cast<const char *>(&source->battle.player)
                                - reinterpret_cast<const char *>(source.get());
    for (auto offset : {offsetof(Player, crimsonMantleSelfDamage), offsetof(Player, infernoSelfDamage)}) {
        for (int invalid : {-1, 10000001}) {
            auto bad = blob;
            std::memcpy(bad.data()+playerOffset+offset, &invalid, sizeof(invalid));
            rejects_atomically(bad, *restored);
        }
    }
    auto badBool = blob;
    badBool[playerOffset+offsetof(Player, infernoBeforeCrimsonMantle)] = 2;
    rejects_atomically(badBool, *restored);

    // Starting the next combat cannot retain a prior battle's power state.
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 43,
           source->deck, source->deckCount, 0, 80, 80);
    assert(b.player.crimsonMantleSelfDamage == 0 && b.player.infernoSelfDamage == 0);
    assert(!b.player.infernoBeforeCrimsonMantle);
    std::cout << "step1 state contract: public counters/order, 32 resamplings, clone/restore continuation, "
                 "old version and malformed state rejection, new-combat reset passed\n";
}
