#include "sts2/monsters.h"
#include "sts2/relics.h"

#include <cstring>

namespace sts2 {
#include "sts2/monsters_generated.inc"

const MonsterDef &monster_def(MonsterId id) {
    const int i = static_cast<int>(id);
    if (i <= 0 || i >= static_cast<int>(MonsterId::COUNT)) return MONSTER_DEFS[0];
    return MONSTER_DEFS[i];
}

const char *monster_name(MonsterId id) {
    const MonsterDef &d = monster_def(id);
    return d.key ? d.key : "UNKNOWN";
}

const EncounterDef &encounter_def(int index) {
    return ENCOUNTER_DEFS[index];
}

std::uint16_t encounter_tags(Encounter enc) {
    const int index = static_cast<int>(enc);
    if (index <= 0 || index >= static_cast<int>(Encounter::COUNT)) return 0;
    return ENCOUNTER_DEFS[index].tags;
}

bool encounters_share_tags(Encounter first, Encounter second) {
    return (encounter_tags(first) & encounter_tags(second)) != 0;
}

const EncounterPattern &encounter_pattern(int index) {
    return ENC_PATTERNS[index];
}

int encounter_count() { return static_cast<int>(Encounter::COUNT); }

static const MonStateDef &state_of(const MonsterDef &def, int local) {
    return MON_STATES[def.stateOff + local];
}

static int alive_allies(const BattleContext &bc, int selfIdx) {
    int n = 0;
    for (int i = 0; i < bc.monsterCount; ++i) {
        if (i != selfIdx && bc.monsters[i].alive) ++n;
    }
    return n;
}

static bool has_other_amalgam(const BattleContext &bc, int selfIdx) {
    for (int i = 0; i < bc.monsterCount; ++i) {
        if (i != selfIdx && bc.monsters[i].alive &&
            bc.monsters[i].id == MonsterId::TORCH_HEAD_AMALGAM) {
            return true;
        }
    }
    return false;
}

// Living creatures in the enemy list (Creature.IsAlive: dead illusions waiting to
// revive do not count).
static int living_enemies(const BattleContext &bc) {
    int n = 0;
    for (int i = 0; i < bc.monsterCount; ++i)
        n += bc.monsters[i].id != MonsterId::INVALID && bc.monsters[i].alive && !bc.monsters[i].reviving;
    return n;
}

// Index of the creature's slot name among first/second/third/fourth (or wriggler1..4);
// -1 when it has no such slot. Phrog Parasite's Slots start with "phrog".
static int native_slot_ordinal(const BattleContext &bc, const Monster &m) {
    if (bc.encounterSlots == 0 || m.orderKey >= 64) return -1;
    return m.orderKey - (bc.encounter == Encounter::SETUP_PHROG_PARASITE_ELITE ? 1 : 0);
}

static bool eval_cond(BattleContext &bc, Monster &m, int selfIdx, std::uint8_t cond) {
    switch (cond) {
        case COND_ALWAYS: return true;
        case COND_ALONE: return alive_allies(bc, selfIdx) == 0;
        case COND_FRONT: return m.slot == 0;
        case COND_NOT_FRONT: return m.slot != 0;
        case COND_OFF_BALANCE: return m.offBalance;
        case COND_SLUMBER: return power_ref(m, PowerId::SLUMBER) > 0;
        case COND_HALF_HP: return m.hp < m.maxHp / 2;
        case COND_HAS_ALLY: return alive_allies(bc, selfIdx) > 0;
        case COND_NO_ALLY: return alive_allies(bc, selfIdx) == 0;
        case COND_CAN_SUMMON: return bc.monsterCount < MAX_MONSTERS;
        case COND_CAN_FABRICATE: return living_enemies(bc) < 4;
        case COND_CAN_LAY: return living_enemies(bc) <= 3;
        case COND_AMALGAM: return has_other_amalgam(bc, selfIdx);
        case COND_SLOT_FIRST: return native_slot_ordinal(bc, m) == 0;
        case COND_SLOT_SECOND: return native_slot_ordinal(bc, m) == 1;
        case COND_SLOT_THIRD: return native_slot_ordinal(bc, m) == 2;
        case COND_SLOT_FOURTH: return native_slot_ordinal(bc, m) == 3;
        case COND_ASLEEP: return power_ref(m, PowerId::ASLEEP) > 0;
        case COND_KNOWLEDGE_CURSE: return m.aux[0] < 3;
        case COND_TEST_SUBJECT_REVIVE: return m.aux[0] < 2;
        case COND_FROG_CHARGED: return m.aux[0] == 0 && m.hp < m.maxHp / 2;  // CurrentHp < MaxHp / 2 (int)
        case COND_WRIGGLER_BITE: return (m.slot % 2) == 0;
        case COND_WRIGGLER_WRIGGLE: return (m.slot % 2) == 1;
        // Unknown condition codes must never silently evaluate true.
        default: return false;
    }
}

static bool in_log(const Monster &m, int state, int lastN) {
    if (lastN <= 0) return state < 32 && (m.everLogged >> state) & 1u;
    const int n = m.stateLogN;
    const int start = lastN > 0 ? std::max(0, n - lastN) : 0;
    for (int i = start; i < n; ++i) {
        if (m.stateLog[i] == state) return true;
    }
    return false;
}

static int trailing(const Monster &m, int state) {
    int n = 0;
    for (int i = m.stateLogN - 1; i >= 0 && m.stateLog[i] == state; --i) ++n;
    return n;
}

// TwoTailedRat.CanSummon: TurnsUntilSummonable <= 0, CallForBackupCount < 3, a free
// encounter slot (TwoTailedRatsNormal has 5), and no teammate whose NextMove is
// CALL_FOR_BACKUP_MOVE (local state 4).
static bool rat_can_summon(const BattleContext &bc, const Monster &m) {
    if (m.aux[0] > 0 || m.aux[1] >= 3) return false;
    int listed = 0;
    for (int i = 0; i < bc.monsterCount; ++i) {
        const Monster &o = bc.monsters[i];
        if (o.id == MonsterId::INVALID || !(o.alive || o.reviving)) continue;
        ++listed;
        // Compare by slot: the A2 prediction passes a copy of the rat.
        if (o.orderKey != m.orderKey && o.id == MonsterId::TWO_TAILED_RAT && o.move == 4) return false;
    }
    return listed < 5;
}

// Native RandomBranchState.GetNextState: weights are floats (the table stores
// weight x 10), summed in branch order; num = rng.NextFloat(sum); then
// num -= weight for every branch in order, first with num <= 0 wins. Exactly one
// MonsterAi draw per traversal, also when every weight is zero (NextFloat(0)).
// Branch weights of a RandomBranchState after the repeat / max-times / cooldown rules
// (shared by the real roll and the A2 prediction). Returns the branch count.
static int random_branch_weights(const BattleContext &bc, const Monster &m, const MonStateDef &st,
                                 float *weights, float &total) {
    total = 0.0f;
    const int n = std::min<int>(st.branchN, 16);
    const bool rat = m.id == MonsterId::TWO_TAILED_RAT;
    const bool ratCanSummon = rat && rat_can_summon(bc, m);
    for (int i = 0; i < n; ++i) {
        const MonBranchDef &b = MON_BRANCHES[st.branchOff + i];
        float w = static_cast<float>(b.weight) / 10.0f;
        if (rat) {
            // TwoTailedRat RAND: Scratch / Disease Bite / Screech weigh
            // (!CanSummon() ? 1f : 1f / 12f); Call For Backup (!CanSummon() ? 0f : 0.75f).
            w = i < 3 ? (ratCanSummon ? 1.0f / 12.0f : 1.0f) : (ratCanSummon ? 0.75f : 0.0f);
        }
        switch (b.repeat) {
            case 1: if (m.stateLogN > 0 && m.stateLog[m.stateLogN - 1] == b.state) w = 0.0f; break;
            case 2: if (trailing(m, b.state) >= b.maxTimes) w = 0.0f; break;
            case 3: if (in_log(m, b.state, 0)) w = 0.0f; break;
            default: break;
        }
        if (b.cooldown > 0 && in_log(m, b.state, b.cooldown)) w = 0.0f;
        weights[i] = w > 0.0f ? w : 0.0f;
        total += weights[i];
    }
    return n;
}

static int choose_random(BattleContext &bc, Monster &m, const MonStateDef &st) {
    float weights[16];
    float total = 0.0f;
    const int n = random_branch_weights(bc, m, st, weights, total);
    float num = bc.monsterAiRng.next_float(0.0f, total);
    for (int i = 0; i < n; ++i) {
        num -= weights[i];
        if (num <= 0.0f) return MON_BRANCHES[st.branchOff + i].state;
    }
    return n > 0 ? MON_BRANCHES[st.branchOff + n - 1].state : 0;
}

static int resolve_state(BattleContext &bc, Monster &m, int selfIdx, int local) {
    const MonsterDef &def = monster_def(m.id);
    int guard = 0;
    while (guard++ < 32) {
        if (local < 0 || local >= def.stateCount) return 0;
        const MonStateDef &st = state_of(def, local);
        if (st.kind == MON_MOVE) return local;
        if (st.kind == MON_RANDOM) {
            local = choose_random(bc, m, st);
            continue;
        }
        int pick = -1;
        for (int i = 0; i < st.branchN; ++i) {
            const MonCondDef &cb = MON_CONDS[st.branchOff + i];
            if (eval_cond(bc, m, selfIdx, cb.cond)) {
                pick = cb.state;
                break;
            }
        }
        if (pick < 0) return 0;
        local = pick;
    }
    return 0;
}

static void add_log(Monster &m, int state) {
    if (state < 32) m.everLogged |= 1u << state;
    if (m.stateLogN < 8) {
        m.stateLog[m.stateLogN++] = static_cast<std::uint8_t>(state);
    } else {
        for (int i = 1; i < 8; ++i) m.stateLog[i - 1] = m.stateLog[i];
        m.stateLog[7] = static_cast<std::uint8_t>(state);
    }
}

static int move_attack_damage(const BattleContext &bc, const Monster &m, int local, const MonIntentDef &intent) {
    if (m.id == MonsterId::WATERFALL_GIANT && local == 7) return m.steamEruptionDamage;
    if (m.id == MonsterId::WATERFALL_GIANT && local == 4) return m.aux[2];
    // TheForgotten.DreadDamage is evaluated for both the intent and the attack.
    // It grows with current Dexterity; the old recorded 15 assumed one Miasma.
    if (m.id == MonsterId::THE_FORGOTTEN && local == 1)
        return (bc.ascension >= 9 ? 15 : 13) + m.power[static_cast<int>(PowerId::DEXTERITY)];
    return bc.ascension >= 9 && intent.deadlyDamage >= 0 ? intent.deadlyDamage : intent.damage;
}

std::vector<VisibleMonsterIntent> visible_monster_intents(const BattleContext &bc, int slot) {
    if (slot < 0 || slot >= bc.monsterCount) throw std::out_of_range("monster slot");
    const Monster &m = bc.monsters[slot];
    if (m.stunned) return {{10, 0, 0}};
    const MonsterDef &def = monster_def(m.id);
    const MonStateDef &st = state_of(def, m.move);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    std::vector<VisibleMonsterIntent> out;
    bool firstAttack = true;
    for (int i=0;i<st.intentN[asc];++i) {
        const auto &in=MON_INTENTS[st.intentOff[asc]+i];
        int damage=0,hits=0;
        if (in.type==0) {
            int base=move_attack_damage(bc,m,m.move,in);
            hits=bc.ascension>=9 && in.deadlyHits>=0 ? in.deadlyHits : in.hits;
            // roll_intent already accounts for the visible growing hit/damage counters.
            if(firstAttack){hits=m.intentHits;firstAttack=false;}
            damage=bc.calc_monster_damage(m,base);
            // Native AttackIntent.GetSingleDamage uses ModifyDamageHookType.All,
            // including public damage caps, before drawing the intent number.
            if(bc.player_power(PowerId::INTANGIBLE)>0)damage=std::min(damage,1);
            if(bc.player_power(PowerId::HARD_TO_KILL)>0)damage=std::min(damage,bc.player_power(PowerId::HARD_TO_KILL));
            hits=std::max(1,hits);
        }
        out.push_back({in.displayType,damage,hits});
    }
    return out;
}

void roll_intent(BattleContext &bc, Monster &m) {
    const MonsterDef &def = monster_def(m.id);
    const MonStateDef &st = state_of(def, m.move);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    m.intentType = 2;
    m.intentDamage = 0;
    m.intentHits = 1;
    bool haveAttack = false;
    for (int i = 0; i < st.intentN[asc]; ++i) {
        const MonIntentDef &in = MON_INTENTS[st.intentOff[asc] + i];
        if (in.type == 0 && !haveAttack) {
            m.intentType = 0;
            m.intentDamage = move_attack_damage(bc, m, m.move, in);
            m.intentHits = bc.ascension >= 9 && in.deadlyHits >= 0
                               ? in.deadlyHits : in.hits;
            haveAttack = true;
        } else if (!haveAttack && i == 0) {
            m.intentType = in.type;
        }
    }
    // Test Subject's multi-claw gains one hit each time it is used; the intent
    // must reflect the live count, not the recorded initial effect.
    if (def.multiClawState != 255 && m.move == def.multiClawState) {
        m.intentHits = static_cast<std::uint8_t>(3 + m.aux[1]);
    }
    if (m.stunned) {
        m.intentType = 8;  // StunIntent
        m.intentDamage = 0;
        m.intentHits = 1;
    } else if (m.reviving) {
        m.intentType = 7;  // heal intent while waiting to respawn
        m.intentDamage = 0;
        m.intentHits = 1;
    }
}

// Native Creature.SetUniqueMonsterHpValue (CombatState.CreateCreature, every enemy,
// also mid-combat summons): candidates = [MinInitialHp, MaxInitialHp] minus the
// MaxHp of every other creature in the enemy list, in ascending order (HashSet
// built from Enumerable.Range, then ExceptWith); Niche.NextItem picks one
// (NextInt(0, count)); if none is left, Niche.NextInt(min, max + 1).
static int roll_unique_monster_hp(BattleContext &bc, int slot, int lo, int hi) {
    if (hi < lo) hi = lo;
    int candidates[512];
    int n = 0;
    for (int hp = lo; hp <= hi && n < 512; ++hp) {
        bool taken = false;
        for (int i = 0; i < bc.monsterCount && !taken; ++i) {
            if (i == slot) continue;
            const Monster &o = bc.monsters[i];
            if (o.id == MonsterId::INVALID) continue;
            if (!(o.alive || o.reviving)) continue;
            taken = o.maxHp == hp;
        }
        if (bc.hpDyingMaxHp > 0 && bc.hpDyingMaxHp == hp) taken = true;
        if (!taken) candidates[n++] = hp;
    }
    if (n <= 0) return bc.nicheRng.next_int_range(lo, hi + 1);
    return candidates[bc.nicheRng.next_int_range(0, n)];
}

static void spawn_at(BattleContext &bc, MonsterId id, int slot,
                     int forcedInitialState = -1, int hpBonus = 0) {
    if (slot < 0 || slot >= MAX_MONSTERS) return;
    Monster &m = bc.monsters[slot];
    m = Monster();
    m.id = id;
    m.slot = static_cast<std::uint8_t>(slot);
    if (id == MonsterId::WATERFALL_GIANT) m.aux[2] = bc.ascension >= 9 ? 23 : 20;
    if (id == MonsterId::AEONGLASS) m.aux[2] = 6; // WitheringPresence.CardsLeft, separate from Amount
    const MonsterDef &def = monster_def(id);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    m.maxHp = m.hp = roll_unique_monster_hp(bc, slot, def.hpLo[asc] + hpBonus, def.hpHi[asc] + hpBonus);
    for (int i = 0; i < def.innateCount[asc]; ++i) {
        const MonPowerDef &p = MON_INNATE[def.innateOff[asc] + i];
        power_ref(m, p.id) += bc.ascension >= 9 && p.deadlyAmount >= 0
                                  ? p.deadlyAmount : p.amount;
    }
    if (power_ref(m, PowerId::ILLUSION) > 0 && power_ref(m, PowerId::MINION) <= 0)
        power_ref(m, PowerId::MINION) = 1;
    int state = forcedInitialState >= 0
                    ? forcedInitialState
                    : (def.initialCount > 0 ? MON_INITIALS[def.initialOff].state
                                            : 0);
    if (forcedInitialState < 0 && def.initialCount > 1) {
        int total = 0;
        for (int i = 0; i < def.initialCount; ++i) total += MON_INITIALS[def.initialOff + i].weight;
        int roll = bc.monsterAiRng.next_int(0, total > 0 ? total - 1 : 0);
        for (int i = 0; i < def.initialCount; ++i) {
            roll -= MON_INITIALS[def.initialOff + i].weight;
            if (roll < 0) {
                state = MON_INITIALS[def.initialOff + i].state;
                break;
            }
        }
    }
    m.stateLogN = 0;
    m.spawnedThisEnemyTurn = bc.inMonsterTurn;
    // ToughEgg.AfterAddedToRoom: Hatch 2 when added on the enemy side's turn, else 1.
    if (id == MonsterId::TOUGH_EGG) power_ref(m, PowerId::HATCH) = bc.inMonsterTurn ? 2 : 1;
    if (id == MonsterId::TWO_TAILED_RAT) {
        m.aux[0] = 2;   // TwoTailedRat._turnsUntilSummonable
        m.aux[1] = 0;   // CallForBackupCount
    }
    // MonsterMoveStateMachine(list, initial): an initial MoveState is the first move;
    // an initial branch state is traversed by the first RollMove -- at the next
    // player-turn start, or at once if the monster arrives during the player's turn
    // (CombatManager.AfterCreatureAdded rolls when CurrentSide == Player).
    m.move = static_cast<std::uint8_t>(state);
    if (state_of(def, state).kind != MON_MOVE) {
        m.pendingRoll = true;
        m.pendingState = static_cast<std::uint8_t>(state);
        if (bc.turn >= 1 && !bc.inMonsterTurn) {
            m.move = static_cast<std::uint8_t>(resolve_state(bc, m, slot, state));
            m.pendingRoll = false;
        }
    }
    roll_intent(bc, m);
    if (id == MonsterId::ROCKET) {
        bc.player.power[static_cast<int>(PowerId::SURROUNDED)] = 1;
    }
    // Hook.AfterCreatureAddedToCombat fires only for CreatureCmd.Add (mid-combat summons,
    // turn >= 1), not for the encounter's initial roster.
    if (bc.turn >= 1 && relic_has(bc, RelicId::PHILOSOPHERS_STONE)) m.strength += 1;
    if (bc.furCoatActive) m.hp = 1;  // FurCoat.AfterCreatureAddedToCombat: SetCurrentHp(1)
}

void roll_pending_moves(BattleContext &bc) {
    int order[MAX_MONSTERS];
    const int n = bc.enemy_order(order);
    for (int k = 0; k < n; ++k) {
        const int i = order[k];
        Monster &m = bc.monsters[i];
        if (!m.alive || !m.pendingRoll) continue;
        m.move = static_cast<std::uint8_t>(resolve_state(bc, m, i, m.pendingState));
        m.pendingRoll = false;
        roll_intent(bc, m);
    }
}

void spawn_monster_with(BattleContext &bc, MonsterId id, int slot, int initialState, int hpBonus) {
    if (slot < 0 || slot >= MAX_MONSTERS) return;
    if (slot >= bc.monsterCount) bc.monsterCount = slot + 1;
    const std::int16_t key = bc.monsters[slot].orderKey;   // a respawn keeps the slot (StockPower)
    spawn_at(bc, id, slot, initialState, hpBonus);
    bc.monsters[slot].orderKey = key;
}

void spawn_monster(BattleContext &bc, MonsterId id, int slot) {
    if (slot < 0) {
        for (int i = 0; i < bc.monsterCount; ++i) {
            if (!bc.monsters[i].alive) { slot = i; break; }
        }
        if (slot < 0) {
            if (bc.monsterCount >= MAX_MONSTERS) return;
            slot = bc.monsterCount++;
        }
    }
    spawn_at(bc, id, slot);
    bc.monsters[slot].orderKey = static_cast<std::int16_t>(64 + bc.spawnSeq++);   // no Slots: appended
}

// Native ModelId.Entry = StringHelper.Slugify(class name). Our keys are SETUP_<entry>
// except the event encounters, whose native classes end in EventEncounter.
const char *encounter_native_entry(Encounter enc) {
    switch (enc) {
        case Encounter::SETUP_PUNCH_OFF: return "PUNCH_OFF_EVENT_ENCOUNTER";
        case Encounter::SETUP_DENSE_VEGETATION: return "DENSE_VEGETATION_EVENT_ENCOUNTER";
        case Encounter::SETUP_FAKE_MERCHANT: return "FAKE_MERCHANT_EVENT_ENCOUNTER";
        case Encounter::SETUP_MYSTERIOUS_KNIGHT: return "MYSTERIOUS_KNIGHT_EVENT_ENCOUNTER";
        case Encounter::SETUP_THE_ARCHITECT: return "THE_ARCHITECT_EVENT_ENCOUNTER";
        case Encounter::SETUP_BATTLEWORN_DUMMY_V1: return "BATTLEWORN_DUMMY_EVENT_V1_ENCOUNTER";
        case Encounter::SETUP_BATTLEWORN_DUMMY_V2: return "BATTLEWORN_DUMMY_EVENT_V2_ENCOUNTER";
        case Encounter::SETUP_BATTLEWORN_DUMMY_V3: return "BATTLEWORN_DUMMY_EVENT_V3_ENCOUNTER";
        default: break;
    }
    const int ei = static_cast<int>(enc);
    if (ei <= 0 || ei >= static_cast<int>(Encounter::COUNT)) return "";
    const char *key = ENCOUNTER_DEFS[ei].key;
    if (key == nullptr) return "";
    return std::strncmp(key, "SETUP_", 6) == 0 ? key + 6 : key;
}

namespace {
struct RosterSlot {
    MonsterId id = MonsterId::INVALID;
    int initial = -1;         // forced initial local state, -1 = the table's initial
    int hpReduction = 0;      // PunchConstruct.StartingHpReduction
};

// Rng.NextItem over a list of n items: NextInt(0, n), also when n == 1.
int next_item(Rng &rng, int n) { return rng.next_int_range(0, n); }

// Native GenerateMonsters for the encounters whose roster or starting moves depend on
// the encounter's own Rng, or that set per-monster flags (native file per case).
// RNG calls happen in the same order as in the native code. Returns the monster
// count, or 0 when the encounter's single table pattern is used unchanged.
int native_roster(Encounter enc, Rng &rng, RosterSlot out[MAX_MONSTERS]) {
    using M = MonsterId;
    int n = 0;
    auto add = [&](M id, int initial = -1) {
        if (n < MAX_MONSTERS) { out[n] = RosterSlot{}; out[n].id = id; out[n].initial = initial; ++n; }
    };
    // Picks k distinct items from `pool` in order (native: filter by "count < 1",
    // then NextItem; Dictionary keys keep insertion order).
    auto pick_distinct = [&](const M *pool, int poolN, int k, M *picked) {
        bool used[8] = {};
        for (int j = 0; j < k; ++j) {
            M left[8]; int leftN = 0; int map[8];
            for (int i = 0; i < poolN; ++i) if (!used[i]) { map[leftN] = i; left[leftN++] = pool[i]; }
            const int c = next_item(rng, leftN);
            used[map[c]] = true;
            picked[j] = left[c];
        }
    };
    switch (enc) {
        case Encounter::SETUP_SLIMES_WEAK: {                  // SlimesWeak.cs
            const M small[2] = {M::LEAF_SLIME_S, M::TWIG_SLIME_S};
            const int i1 = next_item(rng, 2);
            const M m1 = small[i1];
            (void)next_item(rng, 1);                          // NextItem over the one left
            const M m2 = small[1 - i1];
            const M medium[2] = {M::LEAF_SLIME_M, M::TWIG_SLIME_M};
            const M m = medium[next_item(rng, 2)];
            add(m1); add(m); add(m2);
            return n;
        }
        case Encounter::SETUP_SLIMES_NORMAL: {                // SlimesNormal.cs
            const bool flag = rng.next_bool();
            add(M::TWIG_SLIME_M); add(M::LEAF_SLIME_M);
            add(flag ? M::LEAF_SLIME_S : M::TWIG_SLIME_S);
            add(flag ? M::TWIG_SLIME_S : M::LEAF_SLIME_S);
            return n;
        }
        case Encounter::SETUP_BOWLBUGS_WEAK: {                // BowlbugsWeak.cs
            const M bugs[2] = {M::BOWLBUG_EGG, M::BOWLBUG_NECTAR};
            add(M::BOWLBUG_ROCK);
            add(bugs[next_item(rng, 2)]);
            return n;
        }
        case Encounter::SETUP_BOWLBUGS_NORMAL: {              // BowlbugsNormal.cs
            const M workers[3] = {M::BOWLBUG_EGG, M::BOWLBUG_SILK, M::BOWLBUG_NECTAR};
            M picked[2];
            add(M::BOWLBUG_ROCK);
            pick_distinct(workers, 3, 2, picked);
            add(picked[0]); add(picked[1]);
            return n;
        }
        case Encounter::SETUP_FLYCONID_NORMAL: {              // FlyconidNormal.cs
            const M medium[2] = {M::LEAF_SLIME_M, M::TWIG_SLIME_M};
            add(medium[next_item(rng, 2)]);
            add(M::FLYCONID);
            return n;
        }
        case Encounter::SETUP_RUBY_RAIDERS_NORMAL: {          // RubyRaidersNormal.cs
            const M raiders[5] = {M::AXE_RUBY_RAIDER, M::ASSASSIN_RUBY_RAIDER, M::BRUTE_RUBY_RAIDER,
                                  M::CROSSBOW_RUBY_RAIDER, M::TRACKER_RUBY_RAIDER};
            M picked[3];
            pick_distinct(raiders, 5, 3, picked);
            add(picked[0]); add(picked[1]); add(picked[2]);
            return n;
        }
        case Encounter::SETUP_SLITHERING_STRANGLER_NORMAL: {  // SlitheringStranglerNormal.cs
            const M small[2] = {M::LEAF_SLIME_S, M::TWIG_SLIME_S};
            const M medium[2] = {M::LEAF_SLIME_M, M::TWIG_SLIME_M};
            switch (next_item(rng, 3)) {                     // SnappingJaxfruit, MediumSlime, SmallSlimes
                case 0: add(M::SNAPPING_JAXFRUIT); break;
                case 1: add(medium[next_item(rng, 2)]); break;
                default: {
                    const M a = small[next_item(rng, 2)];
                    const M b = small[next_item(rng, 2)];
                    add(a); add(b);
                    break;
                }
            }
            add(M::SLITHERING_STRANGLER);
            return n;
        }
        case Encounter::SETUP_CORPSE_SLUGS_WEAK:              // CorpseSlugsWeak.cs / CorpseSlugsNormal.cs:
        case Encounter::SETUP_CORPSE_SLUGS_NORMAL: {          // StarterMoveIdx = (NextInt(3) + i) % 3
            const int count = enc == Encounter::SETUP_CORPSE_SLUGS_WEAK ? 2 : 3;
            const int first = rng.next_int_exclusive(3);
            for (int i = 0; i < count; ++i) add(M::CORPSE_SLUG, (first + i) % 3);  // WHIP_SLAP, GLOMP, GOOP
            return n;
        }
        case Encounter::SETUP_TWO_TAILED_RATS_NORMAL: {       // TwoTailedRatsNormal.cs
            const int first = rng.next_int_exclusive(3);
            for (int i = 0; i < 3; ++i) add(M::TWO_TAILED_RAT, (first + i) % 3 + 1);  // SCRATCH, DISEASE_BITE, SCREECH
            return n;
        }
        case Encounter::SETUP_SCROLLS_OF_BITING_WEAK:         // ScrollsOfBitingWeak.cs / ...Normal.cs
        case Encounter::SETUP_SCROLLS_OF_BITING_NORMAL: {
            const int first = rng.next_int_exclusive(3);
            for (int i = 0; i < 3; ++i) add(M::SCROLL_OF_BITING, (first + i) % 3);  // CHOMP, CHEW, MORE_TEETH
            if (enc == Encounter::SETUP_SCROLLS_OF_BITING_NORMAL) add(M::SCROLL_OF_BITING, 2);
            return n;
        }
        case Encounter::SETUP_DECIMILLIPEDE_ELITE: {          // DecimillipedeElite.cs
            // StarterMoveIdx 0/1/2 = WRITHE/BULK/CONSTRICT; table order WRITHE(0), CONSTRICT(1), BULK(2).
            static const int local[3] = {0, 2, 1};
            const int first = rng.next_int_exclusive(3);
            for (int i = 0; i < 3; ++i) add(M::DECIMILLIPEDE_SEGMENT, local[(first + i) % 3]);
            return n;
        }
        case Encounter::SETUP_PUNCH_OFF: {                    // PunchOffEventEncounter.cs
            add(M::PUNCH_CONSTRUCT, 2);                       // StartsWithFastPunch -> FAST_PUNCH_MOVE
            out[0].hpReduction = rng.next_int_range(2, 10);
            add(M::PUNCH_CONSTRUCT, 0);                       // READY_MOVE
            out[1].hpReduction = rng.next_int_range(2, 10);
            return n;
        }
        case Encounter::SETUP_TUNNELER_NORMAL:                // TunnelerNormal.cs: Chomper.ScreamFirst
            add(M::CHOMPER, 1); add(M::TUNNELER);
            return n;
        case Encounter::SETUP_TOADPOLES_WEAK:                 // ToadpolesWeak.cs: IsFront -> SPIKEN, else WHIRL
            add(M::TOADPOLE, 3); add(M::TOADPOLE, 2);
            return n;
        case Encounter::SETUP_DENSE_VEGETATION:               // DenseVegetationEventEncounter.cs: StartStunned = false;
            for (int i = 0; i < 4; ++i) add(M::WRIGGLER, i % 2 == 0 ? 2 : 3);  // wriggler1/3 bite, 2/4 wriggle
            return n;
        default:
            break;
    }
    return 0;
}
}  // namespace

// Native Encounter.Slots: count and the slot index of each roster entry (creation order).
// Encounters without a Slots override return 0 (enemies keep creation order).
static int encounter_slot_table(Encounter enc, int keys[MAX_MONSTERS]) {
    for (int i = 0; i < MAX_MONSTERS; ++i) keys[i] = i;
    switch (enc) {
        case Encounter::SETUP_AXEBOTS_NORMAL: return 1;                 // front
        case Encounter::SETUP_DECIMILLIPEDE_ELITE: return 3;            // segment1..3
        case Encounter::SETUP_DENSE_VEGETATION: return 4;               // wriggler1..4
        case Encounter::SETUP_EXOSKELETONS_NORMAL: return 4;            // first..fourth
        case Encounter::SETUP_EXOSKELETONS_WEAK: return 3;              // first..third
        case Encounter::SETUP_FABRICATOR_NORMAL: keys[0] = 2; return 5;  // bot1, bot2, fabricator, bot3, bot4
        case Encounter::SETUP_FAKE_MERCHANT: return 1;                  // merchant
        case Encounter::SETUP_FOGMOG_NORMAL: keys[0] = 1; return 2;     // illusion, fogmog
        case Encounter::SETUP_KAISER_CRAB_BOSS: return 2;               // crusher, rocket
        case Encounter::SETUP_LIVING_FOG_NORMAL: keys[0] = 5; return 6; // bomb1..5, livingFog
        case Encounter::SETUP_MYTES_NORMAL: return 2;                   // first, second
        case Encounter::SETUP_NIBBITS_NORMAL: return 2;                 // front, back
        case Encounter::SETUP_OVICOPTER_NORMAL: keys[0] = 5; return 6;  // egg1..5, ovicopter
        case Encounter::SETUP_PHANTASMAL_GARDENERS_ELITE: return 4;     // first..fourth
        case Encounter::SETUP_PHROG_PARASITE_ELITE: return 5;           // phrog, wriggler1..4
        case Encounter::SETUP_QUEEN_BOSS: return 2;                     // amalgam, queen
        case Encounter::SETUP_THE_KIN_BOSS: return 3;                   // slot1, slot2, leaderSlot
        case Encounter::SETUP_THE_OBSCURA_NORMAL: keys[0] = 1; return 2; // illusion, obscura
        case Encounter::SETUP_TWO_TAILED_RATS_NORMAL:                   // first..fifth; rats in 3rd..5th
            keys[0] = 2; keys[1] = 3; keys[2] = 4; return 5;
        default: return 0;
    }
}

int BattleContext::enemy_order(int out[MAX_MONSTERS]) const {
    int n = 0;
    for (int i = 0; i < monsterCount; ++i) out[n++] = i;
    for (int i = 1; i < n; ++i)                       // insertion sort: stable, n <= 6
        for (int j = i; j > 0 && monsters[out[j]].orderKey < monsters[out[j - 1]].orderKey; --j)
            std::swap(out[j], out[j - 1]);
    return n;
}

int BattleContext::living_enemies(int out[MAX_MONSTERS]) const {
    int order[MAX_MONSTERS], n = 0;
    const int total = enemy_order(order);
    for (int k = 0; k < total; ++k)
        if (monsters[order[k]].alive && !monsters[order[k]].reviving) out[n++] = order[k];
    return n;
}

static bool slot_taken(const BattleContext &bc, int key) {
    for (int i = 0; i < bc.monsterCount; ++i) {
        const Monster &o = bc.monsters[i];
        if (o.id != MonsterId::INVALID && (o.alive || o.reviving) && o.orderKey == key) return true;
    }
    return false;
}

int summon_enemy(BattleContext &bc, MonsterId id, SlotRule rule, int namedSlot, int initialState, int hpBonus) {
    int key = -1;
    switch (rule) {
        case SlotRule::APPEND: key = 64 + bc.spawnSeq++; break;
        case SlotRule::NAMED: key = bc.encounterSlots > 0 ? namedSlot : 64 + bc.spawnSeq++; break;
        case SlotRule::FIRST_FREE:
            for (int s = 0; s < bc.encounterSlots && key < 0; ++s) if (!slot_taken(bc, s)) key = s;
            break;
        case SlotRule::LAST_FREE:
            for (int s = bc.encounterSlots - 1; s >= 0 && key < 0; --s) if (!slot_taken(bc, s)) key = s;
            break;
    }
    if (key < 0) return -1;
    int idx = -1;                                     // reuse a dead entry, else append
    for (int i = 0; i < bc.monsterCount && idx < 0; ++i)
        if (!bc.monsters[i].alive && !bc.monsters[i].reviving) idx = i;
    if (idx < 0) {
        if (bc.monsterCount >= MAX_MONSTERS) return -1;
        idx = bc.monsterCount++;
    }
    spawn_at(bc, id, idx, initialState, hpBonus);
    bc.monsters[idx].orderKey = static_cast<std::int16_t>(key);
    return idx;
}

void setup_encounter(BattleContext &bc, Encounter enc, std::uint64_t encounterSeed) {
    bc.monsterCount = 0;
    bc.encounter = enc;
    const int ei = static_cast<int>(enc);
    if (ei <= 0 || ei >= static_cast<int>(Encounter::COUNT)) return;
    const EncounterDef &ed = ENCOUNTER_DEFS[ei];
    // EncounterModel.GenerateMonstersWithSlots: the encounter's own Rng. No game
    // stream (MonsterAi, Niche, ...) is consumed to choose the roster.
    Rng encounterRng(encounterSeed);
    RosterSlot roster[MAX_MONSTERS];
    int count = native_roster(enc, encounterRng, roster);
    if (count == 0) {
        if (ed.patternCount == 0) {
            spawn_monster(bc, MonsterId::SHRINKER_BEETLE, 0);
            bc.monsterCount = 1;
            return;
        }
        // Fixed native roster: the encounter's single table pattern.
        const EncounterPattern &pat = ENC_PATTERNS[ed.patternOff];
        count = std::min<int>(pat.count, MAX_MONSTERS);
        for (int i = 0; i < count; ++i) {
            roster[i] = RosterSlot{};
            roster[i].id = static_cast<MonsterId>(pat.ids[i]);
        }
        // Fixed starting moves set by the native encounter or monster.
        if (enc == Encounter::SETUP_CHOMPERS_NORMAL) {
            roster[0].initial = 0;  // CLAMP_MOVE
            roster[1].initial = 1;  // SCREECH_MOVE
        } else if (enc == Encounter::SETUP_INKLETS_NORMAL) {
            roster[0].initial = 0;  // JAB_MOVE
            roster[1].initial = 1;  // WHIRLWIND_MOVE
            roster[2].initial = 0;  // JAB_MOVE
        } else if (enc == Encounter::SETUP_THE_KIN_BOSS) {
            roster[0].initial = 2;  // POWER_DANCE_MOVE
            roster[1].initial = 0;  // QUICK_SLASH_MOVE
        }
    }
    bc.monsterCount = count;
    int keys[MAX_MONSTERS];
    bc.encounterSlots = encounter_slot_table(enc, keys);
    bc.spawnSeq = count;
    // CombatRoom.StartCombat: CreateCreature in roster order (HP on Niche, unique
    // among the enemies created so far), then AddCreature.
    for (int i = 0; i < count; ++i) {
        spawn_at(bc, roster[i].id, i, roster[i].initial);
        bc.monsters[i].orderKey = static_cast<std::int16_t>(bc.encounterSlots > 0 ? keys[i] : 64 + i);
    }

    // AfterAddedToRoom, in enemy order, after every creature exists.
    const int asc = bc.ascension >= 8 ? 1 : 0;
    for (int i = 0; i < bc.monsterCount; ++i) {
        Monster &m = bc.monsters[i];
        if (m.id == MonsterId::DECIMILLIPEDE_SEGMENT) {
            // DecimillipedeSegment.AfterAddedToRoom: make MaxHp even, then step by 2
            // (wrapping to MinInitialHp) until no teammate has the same MaxHp.
            const MonsterDef &def = monster_def(m.id);
            int hp = m.maxHp;
            if (hp % 2 == 1) ++hp;
            for (int guard = 0; guard < 64; ++guard) {
                bool duplicate = false;
                for (int j = 0; j < bc.monsterCount; ++j)
                    duplicate |= j != i && bc.monsters[j].alive && bc.monsters[j].maxHp == hp;
                if (!duplicate) break;
                hp += 2;
                if (hp > def.hpHi[asc]) hp = def.hpLo[asc];
            }
            m.maxHp = m.hp = hp;
        } else if (m.id == MonsterId::PUNCH_CONSTRUCT && roster[i].hpReduction > 0) {
            // PunchConstruct.AfterAddedToRoom: current HP only.
            m.hp = std::max(1, m.hp - roster[i].hpReduction);
        }
    }
    // CubexConstruct.AfterAddedToRoom: GainBlock 13 (and Artifact 1, innate) for every
    // Cubex, also in Construct Menagerie.
    for (int i = 0; i < bc.monsterCount; ++i)
        if (bc.monsters[i].id == MonsterId::CUBEX_CONSTRUCT) bc.monsters[i].block += 13;
}

int random_encounter_for_act(int act, Rng &rng, int kind) {
    int pool[static_cast<int>(Encounter::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(Encounter::COUNT); ++i) {
        const EncounterDef &d = ENCOUNTER_DEFS[i];
        if (d.act != act || d.key == nullptr) continue;
        const bool elite = std::strstr(d.key, "ELITE") != nullptr;
        const bool boss = std::strstr(d.key, "BOSS") != nullptr;
        if (kind == 1 && !elite) continue;
        if (kind == 2 && !boss) continue;
        if (kind == 0 && (elite || boss)) continue;
        pool[n++] = i;
    }
    if (n == 0) return 0;
    return pool[rng.next_int(0, n - 1)];
}

int aeonglass_wither_upgrades(const BattleContext &bc) {
    for (int i = 0; i < bc.monsterCount; ++i)
        if (bc.monsters[i].alive && bc.monsters[i].id == MonsterId::AEONGLASS) return bc.monsters[i].aux[0];
    return 0;
}

void add_withers(BattleContext &bc, int count, bool toHand) {
    for (int k = 0; k < count && bc.outcome == Outcome::UNDECIDED; ++k) {
        Card c = make_card(CardId::WITHER, false, bc.require_card_uid());
        if (toHand) bc.add_card_to_hand(c);
        else bc.add_card_to_discard(c);
        bc.notify_card_generated(c, false);
    }
}

static void apply_monster_power(Monster &m, PowerId id, int amount) {
    // RitualPower.AfterApplied runs only for a new instance, not when stacking.
    if (id == PowerId::RITUAL && amount > 0 && power_ref(m, id) == 0) m.ritualJustApplied = true;
    if (id == PowerId::MINION && amount > 0) {
        power_ref(m, id) = std::max(power_ref(m, id), amount);
    } else {
        power_ref(m, id) += amount;
    }
    if (id == PowerId::ILLUSION && amount > 0 && power_ref(m, PowerId::MINION) <= 0)
        power_ref(m, PowerId::MINION) = 1;
}

static void perform_ops(BattleContext &bc, Monster &m, int selfIdx, const MonStateDef &st, int asc) {
    for (int i = 0; i < st.opN[asc]; ++i) {
        const MonOpDef &op = MON_OPS[st.opOff[asc] + i];
        const bool useDeadly = bc.ascension >= 9 && op.deadlyAmount >= 0;
        switch (op.op) {
            case OP_BLOCK: {
                // Every table block op is ValueProp.Move; Guardbot's Unpowered
                // block to Fabricator is handled separately below.
                int amount = (useDeadly ? op.deadlyAmount : op.a) + power_ref(m, PowerId::DEXTERITY);
                if (power_ref(m, PowerId::FRAIL) > 0) amount = amount * 3 / 4;
                m.block += std::max(0, amount);
                break;
            }
            case OP_POWER_SELF:
                if (static_cast<PowerId>(op.a) == PowerId::VITAL_SPARK)
                    bc.add_monster_power(selfIdx, PowerId::VITAL_SPARK, useDeadly ? op.deadlyAmount : op.b);
                else apply_monster_power(m, static_cast<PowerId>(op.a), useDeadly ? op.deadlyAmount : op.b);
                break;
            case OP_POWER_PLAYER: {
                PowerId pid = static_cast<PowerId>(op.a);
                int amount = useDeadly ? op.deadlyAmount : op.b;
                // ShrinkerBeetle applies Shrink -1: a negative amount is permanent
                // (ShrinkPower.IsInfinite) until the applier dies.
                if (amount < 0 && pid == PowerId::STRENGTH &&
                    power_ref(m, PowerId::POSSESS_STRENGTH) > 0) {
                    m.aux[0] = static_cast<std::int16_t>(m.aux[0] - amount);
                }
                if (amount < 0 && pid == PowerId::DEXTERITY &&
                    power_ref(m, PowerId::POSSESS_SPEED) > 0) {
                    m.aux[0] = static_cast<std::int16_t>(m.aux[0] - amount);
                }
                bc.add_player_power(pid, amount);
                break;
            }
            case OP_POWER_OTHER:
                // Captured summon moves include the new illusion's innate
                // powers before the spawn operation.  spawn_at applies them;
                // do not apply those records to an unrelated existing ally.
                if ((op.a == static_cast<int>(PowerId::ILLUSION) ||
                     op.a == static_cast<int>(PowerId::MINION)) &&
                    i + 1 < st.opN[asc]) {
                    bool summonedIllusion = false;
                    for (int j = i + 1; j < st.opN[asc]; ++j) {
                        const MonOpDef &next = MON_OPS[st.opOff[asc] + j];
                        if (next.op == OP_SUMMON &&
                            (next.a == static_cast<int>(MonsterId::EYE_WITH_TEETH) ||
                             next.a == static_cast<int>(MonsterId::PARAFRIGHT))) {
                            summonedIllusion = true;
                            break;
                        }
                    }
                    if (summonedIllusion) break;
                }
                for (int j = 0; j < bc.monsterCount; ++j) {
                    if (j != selfIdx && bc.monsters[j].alive) {
                        apply_monster_power(bc.monsters[j], static_cast<PowerId>(op.a),
                                            useDeadly ? op.deadlyAmount : op.b);
                        break;
                    }
                }
                break;
            case OP_CARD_DISCARD: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.require_card_uid());
                bc.add_card_to_discard(c);
                break;
            }
            case OP_CARD_DRAW: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.require_card_uid());
                // Captured draw-pile additions use CardPilePosition.Random.
                bc.add_card_to_draw_random(c);
                break;
            }
            case OP_CARD_HAND: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.require_card_uid());
                bc.add_card_to_hand(c);
                break;
            }
            case OP_HEAL:
                m.hp = std::min(m.maxHp, m.hp + op.a);
                break;
            case OP_LOSE_HP:
                m.hp -= op.a;
                if (m.hp <= 0) {
                    m.hp = 0;
                    m.alive = false;
                }
                break;
            case OP_SUMMON:
                spawn_monster(bc, static_cast<MonsterId>(op.a));
                break;
            default:
                break;
        }
    }
}

static void steal_hopper_card(BattleContext &bc, Monster &m) {
    if (bc.theftCount >= MAX_PILE) return;
    int bestRank = 99;
    bool candidateDraw[MAX_PILE * 2]{};
    int candidateIndex[MAX_PILE * 2]{};
    int candidateCount = 0;
    auto consider = [&](const Card &card, bool fromDraw, int index) {
        bool fromDeck = false;
        for (int i = 0; i < bc.originalDeckCount; ++i)
            if (bc.originalDeckUids[i] == card.uid) { fromDeck = true; break; }
        if (!fromDeck) return;
        for (int i = 0; i < bc.theftCount; ++i)
            if (bc.theftUids[i] == card.uid) return;
        const CardDef &d = card_def(card.id);
        int rank = 4;
        if (card.enchantment == EnchantmentId::IMBUED) rank = 3;  // only the Ancient/Imbued tier
        else if (d.rarity == Rarity::UNCOMMON) rank = 0;
        else if (d.rarity == Rarity::COMMON || d.rarity == Rarity::RARE ||
                 d.rarity == Rarity::EVENT) {
            rank = 1;
        } else if (d.rarity == Rarity::BASIC || d.rarity == Rarity::QUEST) {
            rank = 2;
        } else if (d.rarity == Rarity::ANCIENT) {
            rank = 3;  // ThievingHopper._stealPriorities[3]: Ancient or Imbued
        }
        if (rank < bestRank) {
            bestRank = rank;
            candidateCount = 0;
        }
        if (rank == bestRank) {
            candidateDraw[candidateCount] = fromDraw;
            candidateIndex[candidateCount++] = index;
        }
    };

    for (int i = bc.drawCount - 1; i >= 0; --i) consider(bc.draw[i], true, i);  // CardPile.GetCards: top first
    for (int i = 0; i < bc.discardCount; ++i) consider(bc.discard[i], false, i);
    if (candidateCount == 0) return;
    const int choice = bc.cardGenerationRng.next_int(0, candidateCount - 1);
    const bool bestDraw = candidateDraw[choice];
    const int bestIndex = candidateIndex[choice];
    const Card stolen = bestDraw ? bc.draw[bestIndex] : bc.discard[bestIndex];
    const int theft = bc.theftCount++;
    bc.theftUids[theft] = stolen.uid;
    bc.theftCards[theft] = stolen;
    bc.theftOwners[theft] = static_cast<std::int8_t>(&m - bc.monsters);
    bc.theftReturned[theft] = false;
    if (bestDraw) bc.remove_draw_at(bestIndex);
    else {
        for (int i = bestIndex; i + 1 < bc.discardCount; ++i) {
            bc.discard[i] = bc.discard[i + 1];
        }
        --bc.discardCount;
    }
    power_ref(m, PowerId::SWIPE) += 1;
}

void monster_act(BattleContext &bc, Monster &m) {
    if (!m.alive) return;
    const int selfIdx = static_cast<int>(&m - bc.monsters);
    const int dampenBefore = bc.player.power[static_cast<int>(PowerId::DAMPEN)];
    if (m.reviving && power_ref(m, PowerId::ILLUSION) > 0) {
        m.block = 0;
        ++m.turn;
        m.hp = m.maxHp;
        m.reviving = false;
        if (m.stateLogN > 0) m.move = m.stateLog[m.stateLogN - 1];
        roll_intent(bc, m);
        bc.check_outcome();
        return;
    }
    if (power_ref(m, PowerId::BURROWED) <= 0) m.block = 0;
    ++m.turn;
    m.lastMove = m.move;

    if (m.power[static_cast<int>(PowerId::POISON)] > 0) {
        const int poison = m.power[static_cast<int>(PowerId::POISON)];
        m.power[static_cast<int>(PowerId::POISON)] = std::max(0, poison - 1);
        bc.damage_monster(selfIdx, poison);
        if (!m.alive || bc.outcome != Outcome::UNDECIDED) return;
    }

    const MonsterDef &def = monster_def(m.id);
    int local = m.reviving && def.reviveState != 255
                    ? def.reviveState
                    : resolve_state(bc, m, selfIdx, m.move);
    const MonStateDef &st = state_of(def, local);
    const int asc = bc.ascension >= 8 ? 1 : 0;

    // ReattachPower.DoReattach: reaching the REATTACH move heals a knocked-out
    // segment and makes it hittable again. The move itself performs no attack.
    if (m.reviving && m.id == MonsterId::DECIMILLIPEDE_SEGMENT &&
        local == 4) {
        const int heal = power_ref(m, PowerId::REATTACH);
        m.hp = std::min(m.maxHp, m.hp + heal);
        m.reviving = false;
    }

    bool escapes = false;
    for (int i = 0; i < st.intentN[asc]; ++i) {
        // Generator intent codes: 8=Stun, 9=Escape.
        if (MON_INTENTS[st.intentOff[asc] + i].type == 9) escapes = true;
    }
    // The captured Doormaker data omits the third EscapeIntent from
    // GET_BACK_IN_MOVE; the C# state always contains it.
    if (m.id == MonsterId::DOORMAKER && local == 2) escapes = true;

    if (m.id == MonsterId::THIEVING_HOPPER && local == 0 && !m.reviving && !m.stunned) {
        steal_hopper_card(bc, m);
    }

    const bool acted = !m.reviving && !m.stunned;
    if (acted) {
        for (int i = 0; i < st.intentN[asc] && m.alive; ++i) {
            const MonIntentDef &in = MON_INTENTS[st.intentOff[asc] + i];
            if (in.type != 0) continue;
            int hits = bc.ascension >= 9 && in.deadlyHits >= 0
                           ? in.deadlyHits : in.hits;
            if (def.multiClawState != 255 && local == def.multiClawState) {
                hits = 3 + m.aux[1];
            }
            int damage = move_attack_damage(bc, m, local, in);
            const int unblockedBefore = bc.unblockedHitsThisCombat;
            for (int h = 0; h < hits; ++h) {
                if (bc.outcome != Outcome::UNDECIDED) break;
                bc.monster_attack_player(selfIdx, damage);
            }
            // SuckPower.AfterAttack: Strength Amount x (hits with unblocked damage).
            const int unblockedHits = bc.unblockedHitsThisCombat - unblockedBefore;
            if (m.alive && power_ref(m, PowerId::SUCK) > 0 && unblockedHits > 0)
                bc.add_monster_power(selfIdx, PowerId::STRENGTH, power_ref(m, PowerId::SUCK) * unblockedHits);
        }
        if (bc.outcome != Outcome::UNDECIDED && !m.alive) return;
        bool spitStrengthOnly = false;
        if (m.id == MonsterId::ENTOMANCER && local == 2) {
            // Native SpitMove returns immediately after Strength 2 when Hive is
            // absent or already full; it must not also execute the growth ops.
            const int hive = power_ref(m, PowerId::PERSONAL_HIVE);
            spitStrengthOnly = hive <= 0 || hive >= 3;
            if (spitStrengthOnly) bc.add_monster_power(selfIdx, PowerId::STRENGTH, 2);
        }
        if (!spitStrengthOnly) perform_ops(bc, m, selfIdx, st, asc);
        if (acted && bc.outcome == Outcome::UNDECIDED) {
            // Summons with the native slot rules (CreatureCmd.Add; IsLiveCombat checked).
            if (m.id == MonsterId::FABRICATOR && (local == 2 || local == 3)) {
                // Fabricator.SpawnBot: NextItem on MonsterAi over the pool minus the last
                // bot it spawned, in Encounter.GetNextSlot, then Minion. FABRICATE_MOVE
                // spawns a defensive then an aggressive bot; FABRICATING_STRIKE one aggressive.
                static const MonsterId defense[2] = {MonsterId::GUARDBOT, MonsterId::NOISEBOT};
                static const MonsterId aggro[2] = {MonsterId::ZAPBOT, MonsterId::STABBOT};
                auto spawn_bot = [&](const MonsterId *pool) {
                    MonsterId items[2];
                    int n = 0;
                    for (int j = 0; j < 2; ++j)
                        if (static_cast<int>(pool[j]) != m.aux[3]) items[n++] = pool[j];
                    const MonsterId pick = items[bc.monsterAiRng.next_int_range(0, n)];
                    m.aux[3] = static_cast<std::int16_t>(pick);   // _lastSpawned
                    const int w = summon_enemy(bc, pick, SlotRule::FIRST_FREE);
                    if (w >= 0) power_ref(bc.monsters[w], PowerId::MINION) = 1;
                };
                if (local == 2) spawn_bot(defense);
                spawn_bot(aggro);
            } else if (m.id == MonsterId::OVICOPTER && local == 0) {
                // Ovicopter.LayEggsMove: three Tough Eggs, each in the last free slot, Minion.
                for (int e = 0; e < 3; ++e) {
                    const int w = summon_enemy(bc, MonsterId::TOUGH_EGG, SlotRule::LAST_FREE);
                    if (w >= 0) power_ref(bc.monsters[w], PowerId::MINION) = 1;
                }
            } else if (m.id == MonsterId::LIVING_FOG && local == 1) {
                // LivingFog.BloatMove: BloatAmount (1) Gas Bombs in Encounter.GetNextSlot.
                summon_enemy(bc, MonsterId::GAS_BOMB, SlotRule::FIRST_FREE);
            } else if (m.id == MonsterId::FOGMOG && local == 0) {
                summon_enemy(bc, MonsterId::EYE_WITH_TEETH, SlotRule::NAMED, 0);   // slot "illusion"
            } else if (m.id == MonsterId::THE_OBSCURA && local == 0) {
                summon_enemy(bc, MonsterId::PARAFRIGHT, SlotRule::NAMED, 0);       // slot "illusion"
            }
        }
        if (acted && m.id == MonsterId::MAGI_KNIGHT && local == 1 && dampenBefore == 0 &&
            bc.player.power[static_cast<int>(PowerId::DAMPEN)] > 0) {
            bc.dampen_apply();   // DampenPower.AfterApplied (not when it was already present)
        }
        if (acted && m.id == MonsterId::KNOWLEDGE_DEMON && local == 0 && bc.outcome == Outcome::UNDECIDED &&
            bc.player.hp > 0 && m.aux[0] < 3) {
            // KnowledgeDemon.CurseOfKnowledgeMove -> ChooseCurse: Disintegration (damage
            // 6 / 7 / 8 by stage) or Mind Rot / Sloth / Waste Away; chosen on a card screen.
            static const CardId other[3] = {CardId::MIND_ROT, CardId::SLOTH_STATUS, CardId::WASTE_AWAY};
            static const int disintegration[3] = {6, 7, 8};
            const int stage = m.aux[0];
            bc.pending = PendingChoice();
            bc.pending.op = ChoiceOp::KNOWLEDGE_CURSE;
            bc.pending.pile = ChoicePile::OFFER;
            Card d = make_card(CardId::DISINTEGRATION, false, bc.require_card_uid());
            d.bonusDamage = disintegration[stage];
            bc.pending.cards[0] = d;
            bc.pending.cards[1] = make_card(other[stage], false, bc.require_card_uid());
            bc.pending.count = 2;
            bc.pending.remaining = 1;
            bc.pending.optional = false;
            bc.pending.payload = stage;
        }
        if (acted && m.id == MonsterId::THE_OBSCURA && local == 3) {
            // TheObscura.WailMove: Strength 3 to every creature on its side (itself included).
            for (int i = 0; i < bc.monsterCount; ++i)
                if (bc.monsters[i].alive && !bc.monsters[i].reviving)
                    bc.add_monster_power(i, PowerId::STRENGTH, 3);
        }
        if (acted && m.id == MonsterId::AXEBOT && local == 1) {
            // Axebot.BootUpMove (after its block): Strength BootUpStrGain (3, A9 4)
            // x RespawnCount (2 - StockAmount).
            const int respawns = 2 - power_ref(m, PowerId::STOCK);
            if (respawns > 0)
                bc.add_monster_power(selfIdx, PowerId::STRENGTH, (bc.ascension >= 9 ? 4 : 3) * respawns);
        }
        if (acted && m.id == MonsterId::TWO_TAILED_RAT) {
            if (local >= 1 && local <= 3) {
                --m.aux[0];   // Scratch / Disease Bite / Screech: TurnsUntilSummonable--
            } else if (local == 4) {
                // CallForBackup: a new rat in a free slot (5 in the encounter), then every
                // rat's CallForBackupCount = max(count + 1) over the rats.
                int listed = 0;
                for (int i = 0; i < bc.monsterCount; ++i)
                    listed += bc.monsters[i].id != MonsterId::INVALID &&
                              (bc.monsters[i].alive || bc.monsters[i].reviving);
                if (listed < 5) summon_enemy(bc, MonsterId::TWO_TAILED_RAT, SlotRule::LAST_FREE);
                int count = 0;
                for (int i = 0; i < bc.monsterCount; ++i)
                    if (bc.monsters[i].alive && bc.monsters[i].id == MonsterId::TWO_TAILED_RAT)
                        count = std::max(count, bc.monsters[i].aux[1] + 1);
                for (int i = 0; i < bc.monsterCount; ++i)
                    if (bc.monsters[i].alive && bc.monsters[i].id == MonsterId::TWO_TAILED_RAT)
                        bc.monsters[i].aux[1] = count;
            }
        }
        if (m.alive && m.id == MonsterId::TOUGH_EGG && local == 0) {
            // HatchMove removes every power except Minion, then Hatch():
            // Niche.NextInt(HatchlingMinHp, HatchlingMaxHp + 1) -- the max is included.
            const int minion = power_ref(m, PowerId::MINION);
            for (int &power : m.power) power = 0;
            power_ref(m, PowerId::MINION) = minion;
            m.strength = 0;
            m.vulnerable = 0;
            m.weak = 0;
            m.tempStrengthLoss = 0;
            m.slowCardsThisTurn = 0;
            m.shellHpLostThisTurn = 0;
            m.nemesisIntangible = false;
            m.maxHp = m.hp = bc.nicheRng.next_int_range(asc ? 20 : 19,
                                                        asc ? 24 : 23);
        }
        if (m.alive && m.id == MonsterId::WATERFALL_GIANT && local == 6) {
            m.steamEruptionDamage = power_ref(m, PowerId::STEAM_ERUPTION);
            power_ref(m, PowerId::STEAM_ERUPTION) = 0;
        }
        if (m.alive && m.id == MonsterId::WATERFALL_GIANT && local == 4)
            m.aux[2] += 5;
        if (m.alive && m.id == MonsterId::AEONGLASS && local == 2) {
            // IncreasingIntensityMove: FakeUpgrade every Wither (+3 damage),
            // WitherUpgradeCount++ (aux0), add 1/2 Withers to discard, then
            // Strength 3/4 + AdditionalStrength (aux1), AdditionalStrength++.
            Card *piles[] = {bc.hand, bc.draw, bc.discard, bc.exhaust, bc.playPile, bc.returnNextTurn};
            const int counts[] = {bc.handCount, bc.drawCount, bc.discardCount, bc.exhaustCount, bc.playCount,
                                  bc.returnNextTurnCount};
            for (int p = 0; p < 6; ++p)
                for (int i = 0; i < counts[p]; ++i)
                    if (piles[p][i].id == CardId::WITHER) piles[p][i].bonusDamage += 3;
            ++m.aux[0];
            add_withers(bc, bc.ascension >= 9 ? 2 : 1, false);
            bc.add_monster_power(selfIdx, PowerId::STRENGTH, (bc.ascension >= 9 ? 4 : 3) + m.aux[1]);
            ++m.aux[1];
        }
        if (m.alive && m.id == MonsterId::TEST_SUBJECT && local == 8 && bc.ascension >= 9) {
            // BurningGrowl creates five Burns at A9; the sampled A8 move table
            // already contains the first three.
            for (int i = 0; i < 2; ++i)
                bc.add_card_to_discard(make_card(CardId::BURN, false, bc.require_card_uid()));
        }
        if (m.alive && bc.player.hp > 0 &&
            power_ref(m, PowerId::THIEVERY) > 0) {
            const int stolen = std::min(bc.gold, power_ref(m, PowerId::THIEVERY));
            bc.gold -= stolen;
            m.stolenGold += stolen;
        }
    }
    m.stunned = false;

    if (acted && m.id == MonsterId::THE_INSATIABLE && local == 0) {
        power_ref(m, PowerId::SANDPIT) += 4;
    }
    if (acted && m.id == MonsterId::GUARDBOT && local == 0) {
        for (int i = 0; i < bc.monsterCount; ++i) {
            if (i != selfIdx && bc.monsters[i].alive &&
                bc.monsters[i].id == MonsterId::FABRICATOR) {
                bc.monsters[i].block += 15;
            }
        }
    }
    if (acted && m.id == MonsterId::GAS_BOMB && local == 0) {
        m.alive = false;
        m.combatEndBlocker = false;
        relics_monster_died(bc);
    }
    if (acted && m.id == MonsterId::WATERFALL_GIANT && local == 7 && m.alive) {
        m.hp = 0;
        m.alive = false;
        m.combatEndBlocker = false;
        relics_monster_died(bc);
    }

    // Escape spells remove the creature (or make the Door's Doormaker phase
    // return to the Door) rather than leaving a live, permanently acting enemy.
    if (acted && escapes && m.alive) {
        for (int i = 0; i < bc.theftCount; ++i) {
            if (bc.theftOwners[i] == selfIdx && !bc.theftReturned[i])
                bc.theftOwners[i] = -1;  // escape forfeits the stolen card
        }
        // The Doormaker's phase change is not CreatureCmd.Escape; everything
        // else leaving through an escape move counts as an escaped creature.
        if (m.id != MonsterId::DOORMAKER) {
            if (bc.escapedMonsterCount < 255) ++bc.escapedMonsterCount;
            if (m.id == MonsterId::FAT_GREMLIN) bc.fatGremlinEscaped = true;
        }
        if (m.id == MonsterId::DOORMAKER) {
            int doorIdx = -1;
            for (int i = 0; i < bc.monsterCount; ++i) {
                if (bc.monsters[i].id == MonsterId::DOOR && bc.monsters[i].reviving) {
                    doorIdx = i;
                    break;
                }
            }
            if (doorIdx >= 0) {
                Monster &door = bc.monsters[doorIdx];
                // The reference reuses the Doormaker between phases.  Keep the
                // return count on the Door so it survives a new spawned model.
                door.aux[0] = std::max(door.aux[0], m.aux[0]) + 1;
                m.aux[0] = door.aux[0];
                door.reviving = false;
                door.alive = true;
                const int baseHp = monster_def(MonsterId::DOOR).hpLo[asc];
                door.maxHp = baseHp + (asc ? 25 : 20) * door.aux[0];
                door.hp = door.maxHp;
                door.strength = (bc.ascension >= 9 ? 4 : 3) * door.aux[0];
                door.block = 0;
                door.move = 0;
                door.pendingRoll = false;
                roll_intent(bc, door);
            }
        }
        m.alive = false;
        m.combatEndBlocker = false;
    }

    // AI counter side effects (see MonStateDef::auxCode).
    switch (st.auxCode) {
        case 1: ++m.aux[0]; break;
        case 2: m.aux[0] = 1; break;
        case 3: ++m.aux[1]; break;
        case 4: {
            ++m.aux[0];
            const int second = asc ? 212 : 200;
            const int third = asc ? 313 : 300;
            m.maxHp = m.hp = m.aux[0] == 1 ? second : third;
            m.reviving = false;
            m.combatEndBlocker = false;
            if (m.aux[0] == 1) {
                power_ref(m, PowerId::PAINFUL_STABS) = 1;
            } else {
                power_ref(m, PowerId::NEMESIS) = 1;
                power_ref(m, PowerId::ADAPTABLE) = 0;
                power_ref(m, PowerId::PAINFUL_STABS) = 0;
            }
            break;
        }
        default: break;
    }

    if (m.id == MonsterId::BOWLBUG_ROCK && local == 2) {
        m.offBalance = false;
    }
    add_log(m, local);
    // Native: the transition happens in RollMove at the start of the player's turn
    // (roll_pending_moves); until then NextMove is still the performed move.
    m.pendingState = static_cast<std::uint8_t>(st.follow == 255 ? local : st.follow);
    m.pendingRoll = true;

    // end-of-turn monster powers
    if (power_ref(m, PowerId::RITUAL) > 0) {
        if (m.ritualJustApplied) m.ritualJustApplied = false;
        else m.strength += power_ref(m, PowerId::RITUAL);
    }
    if (m.alive && power_ref(m, PowerId::TERRITORIAL) > 0) {
        m.strength += power_ref(m, PowerId::TERRITORIAL);
    }
    if (m.alive && power_ref(m, PowerId::HIGH_VOLTAGE) > 0) {
        m.strength += power_ref(m, PowerId::HIGH_VOLTAGE);
    }
    if (m.alive && power_ref(m, PowerId::HATCH) > 0) {
        --power_ref(m, PowerId::HATCH);
    }
    // AsleepPower.BeforeSideTurnEndVeryEarly removes Plating on the last asleep
    // turn before PlatingPower.BeforeSideTurnEndEarly would grant its block.
    if (power_ref(m, PowerId::ASLEEP) > 0 && power_ref(m, PowerId::ASLEEP) <= 1)
        power_ref(m, PowerId::PLATING) = 0;
    if (power_ref(m, PowerId::PLATING) > 0) {
        m.block += power_ref(m, PowerId::PLATING);
        power_ref(m, PowerId::PLATING) -= 1;
    }
    if (power_ref(m, PowerId::ASLEEP) > 0) power_ref(m, PowerId::ASLEEP) -= 1;
    if (power_ref(m, PowerId::METALLICIZE) > 0) m.block += power_ref(m, PowerId::METALLICIZE);
    if (power_ref(m, PowerId::REGEN) > 0) m.hp = std::min(m.maxHp, m.hp + power_ref(m, PowerId::REGEN));
    if (m.alive && power_ref(m, PowerId::SLUMBER) > 0) {
        --power_ref(m, PowerId::SLUMBER);
        if (power_ref(m, PowerId::SLUMBER) <= 0) {
            power_ref(m, PowerId::PLATING) = 0;
            m.move = 2;  // ROLL_OUT_MOVE
            m.pendingRoll = false;
            roll_intent(bc, m);
        }
    }
    if (m.alive && power_ref(m, PowerId::ESCAPE_ARTIST) > 1) {
        --power_ref(m, PowerId::ESCAPE_ARTIST);
    }
    // BattlewornDummyTimeLimitPower.AfterSideTurnEnd: count down, then the
    // dummy escapes and the encounter records RanOutOfTime.
    if (m.alive && power_ref(m, PowerId::BATTLEWORN_DUMMY_TIME_LIMIT) > 0) {
        if (power_ref(m, PowerId::BATTLEWORN_DUMMY_TIME_LIMIT) > 1) {
            --power_ref(m, PowerId::BATTLEWORN_DUMMY_TIME_LIMIT);
        } else {
            bc.battlewornRanOutOfTime = true;
            m.alive = false;
            m.combatEndBlocker = false;
        }
    }

    if (m.vulnerable > 0) --m.vulnerable;
    if (m.weak > 0) --m.weak;
    if (m.power[static_cast<int>(PowerId::SHRINK)] > 0) {
        m.power[static_cast<int>(PowerId::SHRINK)] -= 1;
    }
    // IntangiblePower.AfterTurnEnd: lasts through the turn it was applied for.
    if (m.power[static_cast<int>(PowerId::INTANGIBLE)] > 0) {
        m.power[static_cast<int>(PowerId::INTANGIBLE)] -= 1;
    }
    // NemesisPower.AfterTurnEnd(owner side): alternates Intangible on/off at the
    // end of each of its own turns.  Applied after the generic tick so the
    // fresh stack is not immediately consumed.
    if (power_ref(m, PowerId::NEMESIS) > 0) {
        m.nemesisIntangible = !m.nemesisIntangible;
        if (m.nemesisIntangible) {
            power_ref(m, PowerId::INTANGIBLE) = 1;
        } else {
            power_ref(m, PowerId::INTANGIBLE) = 0;
        }
    }
    bc.check_outcome();
    if (m.alive) roll_intent(bc, m);
}


// ---------------------------------------------------------------- A2 prediction
namespace {
// Distribution over MON_MOVE states reached from `local` (random / conditional
// branches expanded); mirrors resolve_state without drawing from the RNG.
void expand_state(const BattleContext &bc, const Monster &m, int selfIdx, int local, double p,
                  std::vector<std::pair<int, double>> &out, int guard = 0) {
    const MonsterDef &def = monster_def(m.id);
    if (guard > 32 || local < 0 || local >= def.stateCount || p <= 0.0) {
        out.push_back({0, p});
        return;
    }
    const MonStateDef &st = state_of(def, local);
    if (st.kind == MON_MOVE) {
        out.push_back({local, p});
        return;
    }
    if (st.kind == MON_RANDOM) {
        float weights[16];
        float total = 0.0f;
        const int n = random_branch_weights(bc, m, st, weights, total);
        if (total <= 0.0f) {  // NextFloat(0) = 0 -> the first branch (num <= 0)
            if (n > 0) expand_state(bc, m, selfIdx, MON_BRANCHES[st.branchOff].state, p, out, guard + 1);
            return;
        }
        for (int i = 0; i < n; ++i)
            if (weights[i] > 0.0f)
                expand_state(bc, m, selfIdx, MON_BRANCHES[st.branchOff + i].state, p * weights[i] / total, out, guard + 1);
        return;
    }
    auto &mutableBc = const_cast<BattleContext &>(bc);   // eval_cond only reads
    Monster copy = m;
    for (int i = 0; i < st.branchN; ++i) {
        const MonCondDef &cb = MON_CONDS[st.branchOff + i];
        if (eval_cond(mutableBc, copy, selfIdx, cb.cond)) {
            expand_state(bc, m, selfIdx, cb.state, p, out, guard + 1);
            return;
        }
    }
    out.push_back({0, p});
}

PredictedMove describe(const BattleContext &bc, const Monster &m, int local, double p) {
    PredictedMove r{local, p, 2, 0, 0};
    const MonsterDef &def = monster_def(m.id);
    if (local < 0 || local >= def.stateCount) return r;
    const MonStateDef &st = state_of(def, local);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    for (int i = 0; i < st.intentN[asc]; ++i) {
        const MonIntentDef &in = MON_INTENTS[st.intentOff[asc] + i];
        if (i == 0) r.intentType = in.type;
        if (in.type == 0) {
            r.intentType = 0;
            r.damage = bc.calc_monster_damage(m, move_attack_damage(bc, m, local, in));
            r.hits = bc.ascension >= 9 && in.deadlyHits >= 0 ? in.deadlyHits : in.hits;
            if (def.multiClawState != 255 && local == def.multiClawState) r.hits = 3 + m.aux[1];
            break;
        }
    }
    return r;
}

// State bookkeeping a performed move leaves behind (move log, AI counters).
void perform(const BattleContext &bc, Monster &m, int local) {
    const MonsterDef &def = monster_def(m.id);
    const MonStateDef &st = state_of(def, local);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    switch (st.auxCode) {
        case 1: ++m.aux[0]; break;
        case 2: m.aux[0] = 1; break;
        case 3: ++m.aux[1]; break;
        case 4: ++m.aux[0]; m.maxHp = m.hp = m.aux[0] == 1 ? (asc ? 212 : 200) : (asc ? 313 : 300); break;
        default: break;
    }
    add_log(m, local);
    m.pendingState = static_cast<std::uint8_t>(st.follow == 255 ? local : st.follow);
}
}  // namespace

const char *monster_state_name(MonsterId id, int local) {
    const MonsterDef &def = monster_def(id);
    if (local < 0 || local >= def.stateCount) return "";
    return MON_STATE_NAMES[def.stateOff + local];
}

std::vector<std::vector<PredictedMove>> predict_monster_moves(const BattleContext &bc, int slot, int depth) {
    std::vector<std::vector<PredictedMove>> steps;
    if (slot < 0 || slot >= bc.monsterCount || depth <= 0) return steps;
    const Monster &start = bc.monsters[slot];
    if (start.id == MonsterId::INVALID) return steps;
    steps.push_back({describe(bc, start, start.move, 1.0)});
    std::vector<std::pair<Monster, double>> frontier{{start, 1.0}};
    for (int k = 1; k < depth; ++k) {
        std::vector<std::pair<Monster, double>> next;
        std::vector<PredictedMove> step;
        for (auto &[m, p] : frontier) {
            Monster after = m;
            perform(bc, after, m.move);
            // Scratch / Disease Bite / Screech count the rat's summon cooldown down.
            if (after.id == MonsterId::TWO_TAILED_RAT && m.move >= 1 && m.move <= 3) --after.aux[0];
            std::vector<std::pair<int, double>> reached;
            expand_state(bc, after, slot, after.pendingState, p, reached);
            for (auto [local, q] : reached) {
                Monster branch = after;
                branch.move = static_cast<std::uint8_t>(local);
                bool merged = false;
                for (auto &row : step)
                    if (row.state == local) { row.p += q; merged = true; break; }
                if (!merged) step.push_back(describe(bc, branch, local, q));
                next.push_back({branch, q});
            }
        }
        steps.push_back(step);
        frontier.swap(next);
        if (frontier.size() > 256) break;  // bounded: three steps never come close
    }
    return steps;
}
}  // namespace sts2
