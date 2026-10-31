// Act map generation, ported from MegaCrit.Sts2.Core.Map.StandardActMap.
#pragma once

#include "sts2/common.h"

namespace sts2 {

// Content identity is separate from the run's zero-based act position.
enum class ActType : std::uint8_t { OVERGROWTH, HIVE, GLORY, UNDERDOCKS };

enum class MapPointType : std::uint8_t {
    UNASSIGNED,
    UNKNOWN,
    SHOP,
    TREASURE,
    REST,
    MONSTER,
    ELITE,
    BOSS,
    ANCIENT
};

constexpr int MAP_WIDTH = 7;
constexpr int MAP_MAX_ROWS = 18;  // Golden Path: 16 rooms + start + boss.
constexpr int MAP_MAX_POINTS = 119;  // Network node slots remain unchanged.
constexpr int MAP_MAX_EDGES = 8;

struct MapNode {
    std::int8_t type = static_cast<std::int8_t>(MapPointType::UNASSIGNED);
    std::uint8_t childCount = 0;
    std::uint8_t children[MAP_MAX_EDGES]{};
    std::uint8_t parentCount = 0;
    std::uint8_t parents[MAP_MAX_EDGES]{};
};

struct ActMap {
    std::int8_t rooms = 0;      // number of room rows
    std::int8_t mapLength = 0;  // rooms + 1; boss row == mapLength
    std::int8_t startIdx = -1;
    std::int8_t bossIdx = -1;
    std::int8_t secondBossIdx = -1;  // A10 final act, one row above the first boss
    std::uint8_t pointCount = 0;
    std::int8_t index[MAP_MAX_ROWS][MAP_WIDTH];  // row/col -> node index or -1
    MapNode nodes[MAP_MAX_POINTS];

    [[nodiscard]] int at(int row, int col) const {
        if (row < 0 || row >= MAP_MAX_ROWS || col < 0 || col >= MAP_WIDTH) return -1;
        return index[row][col];
    }
};

// Generates the act map exactly as StandardActMap does (paths, type counts,
// pruning, centering, spreading, straightening). mapRng is advanced.
void generate_act_map(ActMap &map, Rng &mapRng, int actIndex, int ascension = 0);
void generate_golden_path_map(ActMap &map);

const char *map_point_name(MapPointType type);

}  // namespace sts2
