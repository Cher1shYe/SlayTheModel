#pragma once
#include "sts2/common.h"
namespace sts2 {
struct RegentPlayState {
    int stage=0;
    int monologue[160]{};
    int monologueCount=0;
    std::uint16_t selected[10]{};
    int selectedCount=0;
};
struct RegentState {
    int stars=0;
    int starsGainedThisTurn=0;
    int generatedThisCombat=0;
    int hitsGivenThisTurn[4]{};
    int cardsFinishedThisTurn=0;
    int skillsFinishedThisTurn=0;
    int voidFormManualPlays=0;
    bool paleBlueActivated=false;
    bool endTurnRequested=false;
    int monologueAmounts[160]{};
    int monologueApplied[160]{};
    int monologueCount=0;
    int orbitAmounts[160]{};
    int orbitEnergy[160]{};
    int orbitCount=0;
};
}
