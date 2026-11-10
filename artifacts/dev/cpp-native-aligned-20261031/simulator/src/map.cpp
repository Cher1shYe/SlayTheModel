// StandardActMap port. Mirrors MegaCrit.Sts2.Core.Map.StandardActMap,
// MapPathPruning and MapPostProcessing (v0.111.0 decompilation).
#include "sts2/map.h"

#include <algorithm>
#include <map>
#include <string>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

namespace sts2 {

namespace {

// MapPoint.Children / parents are .NET HashSet<MapPoint>: enumeration follows
// entry slots; Remove frees a slot and the next Add reuses the most recently
// freed one. Path finding and pruning depend on that order.
class SlotSet {
public:
    struct It {
        const std::vector<int> *slots;
        std::size_t i;
        void skip() { while (i < slots->size() && (*slots)[i] < 0) ++i; }
        int operator*() const { return (*slots)[i]; }
        It &operator++() { ++i; skip(); return *this; }
        bool operator!=(const It &o) const { return i != o.i; }
    };
    It begin() const { It it{&slots_, 0}; it.skip(); return it; }
    It end() const { return It{&slots_, slots_.size()}; }
    bool contains(int v) const { return std::find(slots_.begin(), slots_.end(), v) != slots_.end(); }
    void add(int v) {
        if (v < 0 || contains(v)) return;
        if (!free_.empty()) { slots_[free_.back()] = v; free_.pop_back(); }
        else slots_.push_back(v);
        ++count_;
    }
    void remove(int v) {
        for (std::size_t i = 0; i < slots_.size(); ++i)
            if (slots_[i] == v) { slots_[i] = -1; free_.push_back(static_cast<int>(i)); --count_; return; }
    }
    std::size_t size() const { return count_; }
    bool empty() const { return count_ == 0; }
    int front() const { return *begin(); }
    std::vector<int> to_vector() const { std::vector<int> out; for (int v : *this) out.push_back(v); return out; }
private:
    std::vector<int> slots_;
    std::vector<int> free_;
    std::size_t count_ = 0;
};

struct GNode {
    int col = 0;
    int row = 0;
    MapPointType type = MapPointType::UNASSIGNED;
    SlotSet children;
    SlotSet parents;
    bool alive = true;
    bool fixedType = false;  // MapPoint.CanBeModified == false
};

struct Gen {
    int mapLength = 0;
    std::vector<GNode> nodes;
    int grid[MAP_MAX_ROWS][MAP_WIDTH];
    int startIdx = -1;
    int bossIdx = -1;
    std::vector<int> startPoints;
};

int boss_col(const Gen &g) { return MAP_WIDTH / 2; }

int get_point(Gen &g, int col, int row) {
    if (col < 0 || col >= MAP_WIDTH || row < 0 || row > g.mapLength) return -1;
    if (col == boss_col(g) && row == g.mapLength) return g.bossIdx;
    if (col == boss_col(g) && row == 0) return g.startIdx;
    return g.grid[row][col];
}

int get_or_create(Gen &g, int col, int row) {
    const int existing = get_point(g, col, row);
    if (existing >= 0) return existing;
    GNode n;
    n.col = col;
    n.row = row;
    g.nodes.push_back(n);
    const int idx = static_cast<int>(g.nodes.size()) - 1;
    g.grid[row][col] = idx;
    return idx;
}

void add_child(Gen &g, int parent, int child) {
    if (parent < 0 || child < 0 || parent == child) return;
    g.nodes[parent].children.add(child);   // MapPoint.AddChildPoint
    g.nodes[child].parents.add(parent);
}

void remove_child(Gen &g, int parent, int child) {
    g.nodes[parent].children.remove(child);  // MapPoint.RemoveChildPoint
    g.nodes[child].parents.remove(parent);
}

bool has_invalid_crossover(Gen &g, int current, int targetCol) {
    const int direction = targetCol - g.nodes[current].col;
    if (direction == 0 || direction == 7) return false;
    const int row = g.nodes[current].row;
    if (row < 0 || row >= MAP_MAX_ROWS || targetCol < 0 || targetCol >= MAP_WIDTH) return false;
    const int blocker = g.grid[row][targetCol];
    if (blocker < 0) return false;
    for (const int child : g.nodes[blocker].children) {
        const int childDirection = g.nodes[child].col - g.nodes[blocker].col;
        if (childDirection == -direction) return true;
    }
    return false;
}

void path_generate(Gen &g, Rng &rng, int startIdx) {
    int current = startIdx;
    while (g.nodes[current].row < g.mapLength - 1) {
        const int col = g.nodes[current].col;
        const int minCol = std::max(0, col - 1);
        const int maxCol = std::min(col + 1, MAP_WIDTH - 1);
        int dirs[3] = {-1, 0, 1};
        rng.shuffle(dirs, 3);
        int nextCol = -1;
        for (const int d : dirs) {
            const int target = d < 0 ? minCol : (d > 0 ? maxCol : col);
            if (!has_invalid_crossover(g, current, target)) {
                nextCol = target;
                break;
            }
        }
        if (nextCol < 0) nextCol = col;  // defensive; reference throws
        const int next = get_or_create(g, nextCol, g.nodes[current].row + 1);
        add_child(g, current, next);
        current = next;
    }
}

void for_each_row(Gen &g, int row, const std::function<void(int)> &fn) {
    if (row < 0 || row > g.mapLength) return;
    for (int col = 0; col < MAP_WIDTH; ++col) {
        const int idx = get_point(g, col, row);
        if (idx >= 0) fn(idx);
    }
}

std::vector<int> all_map_points(Gen &g) {
    std::vector<int> out;
    for (int col = 0; col < MAP_WIDTH; ++col) {
        for (int row = 1; row < g.mapLength; ++row) {
            if (g.grid[row][col] >= 0) out.push_back(g.grid[row][col]);
        }
    }
    return out;
}

bool is_valid_for_lower(MapPointType type, int row) {
    // StandardActMap.IsValidForLower: coord.row < 6.
    if (row < 6) {
        return type != MapPointType::REST && type != MapPointType::ELITE;
    }
    return true;
}

bool is_valid_for_upper(MapPointType type, int row, int mapLength) {
    if (row >= mapLength - 3) return type != MapPointType::REST;
    return true;
}

bool is_restricted(MapPointType type) {
    return type == MapPointType::ELITE || type == MapPointType::REST ||
           type == MapPointType::TREASURE || type == MapPointType::SHOP;
}

bool is_sibling_restricted(MapPointType type) {
    return type == MapPointType::REST || type == MapPointType::MONSTER ||
           type == MapPointType::UNKNOWN || type == MapPointType::ELITE ||
           type == MapPointType::SHOP;
}

bool is_valid_point_type(Gen &g, MapPointType type, int idx) {
    const GNode &n = g.nodes[idx];
    if (!is_valid_for_lower(type, n.row)) return false;
    if (!is_valid_for_upper(type, n.row, g.mapLength)) return false;
    if (is_restricted(type)) {
        for (const int p : n.parents) {
            if (g.nodes[p].type == type) return false;
        }
        for (const int c : n.children) {
            if (g.nodes[c].type == type) return false;
        }
    }
    if (is_sibling_restricted(type)) {
        for (const int p : n.parents) {
            for (const int c : g.nodes[p].children) {
                if (c == idx) continue;
                if (g.nodes[c].type == type) return false;
            }
        }
    }
    return true;
}

MapPointType next_valid_type(Gen &g, std::vector<MapPointType> &queue, int idx) {
    const int n = static_cast<int>(queue.size());
    for (int i = 0; i < n; ++i) {
        const MapPointType t = queue.front();
        queue.erase(queue.begin());
        if (is_valid_point_type(g, t, idx)) return t;
        queue.push_back(t);
    }
    return MapPointType::UNASSIGNED;
}

// MapPoint.CompareTo orders by (col, row); StableShuffle sorts, then
// UnstableShuffle (Fisher-Yates from the end).
void stable_shuffle_points(Gen &g, Rng &rng, std::vector<int> &points) {
    std::sort(points.begin(), points.end(), [&](int a, int b) {
        if (g.nodes[a].col != g.nodes[b].col) return g.nodes[a].col < g.nodes[b].col;
        return g.nodes[a].row < g.nodes[b].row;
    });
    for (int i = static_cast<int>(points.size()) - 1; i > 0; --i) {
        const int j = rng.next_int(0, i);
        std::swap(points[i], points[j]);
    }
}

// AssignRemainingTypesToRandomPoints: up to three passes, each shuffling the
// points that are still Unassigned.
void assign_remaining_types(Gen &g, Rng &rng, std::vector<MapPointType> &queue) {
    for (int pass = 0; pass < 3 && !queue.empty(); ++pass) {
        std::vector<int> points;
        for (const int idx : all_map_points(g))
            if (g.nodes[idx].type == MapPointType::UNASSIGNED) points.push_back(idx);
        stable_shuffle_points(g, rng, points);
        for (const int idx : points) {
            if (queue.empty()) break;
            g.nodes[idx].type = next_valid_type(g, queue, idx);
        }
    }
}

void assign_point_types(Gen &g, Rng &rng, int numElites, int numShops, int numUnknowns,
                        int numRests) {
    auto fix = [&](int idx, MapPointType type) { g.nodes[idx].type = type; g.nodes[idx].fixedType = true; };
    for_each_row(g, g.mapLength - 1, [&](int idx) { fix(idx, MapPointType::REST); });
    for_each_row(g, g.mapLength - 7, [&](int idx) { fix(idx, MapPointType::TREASURE); });
    for_each_row(g, 1, [&](int idx) { fix(idx, MapPointType::MONSTER); });

    std::vector<MapPointType> queue;
    for (int i = 0; i < numRests; ++i) queue.push_back(MapPointType::REST);
    for (int i = 0; i < numShops; ++i) queue.push_back(MapPointType::SHOP);
    for (int i = 0; i < numElites; ++i) queue.push_back(MapPointType::ELITE);
    for (int i = 0; i < numUnknowns; ++i) queue.push_back(MapPointType::UNKNOWN);
    assign_remaining_types(g, rng, queue);
    for (const int idx : all_map_points(g))
        if (g.nodes[idx].type == MapPointType::UNASSIGNED) g.nodes[idx].type = MapPointType::MONSTER;
    g.nodes[g.bossIdx].type = MapPointType::BOSS;
    g.nodes[g.startIdx].type = MapPointType::ANCIENT;
}

// ---- pruning ---------------------------------------------------------------

bool is_in_map(Gen &g, int idx) {
    const GNode &n = g.nodes[idx];
    if (n.type == MapPointType::ANCIENT) return true;
    if (n.type == MapPointType::BOSS) return true;
    if (n.row < 0 || n.row > g.mapLength || n.col < 0 || n.col >= MAP_WIDTH) return false;
    return g.grid[n.row][n.col] == idx;
}

bool is_removed(Gen &g, int idx) {
    const GNode &n = g.nodes[idx];
    if (n.row < 0 || n.row > g.mapLength || n.col < 0 || n.col >= MAP_WIDTH) return true;
    return g.grid[n.row][n.col] != idx;
}

void remove_point(Gen &g, int idx) {
    GNode &n = g.nodes[idx];
    if (n.row >= 1 && n.row < g.mapLength) {
        if (g.grid[n.row][n.col] == idx) g.grid[n.row][n.col] = -1;
    }
    g.startPoints.erase(std::remove(g.startPoints.begin(), g.startPoints.end(), idx),
                        g.startPoints.end());
    const std::vector<int> kids = n.children.to_vector();
    const std::vector<int> pars = n.parents.to_vector();
    for (const int c : kids) remove_child(g, idx, c);
    for (const int p : pars) remove_child(g, p, idx);
    n.alive = false;
}

std::vector<std::vector<int>> find_all_paths(Gen &g, int current) {
    std::vector<std::vector<int>> out;
    if (g.nodes[current].type == MapPointType::BOSS) {
        out.push_back({current});
        return out;
    }
    for (const int child : g.nodes[current].children) {
        auto sub = find_all_paths(g, child);
        for (auto &p : sub) {
            std::vector<int> full;
            full.reserve(p.size() + 1);
            full.push_back(current);
            full.insert(full.end(), p.begin(), p.end());
            out.push_back(std::move(full));
        }
    }
    return out;
}

bool valid_segment_start(Gen &g, int idx) {
    if (static_cast<int>(g.nodes[idx].children.size()) <= 1) return g.nodes[idx].row == 0;
    return true;
}

bool valid_segment_end(Gen &g, int idx) {
    return g.nodes[idx].parents.size() >= 2;
}

struct SegmentKey {
    std::uint8_t col0 = 0;
    std::uint8_t row0 = 0;
    std::uint8_t col1 = 0;
    std::uint8_t row1 = 0;
    std::uint8_t len = 0;
    std::uint8_t types[MAP_MAX_ROWS + 2]{};
};

struct SegmentKeyHash {
    std::size_t operator()(const SegmentKey &k) const {
        std::uint64_t h = 1469598103934665603ull;
        auto mix = [&h](std::uint8_t b) {
            h ^= b;
            h *= 1099511628211ull;
        };
        mix(k.col0); mix(k.row0); mix(k.col1); mix(k.row1); mix(k.len);
        for (int i = 0; i < k.len; ++i) mix(k.types[i]);
        return static_cast<std::size_t>(h);
    }
};

struct SegmentKeyEq {
    bool operator()(const SegmentKey &a, const SegmentKey &b) const {
        if (a.col0 != b.col0 || a.row0 != b.row0 || a.col1 != b.col1 ||
            a.row1 != b.row1 || a.len != b.len) {
            return false;
        }
        for (int i = 0; i < a.len; ++i) {
            if (a.types[i] != b.types[i]) return false;
        }
        return true;
    }
};

// GenerateSegmentKey: "row-endCol,endRow-" for row-0 starts, otherwise
// "col,row-endCol,endRow-", then the point types joined by ','.
std::string segment_key_string(const SegmentKey &k) {
    std::string key = k.row0 == 0 ? std::to_string(k.row0) + "-"
                                  : std::to_string(k.col0) + "," + std::to_string(k.row0) + "-";
    key += std::to_string(k.col1) + "," + std::to_string(k.row1) + "-";
    for (int i = 0; i < k.len; ++i) {
        if (i) key += ",";
        key += std::to_string(k.types[i]);
    }
    return key;
}

std::vector<std::vector<std::vector<int>>> find_matching_segments(Gen &g) {
    const auto paths = find_all_paths(g, g.startIdx);
    // MapPathPruning.FindMatchingSegments keeps a SortedDictionary<string, ...>
    // (StringComparer.Ordinal): duplicate groups are returned in ordinal key
    // order. Group with a compact key; build the string only for duplicates.
    std::unordered_map<SegmentKey, int, SegmentKeyHash, SegmentKeyEq> index;
    std::vector<SegmentKey> keys;
    std::vector<std::vector<std::vector<int>>> buckets;
    for (const auto &path : paths) {
        for (int i = 0; i + 1 < static_cast<int>(path.size()); ++i) {
            if (!valid_segment_start(g, path[i])) continue;
            for (int j = 2; j < static_cast<int>(path.size()) - i; ++j) {
                const int end = path[i + j];
                if (!valid_segment_end(g, end)) continue;
                const int len = j + 1;
                SegmentKey key;
                const GNode &a = g.nodes[path[i]];
                const GNode &b = g.nodes[end];
                key.col0 = static_cast<std::uint8_t>(a.col);
                key.row0 = static_cast<std::uint8_t>(a.row);
                key.col1 = static_cast<std::uint8_t>(b.col);
                key.row1 = static_cast<std::uint8_t>(b.row);
                key.len = static_cast<std::uint8_t>(len);
                for (int k = 0; k < len; ++k) key.types[k] = static_cast<std::uint8_t>(g.nodes[path[i + k]].type);
                // Row-0 keys omit the start column (always the same point).
                if (key.row0 == 0) key.col0 = 0;
                auto it = index.find(key);
                if (it == index.end()) {
                    index.emplace(key, static_cast<int>(buckets.size()));
                    keys.push_back(key);
                    buckets.emplace_back();
                    buckets.back().emplace_back(path.begin() + i, path.begin() + i + len);
                    continue;
                }
                auto &bucket = buckets[it->second];
                bool overlap = false;
                for (const auto &existing : bucket) {
                    for (int k = 1; k + 1 < len && !overlap; ++k) overlap = existing[k] == path[i + k];
                    if (overlap) break;
                }
                if (!overlap) bucket.emplace_back(path.begin() + i, path.begin() + i + len);
            }
        }
    }
    std::vector<std::pair<std::string, int>> duplicates;
    for (int b = 0; b < static_cast<int>(buckets.size()); ++b)
        if (buckets[b].size() > 1) duplicates.emplace_back(segment_key_string(keys[b]), b);
    std::sort(duplicates.begin(), duplicates.end());
    std::vector<std::vector<std::vector<int>>> out;
    for (const auto &d : duplicates) out.push_back(std::move(buckets[d.second]));
    return out;
}

bool prune_segment(Gen &g, const std::vector<int> &seg) {
    bool result = false;
    for (int i = 0; i + 1 < static_cast<int>(seg.size()); ++i) {
        const int p = seg[i];
        if (!is_in_map(g, p)) return true;
        bool skip = g.nodes[p].children.size() > 1 || g.nodes[p].parents.size() > 1;
        if (!skip) {
            for (const int parent : g.nodes[p].parents) {
                if (g.nodes[parent].children.size() == 1 && !is_removed(g, parent)) {
                    skip = true;
                    break;
                }
            }
        }
        if (skip) continue;
        bool hasBranch = false;
        for (int k = i; k < static_cast<int>(seg.size()); ++k) {
            if (g.nodes[seg[k]].children.size() > 1 && g.nodes[seg[k]].parents.size() == 1) {
                hasBranch = true;
                break;
            }
        }
        if (hasBranch) continue;
        if (g.nodes[seg.back()].parents.size() == 1) return false;
        bool strayChild = false;
        for (const int child : g.nodes[p].children) {
            if (std::find(seg.begin(), seg.end(), child) != seg.end()) continue;
            if (g.nodes[child].parents.size() == 1) {
                strayChild = true;
                break;
            }
        }
        if (!strayChild) {
            remove_point(g, p);
            result = true;
        }
    }
    return result;
}

int prune_all_but_last(Gen &g, std::vector<std::vector<int>> &matches) {
    int num = 0;
    // The reference stops once all but one segment have been PRUNED (num), not
    // at the last index: if an earlier segment cannot be pruned, the last one
    // is still tried.
    for (int i = 0; i < static_cast<int>(matches.size()); ++i) {
        if (num == static_cast<int>(matches.size()) - 1) return num;
        if (prune_segment(g, matches[i])) ++num;
    }
    return num;
}

// BreakAParentChildRelationshipInAnySegment: the first segment with any
// breakable link has all of its breakable links removed.
bool break_relationship(Gen &g, std::vector<std::vector<int>> &matches) {
    for (auto &seg : matches) {
        bool broke = false;
        for (int i = 0; i + 1 < static_cast<int>(seg.size()); ++i) {
            const int p = seg[i];
            if (g.nodes[p].children.size() >= 2) {
                const int child = seg[i + 1];
                if (g.nodes[child].parents.size() != 1) {
                    remove_child(g, p, child);
                    broke = true;
                }
            }
        }
        if (broke) return true;
    }
    return false;
}

bool prune_paths(Gen &g, Rng &rng, std::vector<std::vector<std::vector<int>>> groups) {
    for (auto &group : groups) {
        for (int i = static_cast<int>(group.size()) - 1; i > 0; --i) {
            const int j = rng.next_int(0, i);
            std::swap(group[i], group[j]);
        }
        if (prune_all_but_last(g, group) != 0) return true;
        if (break_relationship(g, group)) return true;
    }
    return false;
}

void prune_duplicate_segments(Gen &g, Rng &rng) {
    int iterations = 0;
    auto groups = find_matching_segments(g);
    while (prune_paths(g, rng, groups)) {
        if (++iterations > 50) break;  // reference throws; we stop pruning
        groups = find_matching_segments(g);
    }
}

// MapPathPruning.RepairPointType: replace modifiable Monsters until the type
// reaches its target count again.
bool repair_point_type(Gen &g, Rng &rng, MapPointType type, int target) {
    int have = 0;
    for (const int idx : all_map_points(g)) have += g.nodes[idx].type == type;
    int missing = target - have;
    if (missing <= 0) return false;
    std::vector<int> monsters;
    for (const int idx : all_map_points(g))
        if (g.nodes[idx].type == MapPointType::MONSTER && !g.nodes[idx].fixedType) monsters.push_back(idx);
    stable_shuffle_points(g, rng, monsters);
    bool changed = false;
    for (const int idx : monsters) {
        if (missing == 0) break;
        if (is_valid_point_type(g, type, idx)) {
            g.nodes[idx].type = type;
            --missing;
            changed = true;
        }
    }
    return changed;
}

// MapPathPruning.PruneAndRepair.
void prune_and_repair(Gen &g, Rng &rng, int numElites, int numShops, int numUnknowns, int numRests) {
    for (int i = 0; i < 3; ++i) {
        prune_duplicate_segments(g, rng);
        bool changed = repair_point_type(g, rng, MapPointType::SHOP, numShops);
        changed |= repair_point_type(g, rng, MapPointType::ELITE, numElites);
        changed |= repair_point_type(g, rng, MapPointType::REST, numRests);
        changed |= repair_point_type(g, rng, MapPointType::UNKNOWN, numUnknowns);
        if (!changed) break;
    }
}

// ---- post processing -------------------------------------------------------

bool is_column_empty(Gen &g, int col) {
    for (int row = 0; row <= g.mapLength; ++row) {
        if (get_point(g, col, row) >= 0) return false;
    }
    return true;
}

void center_grid(Gen &g) {
    const bool leftEmpty = is_column_empty(g, 0) && is_column_empty(g, 1);
    const bool rightEmpty = is_column_empty(g, MAP_WIDTH - 1) && is_column_empty(g, MAP_WIDTH - 2);
    int shift = 0;
    if (leftEmpty && !rightEmpty) shift = -1;
    else if (!leftEmpty && rightEmpty) shift = 1;
    if (shift == 0) return;

    int newGrid[MAP_MAX_ROWS][MAP_WIDTH];
    for (auto &rowArr : newGrid) {
        for (int &v : rowArr) v = -1;
    }
    for (int row = 0; row < g.mapLength; ++row) {
        if (shift > 0) {
            for (int col = MAP_WIDTH - 1; col >= 0; --col) {
                const int idx = g.grid[row][col];
                const int nc = col + shift;
                if (nc >= 0 && nc < MAP_WIDTH) {
                    newGrid[row][nc] = idx;
                    if (idx >= 0) g.nodes[idx].col = nc;
                }
            }
        } else {
            for (int col = 0; col < MAP_WIDTH; ++col) {
                const int idx = g.grid[row][col];
                const int nc = col + shift;
                if (nc >= 0 && nc < MAP_WIDTH) {
                    newGrid[row][nc] = idx;
                    if (idx >= 0) g.nodes[idx].col = nc;
                }
            }
        }
    }
    for (int row = 0; row <= g.mapLength; ++row) {
        for (int col = 0; col < MAP_WIDTH; ++col) g.grid[row][col] = newGrid[row][col];
    }
}

int compute_gap(const std::vector<int> &rowNodes, const Gen &g, int candidate, int currentIdx) {
    int best = 2147483647;
    for (const int other : rowNodes) {
        if (other == currentIdx) continue;
        best = std::min(best, std::abs(candidate - g.nodes[other].col));
    }
    return best;
}

void spread_adjacent_map_points(Gen &g) {
    for (int row = 1; row < g.mapLength; ++row) {
        std::vector<int> nodes;
        for (int col = 0; col < MAP_WIDTH; ++col) {
            const int idx = g.grid[row][col];
            if (idx >= 0) nodes.push_back(idx);
        }
        bool changed;
        do {
            changed = false;
            for (const int idx : nodes) {
                const int col = g.nodes[idx].col;
                bool allowed[MAP_WIDTH];
                for (bool &b : allowed) b = true;
                for (const int parent : g.nodes[idx].parents) {
                    const int pc = g.nodes[parent].col;
                    for (int c = 0; c < MAP_WIDTH; ++c) {
                        if (std::abs(c - pc) > 1) allowed[c] = false;
                    }
                }
                for (const int child : g.nodes[idx].children) {
                    const int cc = g.nodes[child].col;
                    for (int c = 0; c < MAP_WIDTH; ++c) {
                        if (std::abs(c - cc) > 1) allowed[c] = false;
                    }
                }
                int bestCol = col;
                int bestGap = compute_gap(nodes, g, col, idx);
                for (int c = 0; c < MAP_WIDTH; ++c) {
                    if (!allowed[c] || c == col) continue;
                    if (g.grid[row][c] >= 0 && g.grid[row][c] != idx) continue;
                    const int gap = compute_gap(nodes, g, c, idx);
                    if (gap > bestGap) {
                        bestCol = c;
                        bestGap = gap;
                    }
                }
                if (bestCol != col) {
                    g.grid[row][col] = -1;
                    g.grid[row][bestCol] = idx;
                    g.nodes[idx].col = bestCol;
                    changed = true;
                }
            }
        } while (changed);
    }
}

void straighten_paths(Gen &g) {
    for (int row = 1; row < g.mapLength; ++row) {
        for (int col = 0; col < MAP_WIDTH; ++col) {
            const int idx = g.grid[row][col];
            if (idx < 0) continue;
            if (g.nodes[idx].parents.size() != 1 || g.nodes[idx].children.size() != 1) continue;
            const int parent = g.nodes[idx].parents.front();
            const int child = g.nodes[idx].children.front();
            const int pc = g.nodes[parent].col;
            const int cc = g.nodes[child].col;
            const bool left = col < cc && col < pc;
            const bool right = col > cc && col > pc;
            if (left && col < MAP_WIDTH - 1 && g.grid[row][col + 1] < 0) {
                g.nodes[idx].col = col + 1;
                g.grid[row][col] = -1;
                g.grid[row][col + 1] = idx;
                // The reference loop's next column is the moved node itself,
                // which is examined again.
            } else if (right && col > 0 && g.grid[row][col - 1] < 0) {
                g.nodes[idx].col = col - 1;
                g.grid[row][col] = -1;
                g.grid[row][col - 1] = idx;
            }
        }
    }
}

void bake(Gen &g, ActMap &map) {
    for (auto &rowArr : map.index) {
        for (auto &v : rowArr) v = -1;
    }
    map.rooms = static_cast<std::int8_t>(g.mapLength - 1);
    map.mapLength = static_cast<std::int8_t>(g.mapLength);
    map.pointCount = 0;
    map.startIdx = -1;
    map.bossIdx = -1;
    map.secondBossIdx = -1;

    // Node identity is (col,row); removed nodes are dropped.
    int remap[MAP_MAX_POINTS];
    for (int &v : remap) v = -1;
    for (int i = 0; i < static_cast<int>(g.nodes.size()); ++i) {
        const GNode &n = g.nodes[i];
        if (!n.alive) continue;
        if (n.row >= 0 && n.row <= g.mapLength) {
            if (is_removed(g, i) && n.type != MapPointType::ANCIENT &&
                n.type != MapPointType::BOSS) {
                continue;
            }
        }
        if (map.pointCount >= MAP_MAX_POINTS) break;
        const int pi = map.pointCount++;
        remap[i] = pi;
        MapNode &mn = map.nodes[pi];
        mn = MapNode();
        mn.type = static_cast<std::int8_t>(n.type);
        map.index[n.row][n.col] = static_cast<std::int8_t>(pi);
        if (i == g.startIdx) map.startIdx = static_cast<std::int8_t>(pi);
        if (i == g.bossIdx) map.bossIdx = static_cast<std::int8_t>(pi);
    }
    for (int i = 0; i < static_cast<int>(g.nodes.size()); ++i) {
        if (remap[i] < 0) continue;
        MapNode &mn = map.nodes[remap[i]];
        for (const int c : g.nodes[i].children) {
            if (remap[c] < 0) continue;
            if (mn.childCount < MAP_MAX_EDGES) mn.children[mn.childCount++] = static_cast<std::uint8_t>(remap[c]);
        }
        for (const int p : g.nodes[i].parents) {
            if (remap[p] < 0) continue;
            if (mn.parentCount < MAP_MAX_EDGES) mn.parents[mn.parentCount++] = static_cast<std::uint8_t>(remap[p]);
        }
    }
}

// ActModel.GetMapPointTypes (Underdocks uses Overgrowth's values).
void map_point_type_counts(Rng &mapRng, int actIndex, int ascension, int &numElites, int &numShops,
                           int &numUnknowns, int &numRests) {
    numElites = ascension >= 1 ? 8 : 5;
    numShops = 3;
    if (actIndex == 0) {
        numRests = mapRng.next_gaussian_int(7, 1, 6, 7);
        numUnknowns = mapRng.next_gaussian_int(12, 1, 10, 14);
    } else if (actIndex == 1) {
        numRests = mapRng.next_gaussian_int(6, 1, 6, 7);
        numUnknowns = mapRng.next_gaussian_int(12, 1, 10, 14) - 1;
    } else {
        numRests = mapRng.next_int_range(5, 7);
        numUnknowns = mapRng.next_gaussian_int(12, 1, 10, 14) - 1;
    }
    if (ascension >= 6) --numRests;
}

// ---- SpoilsActMap ------------------------------------------------------------

struct SpoilsGen {
    Gen &g;
    int treasureRow;
};

std::pair<int, int> spoils_allowed_columns(const Gen &g, int treasureRow, int row) {
    const int center = MAP_WIDTH / 2;
    const int toTreasure = std::abs(row - treasureRow);
    const int toEnd = g.mapLength - 1 - row;
    const int endWidth = std::min(center, std::max(0, toEnd) + 1);
    const int half = std::min(center, std::min(toTreasure, endWidth));
    return {std::max(0, center - half), std::min(MAP_WIDTH - 1, center + half)};
}

bool spoils_invalid_crossover(Gen &g, int current, int targetCol) {
    const int direction = targetCol - g.nodes[current].col;
    if (direction == 0) return false;
    const int blocker = get_point(g, targetCol, g.nodes[current].row);
    if (blocker < 0) return false;
    for (const int child : g.nodes[blocker].children)
        if (g.nodes[child].col - g.nodes[blocker].col == -direction) return true;
    return false;
}

int spoils_next_col(Gen &g, Rng &rng, int current, int treasureRow) {
    const int row = g.nodes[current].row + 1;
    const int col = g.nodes[current].col;
    const auto [minCol, maxCol] = spoils_allowed_columns(g, treasureRow, row);
    const int center = MAP_WIDTH / 2;
    std::vector<int> dirs = {-1, 0, 1};
    const int distance = treasureRow - g.nodes[current].row;
    if (distance > 3 || distance <= 0) {
        rng.shuffle(dirs.data(), 3);  // StableShuffle of an already sorted list
    } else {
        // BuildCenteredPriorityList
        dirs.clear();
        const int toward = center > col ? 1 : center < col ? -1 : 0;
        if (toward != 0) dirs.push_back(toward);
        dirs.push_back(0);
        if (toward != 0) dirs.push_back(-toward);
        if (std::find(dirs.begin(), dirs.end(), -1) == dirs.end()) dirs.push_back(-1);
        if (std::find(dirs.begin(), dirs.end(), 1) == dirs.end()) dirs.push_back(1);
    }
    for (const int d : dirs) {
        const int next = d < 0 ? std::max(0, col - 1) : d > 0 ? std::min(MAP_WIDTH - 1, col + 1) : col;
        if (next < minCol || next > maxCol || spoils_invalid_crossover(g, current, next)) continue;
        const int point = get_point(g, next, row);
        const bool pointOk = point < 0 || g.nodes[point].parents.contains(current) || g.nodes[point].parents.size() < 3;
        const bool currentOk = current == g.startIdx || g.nodes[current].children.size() < 3 ||
                               (point >= 0 && g.nodes[current].children.contains(point));
        if (pointOk && currentOk) return next;
    }
    int fallback = std::clamp(center, minCol, maxCol);
    if (std::abs(fallback - col) > 1)
        fallback = std::clamp(col + (fallback > col ? 1 : -1), minCol, maxCol);
    if (spoils_invalid_crossover(g, current, fallback)) fallback = std::clamp(col, minCol, maxCol);
    return fallback;
}

}  // namespace

void generate_spoils_act_map(ActMap &map, std::uint64_t runSeed, int actIndex, int ascension) {
    const int rooms = actIndex == 0 ? 15 : (actIndex == 1 ? 14 : 13);
    Rng rng(runSeed, "spoils_map");
    Gen g;
    g.mapLength = rooms + 1;
    for (auto &rowArr : g.grid) for (int &v : rowArr) v = -1;
    int numElites, numShops, numUnknowns, numRests;
    map_point_type_counts(rng, actIndex, ascension, numElites, numShops, numUnknowns, numRests);
    const int treasureRow = g.mapLength - 7;
    GNode startNode; startNode.col = MAP_WIDTH / 2; startNode.row = 0;
    g.nodes.push_back(startNode); g.startIdx = 0;
    GNode bossNode; bossNode.col = MAP_WIDTH / 2; bossNode.row = g.mapLength;
    g.nodes.push_back(bossNode); g.bossIdx = 1;

    // GenerateHourglassMap.
    std::vector<int> startPoints;
    for (int i = 0; i < 7; ++i) {
        int start = get_or_create(g, rng.next_int_exclusive(MAP_WIDTH), 1);
        if (i == 1)
            while (std::find(startPoints.begin(), startPoints.end(), start) != startPoints.end())
                start = get_or_create(g, rng.next_int_exclusive(MAP_WIDTH), 1);
        startPoints.push_back(start);
        int current = start;
        while (g.nodes[current].row < g.mapLength - 1) {
            const int next = get_or_create(g, spoils_next_col(g, rng, current, treasureRow), g.nodes[current].row + 1);
            add_child(g, current, next);
            current = next;
        }
    }
    g.startPoints = startPoints;
    const int treasure = get_or_create(g, MAP_WIDTH / 2, treasureRow);
    g.nodes[treasure].type = MapPointType::TREASURE;
    g.nodes[treasure].fixedType = true;
    std::vector<int> rowPoints;
    for (int col = 0; col < MAP_WIDTH; ++col) if (g.grid[treasureRow][col] >= 0) rowPoints.push_back(g.grid[treasureRow][col]);
    for (const int stray : rowPoints) {
        if (stray == treasure) continue;
        for (const int parent : g.nodes[stray].parents.to_vector()) { remove_child(g, parent, stray); add_child(g, parent, treasure); }
        for (const int child : g.nodes[stray].children.to_vector()) { remove_child(g, stray, child); add_child(g, treasure, child); }
        g.grid[treasureRow][g.nodes[stray].col] = -1;
        g.nodes[stray].alive = false;
    }
    for_each_row(g, g.mapLength - 1, [&](int idx) { add_child(g, idx, g.bossIdx); });
    for_each_row(g, 1, [&](int idx) { add_child(g, g.startIdx, idx); });

    // AssignPointTypes (no treasure row; the hourglass Treasure is fixed).
    for_each_row(g, g.mapLength - 1, [&](int idx) { g.nodes[idx].type = MapPointType::REST; g.nodes[idx].fixedType = true; });
    for_each_row(g, 1, [&](int idx) { g.nodes[idx].type = MapPointType::MONSTER; g.nodes[idx].fixedType = true; });
    std::vector<MapPointType> queue;
    for (int i = 0; i < numRests; ++i) queue.push_back(MapPointType::REST);
    for (int i = 0; i < numShops; ++i) queue.push_back(MapPointType::SHOP);
    for (int i = 0; i < numElites; ++i) queue.push_back(MapPointType::ELITE);
    for (int i = 0; i < numUnknowns; ++i) queue.push_back(MapPointType::UNKNOWN);
    assign_remaining_types(g, rng, queue);
    for (const int idx : all_map_points(g))
        if (g.nodes[idx].type == MapPointType::UNASSIGNED) g.nodes[idx].type = MapPointType::MONSTER;
    g.nodes[g.bossIdx].type = MapPointType::BOSS;
    g.nodes[g.startIdx].type = MapPointType::ANCIENT;
    prune_and_repair(g, rng, numElites, numShops, numUnknowns, numRests);  // no post-processing
    bake(g, map);
}

void generate_act_map(ActMap &map, Rng &mapRng, int actIndex, int ascension) {
    const int rooms = actIndex == 0 ? 15 : (actIndex == 1 ? 14 : 13);
    Gen g;
    g.mapLength = rooms + 1;
    for (auto &rowArr : g.grid) {
        for (int &v : rowArr) v = -1;
    }

    // Room type counts (per-act RNG consumption order from the reference).
    int numElites, numShops, numUnknowns, numRests;
    map_point_type_counts(mapRng, actIndex, ascension, numElites, numShops, numUnknowns, numRests);

    GNode startNode;
    startNode.col = MAP_WIDTH / 2;
    startNode.row = 0;
    g.nodes.push_back(startNode);
    g.startIdx = 0;
    GNode bossNode;
    bossNode.col = MAP_WIDTH / 2;
    bossNode.row = g.mapLength;
    g.nodes.push_back(bossNode);
    g.bossIdx = 1;

    std::vector<int> startPoints;
    for (int i = 0; i < 7; ++i) {
        int start = get_or_create(g, mapRng.next_int_exclusive(MAP_WIDTH), 1);
        if (i == 1) {
            while (std::find(startPoints.begin(), startPoints.end(), start) != startPoints.end()) {
                start = get_or_create(g, mapRng.next_int_exclusive(MAP_WIDTH), 1);
            }
        }
        startPoints.push_back(start);
        path_generate(g, mapRng, start);
    }
    g.startPoints = startPoints;

    for_each_row(g, g.mapLength - 1, [&](int idx) { add_child(g, idx, g.bossIdx); });
    for_each_row(g, 1, [&](int idx) { add_child(g, g.startIdx, idx); });

    assign_point_types(g, mapRng, numElites, numShops, numUnknowns, numRests);
    prune_and_repair(g, mapRng, numElites, numShops, numUnknowns, numRests);
    center_grid(g);
    spread_adjacent_map_points(g);
    straighten_paths(g);
    bake(g, map);
    if (ascension >= 10 && actIndex == 2 && map.bossIdx >= 0 &&
        map.mapLength + 1 < MAP_MAX_ROWS && map.pointCount < MAP_MAX_POINTS) {
        const int second = map.pointCount++;
        map.secondBossIdx = static_cast<std::int8_t>(second);
        MapNode &node = map.nodes[second];
        node = MapNode();
        node.type = static_cast<std::int8_t>(MapPointType::BOSS);
        node.parents[0] = static_cast<std::uint8_t>(map.bossIdx);
        node.parentCount = 1;
        MapNode &first = map.nodes[map.bossIdx];
        first.children[first.childCount++] = static_cast<std::uint8_t>(second);
        map.index[map.mapLength + 1][MAP_WIDTH / 2] = static_cast<std::int8_t>(second);
    }
}

void generate_golden_path_map(ActMap &map) {
    // GoldenPathActMap._defaultPointTypes, native 41cef1ea single-player.
    constexpr MapPointType types[] = {
        MapPointType::ANCIENT, MapPointType::MONSTER, MapPointType::UNKNOWN,
        MapPointType::MONSTER, MapPointType::REST, MapPointType::MONSTER,
        MapPointType::REST, MapPointType::UNKNOWN, MapPointType::TREASURE,
        MapPointType::UNKNOWN, MapPointType::TREASURE, MapPointType::UNKNOWN,
        MapPointType::SHOP, MapPointType::ELITE, MapPointType::REST,
        MapPointType::ELITE, MapPointType::REST, MapPointType::BOSS
    };
    map = ActMap{};
    for (auto &row : map.index) for (auto &node : row) node = -1;
    map.rooms = 16;
    map.mapLength = 17;
    map.startIdx = 0;
    map.bossIdx = 17;
    map.pointCount = 18;
    for (int row = 0; row < 18; ++row) {
        map.index[row][MAP_WIDTH / 2] = static_cast<std::int8_t>(row);
        auto &node = map.nodes[row];
        node.type = static_cast<std::int8_t>(types[row]);
        if (row > 0) { node.parentCount = 1; node.parents[0] = row - 1; }
        if (row < 17) { node.childCount = 1; node.children[0] = row + 1; }
    }
}

const char *map_point_name(MapPointType type) {
    switch (type) {
        case MapPointType::UNKNOWN: return "UNKNOWN";
        case MapPointType::SHOP: return "SHOP";
        case MapPointType::TREASURE: return "TREASURE";
        case MapPointType::REST: return "REST";
        case MapPointType::MONSTER: return "MONSTER";
        case MapPointType::ELITE: return "ELITE";
        case MapPointType::BOSS: return "BOSS";
        case MapPointType::ANCIENT: return "ANCIENT";
        default: return "UNASSIGNED";
    }
}

}  // namespace sts2
