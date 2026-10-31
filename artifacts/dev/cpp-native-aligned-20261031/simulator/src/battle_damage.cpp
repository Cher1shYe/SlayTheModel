#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
#include "sts2/silent.h"
#include "sts2/defect.h"
#include "sts2/necrobinder.h"
namespace sts2 {
DamageDealt BattleContext::damage_monster(int idx, int amount, bool fromPlayer,
                                          bool poweredAttack, bool unblockable) {
    DamageDealt res;
    bool diedThisHit = false;
    if (idx < 0 || idx >= monsterCount) return res;
    Monster &m = monsters[idx];
    if (!m.alive || m.reviving) return res;
    amount=std::max(0,amount);
    if (poweredAttack && m.power[static_cast<int>(PowerId::COVERED)] > 0) return res;
    // ThornsPower.BeforeDamageReceived: a powered attack from the player
    // triggers thorns before the hit resolves, even if the hit is fully
    // blocked.  The reflect is Unpowered: blockable, no strength/vulnerable.
    if (fromPlayer && poweredAttack && m.power[static_cast<int>(PowerId::THORNS)] > 0 &&
        outcome == Outcome::UNDECIDED) {
        if(necro.dealingOstyDamage)necrobinder_damage_osty(*this,m.power[static_cast<int>(PowerId::THORNS)]);
        else damage_player(m.power[static_cast<int>(PowerId::THORNS)]);
        if (outcome != Outcome::UNDECIDED) return res;
    }
    int remaining = amount;
    // ModifyDamageCap is applied by the hook chain before block. Intangible,
    // HardToKill and Slippery therefore combine by taking the smallest cap.
    int damageCap = remaining;
    if (m.power[static_cast<int>(PowerId::INTANGIBLE)] > 0) damageCap = std::min(damageCap, 1);
    if (m.power[static_cast<int>(PowerId::HARD_TO_KILL)] > 0) {
        damageCap = std::min(damageCap,
                             m.power[static_cast<int>(PowerId::HARD_TO_KILL)]);
    }
    if (m.power[static_cast<int>(PowerId::SLIPPERY)] > 0) damageCap = std::min(damageCap, 1);
    remaining = std::min(remaining, damageCap);
    const bool hadBlock = m.block > 0;
    int blockedDamage = 0;
    if (m.block > 0 && !unblockable) {
        blockedDamage = remaining < m.block ? remaining : m.block;
        m.block -= blockedDamage;
        remaining -= blockedDamage;
    }
    res.blockBroken = !unblockable && hadBlock && m.block == 0;
    if (res.blockBroken && relic_has(*this, RelicId::HAND_DRILL)) {
        // HandDrill.AfterDamageGiven only requires DamageResult.WasBlockBroken,
        // including the exact hit that breaks the last point of block.
        apply_vulnerable(idx, 2);
    }
    // TheBoot.ModifyHpLostBeforeOsty: a powered attack that would cost the
    // enemy 1..4 HP instead costs 5, applied after block.
    if (poweredAttack && remaining > 0 && remaining < 5 && relic_has(*this, RelicId::THE_BOOT)) {
        remaining = 5;
    }
    // HardenedShellPower.ModifyHpLostBeforeOstyLate: HP loss is capped by the
    // power amount minus what this monster already lost this player turn.
    if (remaining > 0 && m.power[static_cast<int>(PowerId::HARDENED_SHELL)] > 0) {
        const int cap = m.power[static_cast<int>(PowerId::HARDENED_SHELL)];
        const int left = std::max(0, cap - m.shellHpLostThisTurn);
        if (remaining > left) remaining = left;
    }
    if (remaining > 0) {
        const bool hadAsleep = m.power[static_cast<int>(PowerId::ASLEEP)] > 0;
        const int hpBefore = m.hp;
        m.hp -= remaining;
        res.unblocked = std::min(remaining, std::max(0, hpBefore));
        res.overkill = std::max(0, remaining - hpBefore);
        res.total = blockedDamage + res.unblocked;
        res.fullyBlocked = blockedDamage > 0 && res.unblocked == 0;
        if (m.power[static_cast<int>(PowerId::HARDENED_SHELL)] > 0) {
            m.shellHpLostThisTurn += res.unblocked;
        }
        // Lagavulin: any unblocked damage wakes it, strips Plating and stuns it.
        if (hadAsleep) {
            m.power[static_cast<int>(PowerId::ASLEEP)] = 0;
            m.power[static_cast<int>(PowerId::PLATING)] = 0;
        }
        if (m.power[static_cast<int>(PowerId::CURL_UP)] > 0) {
            m.block += m.power[static_cast<int>(PowerId::CURL_UP)];
            m.power[static_cast<int>(PowerId::CURL_UP)] = 0;
        }
        if (m.hp <= 0) { m.hp=0;diedThisHit=true;res.wasKilled=true; }

    } else {
        res.total = blockedDamage;
        res.fullyBlocked = blockedDamage > 0;
    }

    if(fromPlayer){
        necrobinder_after_damage_given(*this,idx,res,poweredAttack);
        if(poweredAttack&&!necro.dealingOstyDamage)silent_after_attack_damage(*this,idx,res.unblocked);
    }
    if(diedThisHit)resolve_monster_death(idx);
    // AfterDamageReceived hooks run for surviving targets.

    if (m.alive && m.hp > 0) {
        if (res.blockBroken && m.power[static_cast<int>(PowerId::BURROWED)] > 0) {
            m.power[static_cast<int>(PowerId::BURROWED)] = 0;
            m.block = 0;
            m.stunned = true;
            if (m.id == MonsterId::TUNNELER) m.move = 3;  // DIZZY -> BITE
            roll_intent(*this, m);
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::SHRIEK)] > 0 &&
            m.hp <= m.power[static_cast<int>(PowerId::SHRIEK)]) {
            m.power[static_cast<int>(PowerId::SHRIEK)] = 0;
            m.stunned = true;
            if (m.id == MonsterId::TERROR_EEL) m.move = 2;  // STUN -> TERROR
            roll_intent(*this, m);
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::PLOW)] > 0 &&
            m.hp <= m.power[static_cast<int>(PowerId::PLOW)]) {
            m.power[static_cast<int>(PowerId::PLOW)] = 0;
            m.strength = 0;
            m.stunned = true;
            if (m.id == MonsterId::CEREMONIAL_BEAST) m.move = 2;  // STUN -> BEAST_CRY
            roll_intent(*this, m);
        }
        if (poweredAttack && res.unblocked > 0 &&
            m.power[static_cast<int>(PowerId::FLUTTER)] > 0 &&
            --m.power[static_cast<int>(PowerId::FLUTTER)] == 0) {
            m.stunned = true;
            roll_intent(*this, m);
        }
        if (m.power[static_cast<int>(PowerId::SLIPPERY)] > 0 && res.total != 0) {
            --m.power[static_cast<int>(PowerId::SLIPPERY)];
        }
        if (poweredAttack && m.power[static_cast<int>(PowerId::PERSONAL_HIVE)] > 0) {
            const int count = m.power[static_cast<int>(PowerId::PERSONAL_HIVE)];
            for (int i = 0; i < count; ++i) {
                Card dazed=make_card(CardId::DAZED,false,require_card_uid());
                add_card_to_draw_random(dazed);notify_card_generated(dazed);
            }
        }
        if (poweredAttack && res.unblocked > 0 &&
            m.power[static_cast<int>(PowerId::VITAL_SPARK)] > 0 &&
            !vitalSparkTriggeredThisEnemyTurn) {
            vitalSparkTriggeredThisEnemyTurn = true;
            player.energy += m.power[static_cast<int>(PowerId::VITAL_SPARK)];
        }
        if (res.unblocked > 0 && m.power[static_cast<int>(PowerId::SLUMBER)] > 0) {
            --m.power[static_cast<int>(PowerId::SLUMBER)];
            if (m.power[static_cast<int>(PowerId::SLUMBER)] <= 0) {
                m.power[static_cast<int>(PowerId::PLATING)] = 0;
                m.stunned = true;
                m.move = 2;  // SlumberingBeetle ROLL_OUT_MOVE
                roll_intent(*this, m);
            }
        }
    }

    // CrabRagePower.AfterDeath: any ally death enrages surviving crab members.


    check_outcome();
    return res;
}

int BattleContext::damage_player(int amount, bool unblockable, bool poweredAttack,
                                 bool deferCardRupture) {
    if (amount <= 0 || outcome != Outcome::UNDECIDED) return 0;
    if (poweredAttack && player_power(PowerId::COVERED) > 0) return 0;
    if (player_power(PowerId::INTANGIBLE) > 0) amount = 1;
    int remaining = amount;
    if (!unblockable && player.block > 0) {
        const int blocked = remaining < player.block ? remaining : player.block;
        player.block -= blocked;
        remaining -= blocked;
    }
    // Tungsten Rod / Beating Remnant use ModifyHpLostAfterOsty. Buffer is
    // AfterOstyLate and must remain unspent if those already reduce loss to 0.
    remaining=necrobinder_redirect_damage(*this,remaining,poweredAttack);
    remaining = relics_modify_hp_loss(*this, remaining);
    if (remaining > 0) {
        if (player_power(PowerId::BUFFER) > 0) {
            add_player_power(PowerId::BUFFER, -1);
            remaining = 0;
        }
    }
    if (remaining > 0) {
        player.hp -= remaining;
        relics_current_hp_changed(*this);
        hpLostThisTurn += remaining;
        hpLostThisCombat += remaining;
        if (!unblockable && relic_has(*this, RelicId::LAVA_LAMP)) {
            lavaLampTookQualifyingDamage = true;
        }
        ++unblockedHitsThisCombat;
        player.tookUnblockedDamageThisTurn = true;
        if (poweredAttack) player.tookUnblockedAttackDamageThisCombat = true;
        // TheGambitPower.AfterDamageReceived: only powered, unblocked attack
        // damage kills, and the kill is immediate (PowerCmd.Remove + Kill).
        if (poweredAttack && player_power(PowerId::THE_GAMBIT) > 0) {
            player.power[static_cast<int>(PowerId::THE_GAMBIT)] = 0;
            kill_player();
            return remaining;
        }
        if (player.hp <= 0) {
            kill_player();return remaining;
        }
        relics_damage_received(*this, remaining);
        // RupturePower: only damage taken during the owner's side; damage from
        // the card currently resolving is applied after that card finishes.
        if (!inMonsterTurn && player_power(PowerId::RUPTURE) > 0) {
            const int gain = player_power(PowerId::RUPTURE);
            if (resolvingCard && deferCardRupture) pendingRupture += gain;
            else add_player_power(PowerId::STRENGTH, gain);
        }
        if (!inMonsterTurn && player_power(PowerId::INFERNO) > 0 && outcome == Outcome::UNDECIDED) {
            attack_all(player_power(PowerId::INFERNO), 1, false);
        }
    }
    return remaining;
}

void BattleContext::resolve_monster_death(int idx) {
    Monster &m=monsters[idx];const MonsterDef &def=monster_def(m.id);
    int surpriseGold=-1;
    const int stolenStrength=m.power[static_cast<int>(PowerId::POSSESS_STRENGTH)]>0?m.aux[0]:0;
    const int stolenSpeed=m.power[static_cast<int>(PowerId::POSSESS_SPEED)]>0?m.aux[0]:0;
    const bool removalPrevented=m.power[static_cast<int>(PowerId::STEAM_ERUPTION)]>0 ||
        (m.power[static_cast<int>(PowerId::ADAPTABLE)]>0&&def.reviveState!=255&&m.aux[0]<2) ||
        m.power[static_cast<int>(PowerId::REATTACH)]>0 || m.power[static_cast<int>(PowerId::DOOR_REVIVAL)]>0;

            m.hp = 0;
            // Each SwipePower creates its own skippable special-card reward
            // in BeforeDeath. The run layer resolves the original deck card.
            for (int i = 0; i < theftCount; ++i) {
                if (theftOwners[i] == idx && !theftReturned[i]) theftReturned[i] = true;
            }
            if (m.power[static_cast<int>(PowerId::STEAM_ERUPTION)] > 0 &&
                m.id == MonsterId::WATERFALL_GIANT) {
                // TriggerAboutToBlowState keeps the giant in the encounter
                // through its windup and explosion.
                m.alive = true;
                m.reviving = false;
                m.stunned = false;
                m.hp = m.maxHp = 999999999;
                m.block = 0;
                m.move = 6;  // ABOUT_TO_BLOW -> EXPLODE
                relics_monster_died(*this);
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::ILLUSION)] > 0) {
                // Illusions remain in combat after death and revive on their
                // next turn, but are secondary enemies and do not delay victory.
                m.reviving = true;
                m.alive = true;
                m.stunned = false;
                m.combatEndBlocker = false;
                m.block = 0;
                m.weak = m.vulnerable = 0;
                m.power[static_cast<int>(PowerId::GRAPPLE)] = 0;
                m.grappleCount = 0;
                m.power[static_cast<int>(PowerId::MINION)] = 1;
                relics_monster_died(*this);
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::ADAPTABLE)] > 0 &&
                def.reviveState != 255 && m.aux[0] < 2) {
                // Test Subject: knocked out, revives on its next turn.
                m.reviving = true;
                m.combatEndBlocker = true;
                m.move = def.reviveState;
                m.block = 0;
                roll_intent(*this, m);
            } else if (m.power[static_cast<int>(PowerId::STOCK)] > 0) {
                const int stock = m.power[static_cast<int>(PowerId::STOCK)];
                const MonsterId id = m.id;
                const int slot = idx;
                m.alive = false;
                relics_monster_died(*this);
                spawn_monster(*this, id, slot);
                monsters[slot].power[static_cast<int>(PowerId::STOCK)] = stock - 1;
                monsters[slot].move = 0;  // Axebot stock respawns in BOOT_UP.
                roll_intent(*this, monsters[slot]);
            } else if (m.power[static_cast<int>(PowerId::INFESTED)] > 0) {
                const int infested = m.power[static_cast<int>(PowerId::INFESTED)];
                const int deadSlot = idx;
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
                int nextSlot = deadSlot;
                for (int i = 0; i < infested && i < MAX_MONSTERS; ++i) {
                    if (i > 0) {
                        if (monsterCount < MAX_MONSTERS) {
                            nextSlot = monsterCount;
                        } else {
                            nextSlot = -1;
                            for (int s = 0; s < monsterCount; ++s) {
                                if (!monsters[s].alive && !monsters[s].reviving) {
                                    nextSlot = s;
                                    break;
                                }
                            }
                            if (nextSlot < 0) break;
                        }
                    }
                    spawn_monster(*this, MonsterId::WRIGGLER, nextSlot);
                    monsters[nextSlot].stunned = true;
                    monsterCount = std::max(monsterCount, nextSlot + 1);
                }
            } else if (m.power[static_cast<int>(PowerId::REATTACH)] > 0) {
                bool siblingAlive = false;
                for (int i = 0; i < monsterCount; ++i) {
                    if (i != idx && monsters[i].id == MonsterId::DECIMILLIPEDE_SEGMENT &&
                        monsters[i].alive && !monsters[i].reviving && monsters[i].hp > 0) {
                        siblingAlive = true;
                        break;
                    }
                }
                if (siblingAlive) {
                    m.reviving = true;
                    m.alive = true;  // non-interactable, but still gets a reattach turn
                    m.block = 0;
                    m.move = 3;  // DEAD_MOVE; follow-up is REATTACH_MOVE (4)
                    roll_intent(*this, m);
                } else {
                    for (int i = 0; i < monsterCount; ++i) {
                        if (monsters[i].id == MonsterId::DECIMILLIPEDE_SEGMENT &&
                            monsters[i].reviving) {
                            monsters[i].reviving = false;
                            monsters[i].alive = false;
                        }
                    }
                    m.reviving = false;
                    m.alive = false;
                    relics_monster_died(*this);
                }
            } else if (m.power[static_cast<int>(PowerId::DOOR_REVIVAL)] > 0) {
                m.reviving = true;
                m.alive = true;
                m.block = 0;
                m.move = 3;  // Door DEAD_MOVE
                roll_intent(*this, m);
                int slot = -1;
                for (int i = 0; i < monsterCount; ++i) {
                    if (monsters[i].id == MonsterId::DOORMAKER &&
                        !monsters[i].alive && monsters[i].hp > 0) {
                        slot = i;
                        break;
                    }
                }
                if (slot >= 0) {
                    // Door owns the same Doormaker creature across phases.
                    monsters[slot].alive = true;
                    roll_intent(*this, monsters[slot]);
                } else {
                    slot = monsterCount < MAX_MONSTERS ? monsterCount : -1;
                    if (slot < 0) {
                        for (int i = 0; i < monsterCount; ++i) {
                            if (i != idx && !monsters[i].alive && !monsters[i].reviving) {
                                slot = i;
                                break;
                            }
                        }
                    }
                    if (slot >= 0) {
                        spawn_monster(*this, MonsterId::DOORMAKER, slot);
                        monsterCount = std::max(monsterCount, slot + 1);
                    }
                }
            } else if (m.power[static_cast<int>(PowerId::SURPRISE)] > 0) {
                surpriseGold = m.stolenGold;
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
            } else {
                if (m.id == MonsterId::FAT_GREMLIN && m.stolenGold > 0) {
                    recoveredStolenGold += m.stolenGold;
                    m.stolenGold = 0;
                }
                m.alive = false;
                m.combatEndBlocker = false;
                relics_monster_died(*this);
            }
        
        if (player_power(PowerId::SURROUNDED) > 0) {
            int first = -1;
            bool allLeft = true;
            bool allRight = true;
            for (int i = 0; i < monsterCount; ++i) {
                if (!monsters[i].alive || monsters[i].reviving) continue;
                if (first < 0) first = i;
                allLeft &= monsters[i].power[static_cast<int>(PowerId::BACK_ATTACK_LEFT)] > 0;
                allRight &= monsters[i].power[static_cast<int>(PowerId::BACK_ATTACK_RIGHT)] > 0;
            }
            if (first >= 0 && (allLeft || allRight)) face_surrounded_target(first);
        }
        for (int i = 0; i < monsterCount; ++i) {
            Monster &ally = monsters[i];
            if (i != idx && ally.alive && !ally.reviving &&
                ally.power[static_cast<int>(PowerId::RAVENOUS)] > 0) {
                ally.strength += ally.power[static_cast<int>(PowerId::RAVENOUS)];
                ally.stunned = true;
                roll_intent(*this, ally);
            }
            if (i != idx && ally.alive && ally.power[static_cast<int>(PowerId::CRAB_RAGE)] > 0) {
                ally.strength += 5;
                ally.block += 99;
                ally.power[static_cast<int>(PowerId::CRAB_RAGE)] = 0;
            }
        }
        // Possess powers return exactly the amount stolen by this owner.
        if (stolenStrength != 0) add_player_power(PowerId::STRENGTH, stolenStrength);
        if (stolenSpeed != 0) add_player_power(PowerId::DEXTERITY, stolenSpeed);
        if (surpriseGold >= 0) {
        spawn_monster(*this, MonsterId::SNEAKY_GREMLIN);
        int fatSlot = -1;
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive && !monsters[i].reviving) { fatSlot = i; break; }
        }
        if (fatSlot < 0 && monsterCount < MAX_MONSTERS) fatSlot = monsterCount++;
        if (fatSlot >= 0) {
            spawn_monster(*this, MonsterId::FAT_GREMLIN, fatSlot);
            monsters[fatSlot].stolenGold = surpriseGold;
        }
    }
    necrobinder_after_death(*this,removalPrevented);
}
void BattleContext::kill_monster(int idx) {
    if(idx<0||idx>=monsterCount||!monsters[idx].alive||monsters[idx].reviving)return;
    monsters[idx].hp=0;resolve_monster_death(idx);check_outcome();
}
void BattleContext::kill_player() {
    player.hp=0;relics_current_hp_changed(*this);
    if(try_fairy_revive()||relics_try_revive(*this)){necrobinder_after_death(*this,true);return;}
    necrobinder_after_death(*this,false);necrobinder_kill_osty(*this);outcome=Outcome::PLAYER_LOSS;
}
}
