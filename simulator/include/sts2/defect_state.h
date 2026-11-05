#pragma once

#include <cstdint>

namespace sts2 {

enum class OrbId : std::uint8_t { NONE, LIGHTNING, FROST, DARK, PLASMA, GLASS };
constexpr int MAX_ORBS = 10;

struct OrbState {
    OrbId id = OrbId::NONE;
    // Dark's accumulated evoke damage; Glass's decreasing base passive damage.
    int value = 0;
};

struct DefectPlayState {
    int storm = 0;
    int subroutine = 0;
    int stage = 0;
    int cursor = 0;
    int drawDepth = 0;
    std::uint16_t drawnUids[160]{};
    int drawnCount = 0;
};

struct DefectState {
    OrbState orbs[MAX_ORBS]{};
    int orbCount = 0;
    int orbCapacity = 0;
    int lightningChanneled = 0;
    int firstSeriesStartedThisTurn = 0;
    int finishedThisTurn = 0;
    int energySpentThisTurn = 0;
    int zeroEnergyAttacksStartedThisTurn = 0;
    int feralReturnsThisTurn = 0;
    int statusesDrawnThisTurn = 0;
    int drawDepth = 0;
    std::uint16_t powerOrder[32]{};
    int powerOrderCount = 0;
    // Genetic Algorithm changes DeckVersion even if the combat card exhausts.
    std::uint16_t geneticUids[160]{};
    int geneticGrowth[160]{};
    int geneticCount = 0;
};

}  // namespace sts2
