#pragma once
// Entity-structured public observation of a combat, for a combat policy/value
// network (Set Transformer over entities, pointer scoring of legal actions).
//
// Visibility follows public_combat_observation(): it emits a subset of the same
// public information, one token per visible object. Never emitted: card UIDs,
// the order of the draw pile beyond the known top cards, the stored order of the
// discard / exhaust piles and of pending choices (all sorted by
// card_canonical_less), monster move ids or AI state beyond the public counters,
// RNG state. Other characters' state (orbs, Osty, stars) is not encoded: Ironclad scope.
//
// Candidates are the legal actions in BattleContext::legal_actions() order.
#include "sts2/battle.h"

#include <cstdint>
#include <vector>

namespace sts2 {

constexpr int COMBAT_OBS_VERSION = 5;  // appended selection, potion queue and enchantments
constexpr int COMBAT_ENTITY_NUM = 112;  // all v4 columns remain at their original offsets
constexpr int COMBAT_CAND_NUM = 4;      // numeric features per candidate

enum class CombatEntity : std::uint8_t {
    PLAYER,         // player scalars, counters, pending-choice and active-play state (exactly one)
    ENCOUNTER,      // id = Encounter (exactly one)
    PLAYER_POWER,   // id = PowerId, nonzero player powers
    HAND_CARD,      // id = CardId
    DRAW_CARD,      // id = CardId; known top cards carry their position, the rest are sorted
    DISCARD_CARD,   // id = CardId, sorted
    EXHAUST_CARD,   // id = CardId, sorted
    CHOICE_CARD,    // id = CardId, cards offered by the pending choice, sorted
    ACTIVE_CARD,    // id = CardId, the card whose play is in progress
    MONSTER,        // id = MonsterId
    MONSTER_POWER,  // id = PowerId, nonzero powers of a monster (owner slot one-hot)
    POTION,         // id = PotionId (0 = empty slot)
    RELIC,          // id = RelicId
    COUNT
};

struct CombatObservation {
    std::vector<std::int32_t> kind;        // [N]
    std::vector<std::int32_t> id;          // [N]
    std::vector<float> num;                // [N * COMBAT_ENTITY_NUM]
    std::vector<std::int32_t> candType;    // [C] ActionType
    std::vector<std::int32_t> candTarget;  // [C] entity index or -1 (card / potion / choice)
    std::vector<std::int32_t> candTarget2; // [C] monster entity index or -1
    std::vector<float> candNum;            // [C * COMBAT_CAND_NUM]
};

int combat_id_vocab(CombatEntity kind);
CombatObservation combat_entity_observation(const BattleContext &bc);

}  // namespace sts2
