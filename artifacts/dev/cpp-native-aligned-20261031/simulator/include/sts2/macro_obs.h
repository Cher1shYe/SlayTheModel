#pragma once
// Entity-structured public observation for the out-of-combat ("macro")
// policy, plus a fixed-MCTS combat driver.
//
// The flat public_observation() remains the reference for what a player can
// see; this view reuses the same visibility rules but emits one token per
// visible object instead of fixed one-hot slots:
//   * entities: (kind, id, numeric[MACRO_ENTITY_NUM]) per visible object;
//   * edges:    map links as (parent entity, child entity);
//   * candidates: one per legal RunAction, pointing at the entity (or two)
//     the action acts on, so the policy scores actions by referring to them.
// Hidden state (draw order, unopened card rewards, sealed Crystal Sphere
// cells, RNG, relic bags, unrevealed map content) is never emitted.
#include "sts2/run.h"

#include <cstdint>
#include <vector>

namespace sts2 {

constexpr int MACRO_OBS_VERSION = 1;
constexpr int MACRO_ENTITY_NUM = 80;   // numeric features per entity (zero padded)
constexpr int MACRO_CAND_NUM = 4;      // numeric features per candidate

enum class MacroEntity : std::uint8_t {
    GLOBAL,        // run resources and counters (exactly one)
    CONTEXT,       // current screen / selector / event state (exactly one; id = event + 1)
    DECK_CARD,     // master deck, one per card (duplicates kept)
    RELIC,         // owned relics
    POTION,        // physical potion slots (id 0 = empty slot)
    MAP_NODE,      // current act map (id = MapPointType)
    BOSS,          // known boss encounter(s) (id = Encounter)
    OFFER_CARD,    // reward / shop / generated-grid / stolen / stored cards
    OFFER_RELIC,   // shop / reward / event offer / pending-obtain relics
    OFFER_POTION,  // shop / reward potions
    REWARD,        // gold rewards and unopened card-reward slots
    EVENT_OPTION,  // id = event * MAX_EVENT_CHOICES + option
    SPHERE_CELL,   // Crystal Sphere cell (id = revealed item type + 1, 0 = sealed/empty)
    COUNT
};

struct MacroObservation {
    std::vector<std::int32_t> kind;        // [N]
    std::vector<std::int32_t> id;          // [N]
    std::vector<float> num;                // [N * MACRO_ENTITY_NUM]
    std::vector<std::int32_t> edges;       // [E * 2] entity indices (parent, child)
    std::vector<std::int32_t> candType;    // [C] RunActionType
    std::vector<std::int32_t> candIndex;   // [C] RunAction index (execution descriptor)
    std::vector<std::int32_t> candTarget;  // [C] entity index or -1
    std::vector<std::int32_t> candTarget2; // [C] secondary entity index or -1
    std::vector<float> candNum;            // [C * MACRO_CAND_NUM]
    std::int32_t phase = 0;                // screen * 2 + (selector open ? 1 : 0)
};

// Vocabulary size of the id field for each entity kind.
int macro_id_vocab(MacroEntity kind);
// Number of distinct phase ids.
constexpr int MACRO_PHASES = 2 * 9;

MacroObservation macro_observation(const RunContext &rc);

struct CombatDriveResult {
    int decisions = 0;     // searched decisions (more than one legal action)
    int forced = 0;        // single-legal-action steps
    long long simulations = 0;
    bool ok = true;        // false if MCTS returned an illegal/empty plan
};

// Plays the current combat to its end with the fixed hidden-information MCTS:
// each decision searches from the public state with resampled hidden state
// (resample=true), executes only the first action, then searches again.
// Search seeds are seedBase + 7919 * decisionIndex, independent of game RNG.
CombatDriveResult play_combat_mcts(RunContext &rc, int normalSimulations, int bossSimulations,
                                   double exploration, std::uint32_t seedBase,
                                   int decisionIndexStart, double rolloutEpsilon,
                                   double potionWeight, int maxSteps = 20000);

}  // namespace sts2
