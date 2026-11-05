#pragma once
#include "sts2/common.h"

namespace sts2 {
// Each nested card play retains its own BeforeCardPlayed snapshot.
struct NecrobinderPlayState {
    int oblivion[4]{};
    int stage = 0;
    int damageTotal = 0;
};
// Public combat state. Osty's corpse remains present and can be summoned again.
struct NecrobinderState {
    bool ostyPresent = false;
    int ostyHp = 0;
    int ostyMaxHp = 0;
    int ostyStrength = 0;
    int ostyWeak = 0;
    int ostyVulnerable = 0;
    int ostyAttacksThisTurn = 0;
    int etherealPlayedThisCombat = 0;
    int extraDrawsThisTurn = 0;
    int deathsThisCombat = 0;
    bool doomAppliedThisTurn = false;
    bool dealingOstyDamage = false;
    bool generatingSoulbound = false;
    int summonAtTurnStart = 0;
    int cacophonyDamage[160]{};
    int cacophonyRemaining[160]{};
    int cacophonyCount = 0;
    std::uint16_t finishedUidsThisTurn[160]{};
    int finishedUidCount = 0;
    // Only deltas from original deck entities are synchronized back to the run.
    std::uint16_t scytheUids[160]{};
    int scytheGrowth[160]{};
    int scytheCount = 0;
};
}
