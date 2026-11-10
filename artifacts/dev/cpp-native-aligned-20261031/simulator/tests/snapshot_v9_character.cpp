// Snapshot v9: character state round-trips through serialize/restore, and
// out-of-range counts in a malformed blob are rejected atomically.
#include "sts2/observe.h"
#include <cstring>
#include <iostream>
#include <memory>

using namespace sts2;

namespace {
int failures = 0;
void check(bool ok, const char *label) {
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
}  // namespace

int main() {
    auto source = std::make_unique<RunContext>();
    source->init(42, 0);
    source->screen = RunScreen::COMBAT;
    source->inBattle = true;
    source->battle.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS, 42,
                        source->deck, source->deckCount, 0, 80, 80);
    auto &b = source->battle;
    b.defect.orbCapacity = 3;
    b.defect.orbCount = 2;
    b.defect.orbs[0] = {OrbId::FROST, 0};
    b.defect.orbs[1] = {OrbId::DARK, 9};
    b.necro.ostyPresent = true;
    b.necro.ostyHp = 7;
    b.necro.ostyMaxHp = 10;
    b.regent.stars = 4;

    const auto blob = source->serialize();
    check(static_cast<unsigned char>(blob[4]) == 10, "snapshot version 10");
    auto restored = std::make_unique<RunContext>();
    check(RunContext::restore(blob, *restored), "restore character state");
    check(restored->serialize() == blob, "round trip identical");
    check(public_observation(*restored) == public_observation(*source), "observation preserved");

    // Byte offset of a BattleContext field inside the blob (12-byte header).
    const char *base = reinterpret_cast<const char *>(source.get());
    auto offset = [&](const void *field) {
        return 12 + (reinterpret_cast<const char *>(field) - base);
    };
    auto rejects = [&](const void *field, int value, const char *label) {
        std::string bad = blob;
        std::memcpy(&bad[offset(field)], &value, sizeof(value));
        const auto before = restored->serialize();
        check(!RunContext::restore(bad, *restored), label);
        check(restored->serialize() == before, "rejected restore leaves destination unchanged");
    };
    rejects(&b.defect.orbCount, MAX_ORBS + 1, "orb count above capacity");
    rejects(&b.defect.orbCapacity, -1, "negative orb capacity");
    rejects(&b.necro.cacophonyCount, 161, "Cacophony count overflow");
    rejects(&b.necro.ostyHp, 11, "Osty hp above max");
    rejects(&b.regent.monologueCount, 161, "Monologue count overflow");
    rejects(&b.silent.nightmareCount, 161, "Nightmare count overflow");
    rejects(&b.suspendedPlayCount, MAX_PLAY_DEPTH + 1, "suspended play overflow");
    rejects(&b.autoPlayQueueCount, MAX_PILE + 1, "auto-play queue overflow");
    rejects(&b.turnFlow.stage, 99, "unknown turn flow stage");
    {
        std::string bad = blob;
        bad[offset(&b.defect.orbs[0].id)] = 9;
        check(!RunContext::restore(bad, *restored), "unknown orb id");
    }
    std::cout << "snapshot v9 character: failures=" << failures << '\n';
    return failures ? 1 : 0;
}
