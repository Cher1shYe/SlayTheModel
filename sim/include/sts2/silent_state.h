#pragma once
#include "sts2/common.h"

namespace sts2 {
// Kept in each persistent ActivePlay frame, including nested Sly plays.
struct SilentPlayState {
    int afterimage = 0;
    int serpentForm = 0;
    int strangle[4]{};
    int stage = 0;
    int amount = 0;
    int drawn = 0;
    int firstDrawnType = -1;
    Card selected[10]{};
    int selectedCount = 0;
};
// All fields are public combat facts; queued Nightmare copies retain the exact
// selected instance's modifiers and enchantment, with the affliction cleared.
struct SilentState {
    int discardedThisTurn = 0;
    int drawnThisCombat = 0;
    int attacksFinishedThisTurn = 0;
    int skillsFinishedThisTurn = 0;
    int shivsFinishedThisTurn = 0;
    Card nightmareCards[160]{};
    int nightmareAmounts[160]{};
    int nightmareCount = 0;
    int huntRewards = 0;
    Card turnStartSelected[10]{};
    int turnStartSelectedCount = 0;
};
}
