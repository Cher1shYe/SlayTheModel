#include "sts2/monsters.h"
#include "sts2/relics.h"

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

static bool eval_cond(BattleContext &bc, Monster &m, int selfIdx, std::uint8_t cond) {
    switch (cond) {
        case COND_ALWAYS: return true;
        case COND_ALONE: return alive_allies(bc, selfIdx) == 0;
        case COND_FRONT: return m.slot == 0;
        case COND_NOT_FRONT: return m.slot != 0;
        case COND_OFF_BALANCE: return m.offBalance;
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
    int roll = bc.monsterAiRng.next_int(0, total - 1);
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
            m.intentDamage = bc.ascension >= 9 && in.deadlyDamage >= 0
                                 ? in.deadlyDamage : in.damage;
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
    if (m.id == MonsterId::WATERFALL_GIANT && m.move == 7) {
        m.intentDamage = m.steamEruptionDamage;
    } else if (m.id == MonsterId::WATERFALL_GIANT && m.move == 4) {
        m.intentDamage = m.aux[2];  // CurrentPressureGunDamage
    } else if (m.id == MonsterId::FAKE_MERCHANT_MONSTER && m.move == 4) {
        // ThrowRelic advertises ThrowRelicDamage but its attack uses SwipeDamage.
        m.intentDamage = bc.ascension >= 9 ? 10 : 9;
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

static void spawn_at(BattleContext &bc, MonsterId id, int slot,
                     int forcedInitialState = -1) {
    if (slot < 0 || slot >= MAX_MONSTERS) return;
    Monster &m = bc.monsters[slot];
    m = Monster();
    m.id = id;
    m.slot = static_cast<std::uint8_t>(slot);
    if (id == MonsterId::WATERFALL_GIANT) m.aux[2] = bc.ascension >= 9 ? 23 : 20;
    const MonsterDef &def = monster_def(id);
    const int asc = bc.ascension >= 8 ? 1 : 0;
    m.maxHp = m.hp = bc.monsterAiRng.next_int(def.hpLo[asc], def.hpHi[asc]);
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
    m.move = static_cast<std::uint8_t>(resolve_state(bc, m, slot, state));
    m.stateLogN = 0;
    roll_intent(bc, m);
    if (id == MonsterId::ROCKET) {
        bc.player.power[static_cast<int>(PowerId::SURROUNDED)] = 1;
    }
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
    int roll = bc.monsterAiRng.next_int(0, total > 0 ? total - 1 : 0);
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
    int forcedInitial[MAX_MONSTERS];
    for (int i = 0; i < MAX_MONSTERS; ++i) forcedInitial[i] = -1;

    // EncounterModel.GenerateMonsters sets correlated starts before room
    // creation. Sampling each MonsterModel independently loses those contracts.
    if (enc == Encounter::SETUP_CHOMPERS_NORMAL) {
        forcedInitial[0] = 0;  // CLAMP_MOVE
        forcedInitial[1] = 1;  // SCREECH_MOVE
    } else if (enc == Encounter::SETUP_DECIMILLIPEDE_ELITE) {
        const int first = bc.monsterAiRng.next_int(0, 2);
        for (int i = 0; i < 3; ++i) forcedInitial[i] = (first + i) % 3;
    } else if (enc == Encounter::SETUP_INKLETS_NORMAL) {
        forcedInitial[0] = 0;  // JAB_MOVE
        forcedInitial[1] = 1;  // WHIRLWIND_MOVE
        forcedInitial[2] = 0;  // JAB_MOVE
    } else if (enc == Encounter::SETUP_PUNCH_OFF) {
        forcedInitial[0] = 1;  // STRONG_PUNCH_MOVE
        forcedInitial[1] = 0;  // READY_MOVE
    } else if (enc == Encounter::SETUP_SCROLLS_OF_BITING_NORMAL) {
        const int first = bc.monsterAiRng.next_int(0, 2);
        for (int i = 0; i < 3; ++i) forcedInitial[i] = (first + i) % 3;
        forcedInitial[3] = 2;  // MORE_TEETH
    } else if (enc == Encounter::SETUP_SCROLLS_OF_BITING_WEAK) {
        const int first = bc.monsterAiRng.next_int(0, 2);
        for (int i = 0; i < 3; ++i) forcedInitial[i] = (first + i) % 3;
    } else if (enc == Encounter::SETUP_TWO_TAILED_RATS_NORMAL) {
        const int first = bc.monsterAiRng.next_int(0, 2);
        // StarterMoveIndex 0/1/2 maps to SCRATCH/DISEASE_BITE/SCREECH.
        for (int i = 0; i < 3; ++i) forcedInitial[i] = (first + i) % 3 + 1;
    } else if (enc == Encounter::SETUP_THE_KIN_BOSS) {
        forcedInitial[0] = 2;  // POWER_DANCE_MOVE
        forcedInitial[1] = 0;  // QUICK_SLASH_MOVE
    }

    for (int i = 0; i < pat.count && i < MAX_MONSTERS; ++i) {
        spawn_at(bc, static_cast<MonsterId>(pat.ids[i]), i, forcedInitial[i]);
    }

    if (enc == Encounter::SETUP_DECIMILLIPEDE_ELITE) {
        const int asc = bc.ascension >= 8 ? 1 : 0;
        int seen[MAX_MONSTERS];
        int seenN = 0;
        for (int i = 0; i < bc.monsterCount; ++i) {
            Monster &m = bc.monsters[i];
            if (m.id != MonsterId::DECIMILLIPEDE_SEGMENT) continue;
            int hp = m.maxHp;
            if (hp % 2 != 0) ++hp;
            for (int guard = 0; guard < 8; ++guard) {
                bool duplicate = false;
                for (int k = 0; k < seenN; ++k) duplicate |= seen[k] == hp;
                if (!duplicate) break;
                hp += 2;
                if (hp > monster_def(m.id).hpHi[asc]) {
                    hp = monster_def(m.id).hpLo[asc];
                    if (hp % 2 != 0) ++hp;
                }
            }
            m.maxHp = m.hp = hp;
            seen[seenN++] = hp;
        }
    } else if (enc == Encounter::SETUP_PUNCH_OFF) {
        const int maxHp = bc.ascension >= 8 ? 60 : 55;
        for (int i = 0; i < bc.monsterCount; ++i) {
            Monster &m = bc.monsters[i];
            if (m.id != MonsterId::PUNCH_CONSTRUCT) continue;
            const int reduction = bc.monsterAiRng.next_int(2, 10);
            m.maxHp = maxHp;
            m.hp = maxHp - reduction;
        }
    }

    if (enc == Encounter::SETUP_CUBEX_CONSTRUCT_NORMAL) {
        for (int i = 0; i < bc.monsterCount; ++i) {
            if (bc.monsters[i].id == MonsterId::CUBEX_CONSTRUCT) {
                bc.monsters[i].block += 13;
            }
        }
    }
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

static void apply_monster_power(Monster &m, PowerId id, int amount) {
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
            case OP_BLOCK:
                m.block += useDeadly ? op.deadlyAmount : op.a;
                break;
            case OP_POWER_SELF:
                apply_monster_power(m, static_cast<PowerId>(op.a),
                                    useDeadly ? op.deadlyAmount : op.b);
                break;
            case OP_POWER_PLAYER: {
                PowerId pid = static_cast<PowerId>(op.a);
                int amount = useDeadly ? op.deadlyAmount : op.b;
                if (pid == PowerId::SHRINK && amount < 0) amount = -amount;
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
        if (d.rarity == Rarity::UNCOMMON) rank = 0;
        else if (d.rarity == Rarity::COMMON || d.rarity == Rarity::RARE ||
                 d.rarity == Rarity::EVENT) {
            rank = 1;
        } else if (d.rarity == Rarity::BASIC) {
            rank = 2;
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

    for (int i = 0; i < bc.drawCount; ++i) consider(bc.draw[i], true, i);
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
            int damage = bc.ascension >= 9 && in.deadlyDamage >= 0
                             ? in.deadlyDamage : in.damage;
            if (m.id == MonsterId::WATERFALL_GIANT && local == 7)
                damage = m.steamEruptionDamage;
            else if (m.id == MonsterId::WATERFALL_GIANT && local == 4)
                damage = m.aux[2];
            else if (m.id == MonsterId::FAKE_MERCHANT_MONSTER && local == 4)
                damage = bc.ascension >= 9 ? 15 : 13;
            for (int h = 0; h < hits; ++h) {
                if (bc.outcome != Outcome::UNDECIDED) break;
                bc.monster_attack_player(selfIdx, damage);
            }
        }
        if (bc.outcome != Outcome::UNDECIDED && !m.alive) return;
        perform_ops(bc, m, selfIdx, st, asc);
        if (m.alive && m.id == MonsterId::TOUGH_EGG && local == 0) {
            // HatchMove removes every power except Minion, then rolls the
            // Hatchling HP on the run's Niche RNG (upper bound exclusive).
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
                                                        asc ? 23 : 22);
        }
        if (m.alive && m.id == MonsterId::WATERFALL_GIANT && local == 6) {
            m.steamEruptionDamage = power_ref(m, PowerId::STEAM_ERUPTION);
            power_ref(m, PowerId::STEAM_ERUPTION) = 0;
        }
        if (m.alive && m.id == MonsterId::WATERFALL_GIANT && local == 4)
            m.aux[2] += 5;
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
    int next = st.follow == 255 ? local : st.follow;
    m.move = static_cast<std::uint8_t>(resolve_state(bc, m, selfIdx, next));

    // end-of-turn monster powers
    if (power_ref(m, PowerId::RITUAL) > 0) m.strength += power_ref(m, PowerId::RITUAL);
    if (m.alive && power_ref(m, PowerId::TERRITORIAL) > 0) {
        m.strength += power_ref(m, PowerId::TERRITORIAL);
    }
    if (m.alive && power_ref(m, PowerId::HIGH_VOLTAGE) > 0) {
        m.strength += power_ref(m, PowerId::HIGH_VOLTAGE);
    }
    if (m.alive && power_ref(m, PowerId::HATCH) > 0) {
        --power_ref(m, PowerId::HATCH);
    }
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
    if (m.alive && power_ref(m, PowerId::SLUMBER) > 0) {
        --power_ref(m, PowerId::SLUMBER);
        if (power_ref(m, PowerId::SLUMBER) <= 0) {
            power_ref(m, PowerId::PLATING) = 0;
            m.move = 2;  // ROLL_OUT_MOVE
            roll_intent(bc, m);
        }
    }
    if (m.alive && power_ref(m, PowerId::ESCAPE_ARTIST) > 1) {
        --power_ref(m, PowerId::ESCAPE_ARTIST);
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

}  // namespace sts2
