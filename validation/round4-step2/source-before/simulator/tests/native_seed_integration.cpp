// Seed plumbing and snapshot compatibility; not a full-run native parity claim.
#include "sts2/run.h"
#include <iostream>
#include <memory>
#include <stdexcept>
#include <type_traits>

using namespace sts2;
static void require(bool value, const char *label) { if (!value) throw std::runtime_error(label); }
static bool same_rng(const Rng &a, const Rng &b) {
    return a.counter == b.counter && a.state() == b.state();
}
static int event_id(const char *name) {
    for (int i = 0; i < event_count(); ++i) {
        const EventInfo *info = event_info(i);
        if (info && std::strcmp(info->name, name) == 0) return i;
    }
    throw std::runtime_error("Missing event fixture");
}
int main() {
    static_assert(std::is_trivially_copyable<Rng>::value, "RNG must remain snapshot-copyable");
    static_assert(std::is_trivially_copyable<RunContext>::value, "RunContext snapshot is a POD image");
    auto raw = std::make_unique<RunContext>();
    auto text = std::make_unique<RunContext>();
    auto wide = std::make_unique<RunContext>();
    raw->init(22, 0);
    text->init_seed(" 22 ", 0);
    wide->init(0x100000016ull, 0);
    require(raw->seed == 22 && wide->seed == 0x100000016ull, "raw uint64 seed identity");
    require(text->seed == 1884361412985708340ull, "native hash of game seed 22");
    require(raw->seed != text->seed, "raw seed does not get implicitly hashed");
    require(same_rng(wide->runRng[RNG_SHUFFLE], Rng(wide->seed, "shuffle")), "64-bit named shuffle stream");
    require(same_rng(wide->playerRng[PRNG_SHOPS], Rng(wide->seed, "shops")), "single-player slot zero shops");
    require(!same_rng(wide->runRng[RNG_SHUFFLE], raw->runRng[RNG_SHUFFLE]), "no high seed truncation");
    event_begin(*wide, event_id("TABLET_OF_TRUTH"), false);
    require(same_rng(wide->eventRng, Rng(wide->seed, "TABLET_OF_TRUTH")), "single-player event slot zero");
    event_begin(*wide, event_id("DENSE_VEGETATION"), false);
    Rng denseRng(wide->seed, "DENSE_VEGETATION");
    require(wide->eventData[0] == denseRng.next_int(61, 99), "Dense CalculateVars uses shared event stream");
    require(same_rng(wide->eventRng, denseRng), "shared event stream after CalculateVars");
    auto restored = std::make_unique<RunContext>();
    const auto snapshot = text->serialize();
    require(static_cast<unsigned char>(snapshot[4]) == 8, "snapshot version 8");
    require(RunContext::restore(snapshot, *restored), "restore native RNG snapshot");
    require(restored->seed == text->seed, "snapshot preserves 64-bit seed");
    for (int stream=0; stream<RNG_COUNT; ++stream)
        require(same_rng(restored->runRng[stream], text->runRng[stream]), "snapshot preserves every run stream");
    auto old = snapshot; old[4] = 7;
    const auto before = restored->serialize();
    require(!RunContext::restore(old, *restored), "reject snapshot version 7");
    require(restored->serialize() == before, "rejected snapshot leaves destination unchanged");
    std::cout << "native seed integration: raw/string/high bits/streams/snapshot passed\n";
}
