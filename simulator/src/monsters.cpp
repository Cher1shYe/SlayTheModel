#include "sts2/monsters.h"

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

static bool eval_cond(BattleContext &bc, Monster &m, int selfIdx, std::uint8_t cond) {
    switch (cond) {
        case COND_ALWAYS: return true;
        case COND_ALONE: return alive_allies(bc, selfIdx) == 0;
        case COND_FRONT: return m.slot == 0;
        case COND_NOT_FRONT: return m.slot != 0;
        case COND_OFF_BALANCE: return false;
        case COND_SLUMBER: return power_ref(m, PowerId::SLUMBER) > 0;
        case COND_HALF_HP: return m.hp * 2 < m.maxHp;
        case COND_HAS_ALLY: return alive_allies(bc, selfIdx) > 0;
        case COND_NO_ALLY: return alive_allies(bc, selfIdx) == 0;
        case COND_CAN_SUMMON: return bc.monsterCount < MAX_MONSTERS;
        case COND_AMALGAM: return has_other_amalgam(bc, selfIdx);
        case COND_SLOT_FIRST: return m.slot == 0;
        case COND_SLOT_SECOND: return m.slot == 1;
        case COND_SLOT_THIRD: return m.slot == 2;
        case COND_SLOT_FOURTH: return m.slot == 3;
        case COND_ASLEEP: return power_ref(m, PowerId::ASLEEP) > 0;
        case COND_KNOWLEDGE_CURSE: return m.aux[0] < 3;
        case COND_TEST_SUBJECT_REVIVE: return m.aux[0] < 2;
        case COND_FROG_CHARGED: return m.aux[0] == 0 && m.hp * 2 < m.maxHp;
        case COND_WRIGGLER_BITE: return (m.slot % 2) == 0;
        case COND_WRIGGLER_WRIGGLE: return (m.slot % 2) == 1;
        // Unknown condition codes must never silently evaluate true.
        default: return false;
    }
}

static bool in_log(const Monster &m, int state, int lastN) {
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

static int choose_random(BattleContext &bc, Monster &m, const MonStateDef &st) {
    int weights[16];
    int total = 0;
    const int n = std::min<int>(st.branchN, 16);
    for (int i = 0; i < n; ++i) {
        const MonBranchDef &b = MON_BRANCHES[st.branchOff + i];
        int w = b.weight;
        switch (b.repeat) {
            case 1: if (m.stateLogN > 0 && m.stateLog[m.stateLogN - 1] == b.state) w = 0; break;
            case 2: if (trailing(m, b.state) >= b.maxTimes) w = 0; break;
            case 3: if (in_log(m, b.state, 0)) w = 0; break;
            default: break;
        }
        if (b.cooldown > 0 && in_log(m, b.state, b.cooldown)) w = 0;
        weights[i] = w > 0 ? w : 0;
        total += weights[i];
    }
    if (total <= 0) return n > 0 ? MON_BRANCHES[st.branchOff].state : 0;
    int roll = bc.rng.next_int(0, total - 1);
    for (int i = 0; i < n; ++i) {
        if (weights[i] <= 0) continue;
        roll -= weights[i];
        if (roll < 0) return MON_BRANCHES[st.branchOff + i].state;
    }
    return MON_BRANCHES[st.branchOff + n - 1].state;
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
    if (m.stateLogN < 8) {
        m.stateLog[m.stateLogN++] = static_cast<std::uint8_t>(state);
    } else {
        for (int i = 1; i < 8; ++i) m.stateLog[i - 1] = m.stateLog[i];
        m.stateLog[7] = static_cast<std::uint8_t>(state);
    }
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
            m.intentDamage = in.damage;
            m.intentHits = in.hits;
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
    if (m.reviving) {
        m.intentType = 7;  // heal intent while waiting to respawn
        m.intentDamage = 0;
        m.intentHits = 1;
    }
}

static void spawn_at(BattleContext &bc, MonsterId id, int slot) {
    if (slot < 0 || slot >= MAX_MONSTERS) return;
    Monster &m = bc.monsters[slot];
    m = Monster();
    m.id = id;
    m.slot = static_cast<std::uint8_t>(slot);
    const MonsterDef &def = monster_def(id);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    m.maxHp = m.hp = bc.rng.next_int(def.hpLo[asc], def.hpHi[asc]);
    for (int i = 0; i < def.innateCount[asc]; ++i) {
        const MonPowerDef &p = MON_INNATE[def.innateOff[asc] + i];
        power_ref(m, p.id) += p.amount;
    }
    int state = def.initialCount > 0 ? MON_INITIALS[def.initialOff].state : 0;
    if (def.initialCount > 1) {
        int total = 0;
        for (int i = 0; i < def.initialCount; ++i) total += MON_INITIALS[def.initialOff + i].weight;
        int roll = bc.rng.next_int(0, total > 0 ? total - 1 : 0);
        for (int i = 0; i < def.initialCount; ++i) {
            roll -= MON_INITIALS[def.initialOff + i].weight;
            if (roll < 0) {
                state = MON_INITIALS[def.initialOff + i].state;
                break;
            }
        }
    }
    m.move = static_cast<std::uint8_t>(resolve_state(bc, m, slot, state));
    m.stateLogN = 0;
    roll_intent(bc, m);
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
}

void setup_encounter(BattleContext &bc, Encounter enc) {
    bc.monsterCount = 0;
    bc.encounter = enc;
    const int ei = static_cast<int>(enc);
    if (ei <= 0 || ei >= static_cast<int>(Encounter::COUNT)) return;
    const EncounterDef &ed = ENCOUNTER_DEFS[ei];
    int total = 0;
    for (int i = 0; i < ed.patternCount; ++i) total += ENC_PATTERNS[ed.patternOff + i].weight;
    int pick = 0;
    int roll = bc.rng.next_int(0, total > 0 ? total - 1 : 0);
    for (int i = 0; i < ed.patternCount; ++i) {
        roll -= ENC_PATTERNS[ed.patternOff + i].weight;
        if (roll < 0) { pick = i; break; }
    }
    if (ed.patternCount == 0) {
        spawn_monster(bc, MonsterId::SHRINKER_BEETLE, 0);
        bc.monsterCount = 1;
        return;
    }
    const EncounterPattern &pat = ENC_PATTERNS[ed.patternOff + pick];
    bc.monsterCount = std::min<int>(pat.count, MAX_MONSTERS);
    for (int i = 0; i < pat.count && i < MAX_MONSTERS; ++i) {
        spawn_at(bc, static_cast<MonsterId>(pat.ids[i]), i);
    }
}

int random_encounter_for_act(int act, Rng &rng, int kind) {
    int pool[128];
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

static void perform_ops(BattleContext &bc, Monster &m, int selfIdx, const MonStateDef &st, int asc) {
    for (int i = 0; i < st.opN[asc]; ++i) {
        const MonOpDef &op = MON_OPS[st.opOff[asc] + i];
        switch (op.op) {
            case OP_BLOCK:
                m.block += op.a;
                break;
            case OP_POWER_SELF:
                power_ref(m, static_cast<PowerId>(op.a)) += op.b;
                break;
            case OP_POWER_PLAYER: {
                PowerId pid = static_cast<PowerId>(op.a);
                int amount = op.b;
                if (pid == PowerId::SHRINK && amount < 0) amount = -amount;
                bc.add_player_power(pid, amount);
                break;
            }
            case OP_POWER_OTHER:
                for (int j = 0; j < bc.monsterCount; ++j) {
                    if (j != selfIdx && bc.monsters[j].alive) {
                        power_ref(bc.monsters[j], static_cast<PowerId>(op.a)) += op.b;
                        break;
                    }
                }
                break;
            case OP_CARD_DISCARD: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.nextUid++);
                bc.add_card_to_discard(c);
                break;
            }
            case OP_CARD_DRAW: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.nextUid++);
                bc.add_card_to_draw_top(c);
                break;
            }
            case OP_CARD_HAND: {
                Card c = make_card(static_cast<CardId>(op.a), false, bc.nextUid++);
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

void monster_act(BattleContext &bc, Monster &m) {
    if (!m.alive) return;
    const int selfIdx = static_cast<int>(&m - bc.monsters);
    m.block = 0;
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

    if (!m.reviving) {
        for (int i = 0; i < st.intentN[asc] && m.alive; ++i) {
            const MonIntentDef &in = MON_INTENTS[st.intentOff[asc] + i];
            if (in.type != 0) continue;
            int hits = in.hits;
            if (def.multiClawState != 255 && local == def.multiClawState) {
                hits = 3 + m.aux[1];
            }
            for (int h = 0; h < hits; ++h) {
                if (bc.outcome != Outcome::UNDECIDED) break;
                bc.monster_attack_player(selfIdx, in.damage);
            }
        }
        if (bc.outcome != Outcome::UNDECIDED && !m.alive) return;
        perform_ops(bc, m, selfIdx, st, asc);
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

    add_log(m, local);
    int next = st.follow == 255 ? local : st.follow;
    m.move = static_cast<std::uint8_t>(resolve_state(bc, m, selfIdx, next));

    // end-of-turn monster powers
    if (power_ref(m, PowerId::RITUAL) > 0) m.strength += power_ref(m, PowerId::RITUAL);
    if (power_ref(m, PowerId::PLATING) > 0) {
        m.block += power_ref(m, PowerId::PLATING);
        power_ref(m, PowerId::PLATING) -= 1;
    }
    if (power_ref(m, PowerId::ASLEEP) > 0) {
        if (power_ref(m, PowerId::ASLEEP) <= 1) power_ref(m, PowerId::PLATING) = 0;
        power_ref(m, PowerId::ASLEEP) -= 1;
    }
    if (power_ref(m, PowerId::METALLICIZE) > 0) m.block += power_ref(m, PowerId::METALLICIZE);
    if (power_ref(m, PowerId::REGEN) > 0) m.hp = std::min(m.maxHp, m.hp + power_ref(m, PowerId::REGEN));

    if (m.vulnerable > 0) --m.vulnerable;
    if (m.weak > 0) --m.weak;
    if (m.power[static_cast<int>(PowerId::SHRINK)] > 0) {
        m.power[static_cast<int>(PowerId::SHRINK)] -= 1;
    }
    bc.check_outcome();
    if (m.alive) roll_intent(bc, m);
}

}  // namespace sts2
