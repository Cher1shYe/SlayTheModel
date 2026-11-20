#pragma once

#include "sts2/battle.h"

namespace sts2 {

enum MonStateKind : std::uint8_t { MON_MOVE = 0, MON_RANDOM = 1, MON_COND = 2 };
enum MonOpCode : std::uint8_t {
    OP_NONE = 0, OP_BLOCK = 1, OP_POWER_SELF = 2, OP_POWER_PLAYER = 3,
    OP_CARD_DISCARD = 4, OP_CARD_DRAW = 5, OP_CARD_HAND = 6, OP_HEAL = 7,
    OP_SUMMON = 8, OP_POWER_OTHER = 9, OP_LOSE_HP = 10,
};
enum MonCondCode : std::uint8_t {
    COND_ALWAYS = 0, COND_ALONE = 1, COND_FRONT = 2, COND_OFF_BALANCE = 3,
    COND_SLUMBER = 4, COND_HALF_HP = 5, COND_HAS_ALLY = 6, COND_NO_ALLY = 7,
    COND_CAN_SUMMON = 8, COND_AMALGAM = 9, COND_NOT_FRONT = 10,
    COND_SLOT_FIRST = 11, COND_SLOT_SECOND = 12, COND_SLOT_THIRD = 13,
    COND_SLOT_FOURTH = 14,
    // Explicit codes for conditions that used to fall through to "always true".
    COND_ASLEEP = 15,          // Lagavulin: creature.has_power(ASLEEP)
    COND_KNOWLEDGE_CURSE = 16, // Knowledge Demon: curse_counter < 3
    COND_TEST_SUBJECT_REVIVE = 17,  // respawns < 2
    COND_FROG_CHARGED = 18,    // not charged and hp < max_hp/2
    COND_WRIGGLER_BITE = 19,   // slot in {0, 2}
    COND_WRIGGLER_WRIGGLE = 20,  // slot in {1, 3}
    COND_CAN_FABRICATE = 21,   // Fabricator.CanFabricate: living teammates < 4
    COND_CAN_LAY = 22,         // Ovicopter.CanLay: living teammates <= 3
};

struct MonIntentDef {
    std::uint8_t type;
    std::int16_t damage;
    std::uint8_t hits;
    std::int16_t deadlyDamage;  // A9 override, or -1 when no verified override
    std::int16_t deadlyHits;    // A9 hit-count override, or -1
    std::uint8_t displayType; // native IntentType; independent of execution grouping
};

struct VisibleMonsterIntent {
    std::uint8_t type;
    int damage;
    int hits;
};
// The currently displayed icons and numbers only; never a move/AI state identifier.
std::vector<VisibleMonsterIntent> visible_monster_intents(const BattleContext &bc, int slot);

// Observation A2: move identity and prediction. Step 0 is the move the enemy shows now
// (probability 1); step k is the distribution of its k-th following move, from the state
// machine's follow-ups, random-branch weights (repeat / max-times / cooldown rules on the
// move history) and conditional branches evaluated on the current battle. No RNG is read;
// the rolled future is never used. Read-only.
struct PredictedMove {
    int state;        // monster-local state index (MON_STATE_NAMES via monster_state_name)
    double p;
    int intentType;   // first intent's generator type (0 = attack)
    int damage;       // per-hit damage of the first attack against the player now (0 if none)
    int hits;
};
std::vector<std::vector<PredictedMove>> predict_monster_moves(const BattleContext &bc, int slot, int depth);
const char *monster_state_name(MonsterId id, int local);
struct MonOpDef { std::uint8_t op; std::int16_t a; std::int16_t b; std::int16_t deadlyAmount; };
struct MonBranchDef {
    std::uint8_t state;
    std::uint8_t repeat;
    std::uint8_t maxTimes;
    std::uint8_t cooldown;
    std::int16_t weight;
};
struct MonCondDef { std::uint8_t cond; std::uint8_t state; };
struct MonStateDef {
    std::uint8_t kind;
    std::uint8_t once;
    std::uint8_t follow;
    std::uint16_t intentOff[2];
    std::uint8_t intentN[2];
    std::uint16_t opOff[2];
    std::uint8_t opN[2];
    std::uint16_t branchOff;
    std::uint8_t branchN;
    // AI counter side effect when the state executes:
    // 0 none, 1 curse counter += 1, 2 charged flag = 1,
    // 3 extra multi-claw hits += 1, 4 respawn.
    std::uint8_t auxCode;
};
struct MonPowerDef { PowerId id; std::int16_t amount; std::int16_t deadlyAmount; };
struct MonInitialDef { std::uint8_t state; std::uint16_t weight; };
struct MonsterDef {
    const char *key;
    std::int16_t hpLo[2];
    std::int16_t hpHi[2];
    std::uint16_t innateOff[2];
    std::uint8_t innateCount[2];
    std::uint16_t stateOff;
    std::uint8_t stateCount;
    std::uint16_t initialOff;
    std::uint8_t initialCount;
    std::uint8_t reviveState;  // 255 if the monster never revives
    std::uint8_t multiClawState;  // 255 unless the hit count grows per use
};
struct EncounterPattern { std::uint8_t count; std::uint8_t ids[4]; std::int16_t weight; };
struct EncounterDef {
    const char *key;
    std::uint8_t act;
    std::uint16_t patternOff;
    std::uint8_t patternCount;
    std::uint16_t tags;
};

void setup_encounter(BattleContext &bc, Encounter enc, std::uint64_t encounterSeed);
// Native ModelId.Entry of the encounter (StringHelper.Slugify of its class name).
const char *encounter_native_entry(Encounter enc);
void spawn_monster(BattleContext &bc, MonsterId id, int slot = -1);
// Spawn at a given slot with a forced initial local state (-1 = table initial) and an
// HP range offset (Axebot respawns: MinInitialHp/MaxInitialHp + 10 x RespawnCount).
void spawn_monster_with(BattleContext &bc, MonsterId id, int slot, int initialState, int hpBonus);
// CreatureCmd.Add with the native slot choice. Returns the array index, or -1 when no slot
// is free (rules that need Encounter.Slots do nothing in an encounter without them).
enum class SlotRule : std::uint8_t {
    APPEND,       // no Encounter.Slots: after every existing enemy
    FIRST_FREE,   // Encounter.GetNextSlot
    LAST_FREE,    // Slots.LastOrDefault(free)
    NAMED,        // a fixed slot name (its index in Encounter.Slots)
};
int summon_enemy(BattleContext &bc, MonsterId id, SlotRule rule, int namedSlot = -1,
                 int initialState = -1, int hpBonus = 0);
void roll_intent(BattleContext &bc, Monster &m);
// CombatManager player-turn start: every enemy with a pending transition rolls its
// next move, in enemy order (one MonsterAi draw per random branch traversed).
void roll_pending_moves(BattleContext &bc);
void monster_act(BattleContext &bc, Monster &m);
// Aeonglass: Wither status cards generated for combat (each matched to the
// boss's WitherUpgradeCount via AfterCardGeneratedForCombat).
void add_withers(BattleContext &bc, int count, bool toHand);
int aeonglass_wither_upgrades(const BattleContext &bc);
int random_encounter_for_act(int act, Rng &rng, int kind = 0);
const MonsterDef &monster_def(MonsterId id);
const char *monster_name(MonsterId id);
const EncounterDef &encounter_def(int index);
std::uint16_t encounter_tags(Encounter enc);
bool encounters_share_tags(Encounter first, Encounter second);
const EncounterPattern &encounter_pattern(int index);
int encounter_count();

}  // namespace sts2
