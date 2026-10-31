#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
#include "sts2/relic_persistent.h"
#include "sts2/silent.h"
#include "sts2/defect.h"
#include "sts2/necrobinder.h"
#include "sts2/regent.h"
namespace sts2 {
int &power_ref(Player &,PowerId);
static void remove_at(Card *cards,int &count,int index){for(int i=index;i+1<count;++i)cards[i]=cards[i+1];--count;}

void BattleContext::start_player_turn() {
    ++turn;
    // PlatingPower.BeforeSideTurnStart: at the start of round 1 enemies gain
    // block equal to their plating.
    if (turn == 1) {
        for (int i = 0; i < monsterCount; ++i) {
            const int plating = monsters[i].power[static_cast<int>(PowerId::PLATING)];
            if (monsters[i].alive && plating > 0) monsters[i].block += plating;
        }
    }
    // RampartPower.AfterSideTurnStart(Player): every Rampart owner supplies
    // its Amount to all TurretOperator allies.
    for (int i = 0; i < monsterCount; ++i) {
        if (!monsters[i].alive ||
            monsters[i].power[static_cast<int>(PowerId::RAMPART)] <= 0) {
            continue;
        }
        const int amount = monsters[i].power[static_cast<int>(PowerId::RAMPART)];
        for (int j = 0; j < monsterCount; ++j) {
            if (monsters[j].alive && monsters[j].id == MonsterId::TURRET_OPERATOR) {
                monsters[j].block += amount;
            }
        }
    }
    player.tookUnblockedDamageThisTurn = false;
    if (player_power(PowerId::BARRICADE) <= 0) {
        const int keep = relics_block_retain(*this);
        player.block = keep > 0 ? std::min(player.block, keep) : 0;
    }
    // AfterBlockCleared runs at the start of the owner's turn, including
    // turns where no block was present or Barricade retained it.
    for (int i = 0; i < toricCount;) {
        gain_block(toricBlock[i], false, false);
        --toricTurns[i];
        add_player_power(PowerId::TORIC_TOUGHNESS, -1);
        if (toricTurns[i] <= 0) {
            player.toricToughnessBlock -= toricBlock[i];
            for (int j = i; j + 1 < toricCount; ++j) {
                toricBlock[j] = toricBlock[j + 1];
                toricTurns[j] = toricTurns[j + 1];
            }
            --toricCount;
        } else {
            ++i;
        }
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::BLOCK_NEXT_TURN) > 0) {
        const int b = player_power(PowerId::BLOCK_NEXT_TURN);
        add_player_power(PowerId::BLOCK_NEXT_TURN, -b);
        gain_block(b, false, false);
    }
    int baseEnergy = player.energyPerTurn;
    if (player_power(PowerId::PYRE) > 0) baseEnergy += player_power(PowerId::PYRE);
    player.energy = relics_energy_for_turn(*this, baseEnergy) + nextTurnEnergy;
    nextTurnEnergy = 0;
    relic_persistent_after_energy_reset(*this);
    // RadiancePower.AfterEnergyReset: +1 energy, then one stack expires.
    if (player_power(PowerId::RADIANCE) > 0) {
        player.energy += 1;
        add_player_power(PowerId::RADIANCE, -1);
    }

    cardsPlayedThisTurn = 0;
    attacksPlayedThisTurn = 0;
    skillsPlayedThisTurn = 0;
    hpLostThisTurn = 0;
    exhaustedThisTurn = 0;
    cardsDrawnThisTurn = 0;
    gainedBlockFromCardThisTurn = false;
    blockCardPlaysThisTurn = 0;
    blockPlayIndex = -1;
    playedAttackOrSkillThisTurn = false;
    attackSkillPlaysThisTurn = 0;
    // HardenedShellPower.BeforeSideTurnStart(side Player): the per-turn HP-loss
    // allowance is restored at the start of every player turn.
    for (int i = 0; i < monsterCount; ++i) monsters[i].shellHpLostThisTurn = 0;
    jugglingTriggeredThisTurn = false;
    reboundPending = false;
    skillsLocked = false;
    relics_turn_start(*this);
    if (outcome != Outcome::UNDECIDED) return;

    if (player_power(PowerId::DEMON_FORM) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::DEMON_FORM));
    // Both native hooks run in the order the power instances were acquired.
    // This is observable with unequal SelfDamage values and one Buffer charge.
    const auto crimsonTurnStart = [&]() {
        if (player_power(PowerId::CRIMSON_MANTLE) <= 0 || outcome != Outcome::UNDECIDED) return;
        damage_player(player.crimsonMantleSelfDamage, true);
        if (outcome == Outcome::UNDECIDED)
            gain_block(player_power(PowerId::CRIMSON_MANTLE), false, false);
    };
    const auto infernoTurnStart = [&]() {
        if (player_power(PowerId::INFERNO) > 0 && outcome == Outcome::UNDECIDED)
            damage_player(player.infernoSelfDamage, true);
    };
    if (player.infernoBeforeCrimsonMantle) {
        infernoTurnStart();
        crimsonTurnStart();
    } else {
        crimsonTurnStart();
        infernoTurnStart();
    }
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < rollingCount && outcome == Outcome::UNDECIDED; ++i) {
        attack_all(rollingDamage[i], 1, false);
        rollingDamage[i] += 5;
        power_ref(player, PowerId::ROLLING_BOULDER) += 5;
    }
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::PREP_TIME) > 0) add_player_power(PowerId::VIGOR, player_power(PowerId::PREP_TIME));

    // Cards whose cost was changed "this turn" expire now, wherever they are;
    // free-until-played costs persist until that copy is played.  Hidden Gem's
    // replay is BaseReplayCount (permanent for the combat), not a turn effect.
    for (int i = 0; i < handCount; ++i) card_restore_cost(hand[i]);
    for (int i = 0; i < drawCount; ++i) card_restore_cost(draw[i]);
    for (int i = 0; i < discardCount; ++i) card_restore_cost(discard[i]);

    for (int i = 0; i < returnNextTurnCount; ++i) add_card_to_hand(returnNextTurn[i]);
    returnNextTurnCount = 0;

    // ---- BeforeHandDraw hooks (all run before the hand is drawn) ----------
    // ThrummingHatchet.BeforeHandDraw: the exact instance played last round
    // returns from whichever pile holds it (normally the discard pile).
    recall_played_last_turn(CardId::THRUMMING_HATCHET);
    // HowlFromBeyond.BeforeHandDraw: every exhausted copy auto-plays.
    if (exhaustCount > 0) {
        std::uint16_t howls[MAX_PILE];
        int howlN = 0;
        for (int i = 0; i < exhaustCount; ++i) {
            if (exhaust[i].id == CardId::HOWL_FROM_BEYOND) howls[howlN++] = exhaust[i].uid;
        }
        for (int i = 0; i < howlN && outcome == Outcome::UNDECIDED; ++i) {
            for (int j = 0; j < exhaustCount; ++j) {
                if (exhaust[j].uid != howls[i]) continue;
                Card c = exhaust[j];
                for (int k = j; k + 1 < exhaustCount; ++k) exhaust[k] = exhaust[k + 1];
                --exhaustCount;
                auto_play_random(c, false);
                break;
            }
        }
    }
    // AggressionPower.BeforeSideTurnStart: move Amount random attacks from the
    // discard pile to hand and upgrade them, before the draw/shuffle.
    if (player_power(PowerId::AGGRESSION) > 0 && discardCount > 0) {
        int idxs[MAX_PILE];
        int n = 0;
        for (int i = 0; i < discardCount; ++i) {
            if (card_is_attack(discard[i])) idxs[n++] = i;
        }
        for (int i = n - 1; i > 0; --i) {
            const int j = cardSelectionRng.next_int(0, i);
            std::swap(idxs[i], idxs[j]);
        }
        const int take = std::min(n, player_power(PowerId::AGGRESSION));
        int chosen[MAX_PILE];
        for (int k = 0; k < take; ++k) chosen[k] = idxs[k];
        // Sort the chosen indices descending so removals do not shift the rest.
        for (int a = 1; a < take; ++a) {
            const int v = chosen[a];
            int b = a - 1;
            while (b >= 0 && chosen[b] < v) { chosen[b + 1] = chosen[b]; --b; }
            chosen[b + 1] = v;
        }
        for (int k = 0; k < take; ++k) {
            Card c = discard[chosen[k]];
            if (card_upgradable(c)) upgrade_card(c);
            add_card_to_hand(c);
        }
        for (int k = 0; k < take; ++k) {
            const int idx = chosen[k];
            for (int j = idx; j + 1 < discardCount; ++j) discard[j] = discard[j + 1];
            --discardCount;
        }
    }
    // HelloWorldPower.BeforeHandDraw: add distinct unlocked Ironclad commons
    // before the normal hand draw.
    if (player_power(PowerId::HELLO_WORLD) > 0) {
        CardId pool[static_cast<int>(CardId::COUNT)];
        int n = 0;
        for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
            const CardDef &d = card_def(static_cast<CardId>(i));
        if (!card_native_available(static_cast<CardId>(i))) continue;
            if (d.pool == CardPool::IRONCLAD && d.rarity == Rarity::COMMON &&
                !(d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY |
                             CF_CANNOT_GENERATE_IN_COMBAT))) {
                pool[n++] = static_cast<CardId>(i);
            }
        }
        CardId picked[16];
        int pickedN = 0;
        const int wanted = std::min(player_power(PowerId::HELLO_WORLD),
                                    static_cast<int>(sizeof(picked) / sizeof(picked[0])));
        for (int guard = 0; guard < 256 && pickedN < wanted && n > 0; ++guard) {
            const int idx = cardGenerationRng.next_int(0, n - 1);
            bool duplicate = false;
            for (int j = 0; j < pickedN; ++j) duplicate |= picked[j] == pool[idx];
            if (duplicate) continue;
            picked[pickedN++] = pool[idx];
            add_card_to_hand(make_card(pool[idx], false, require_card_uid()));
        }
    }

    int drawCountThisTurn = relics_modify_draw(*this, player.drawPerTurn) + nextTurnDraw;
    nextTurnDraw = 0;
    // ClarityPower.ModifyHandDraw: one extra card for each remaining turn.
    const bool clarity = player_power(PowerId::CLARITY) > 0;
    // Innate cards go on top of the draw pile on turn 1; the opening draw is
    // max(normal draw, innate count), capped at the 10-card hand (C# CombatManager).
    if (turn == 1) {
        Card ordered[MAX_PILE];
        int n = 0;
        int innate = 0;
        for (int i = 0; i < drawCount; ++i) {
            if (!card_has(draw[i], CF_INNATE)) ordered[n++] = draw[i];
        }
        for (int i = 0; i < drawCount; ++i) {
            if (card_has(draw[i], CF_INNATE)) { ordered[n++] = draw[i]; ++innate; }
        }
        for (int i = 0; i < n; ++i) draw[i] = ordered[i];
        drawCount = n;
        knownTopCount = innate;
        drawCountThisTurn = std::min(MAX_HAND, std::max(drawCountThisTurn, innate));
    }
    if (clarity) drawCountThisTurn += 1;
    draw_cards(drawCountThisTurn);
    if (clarity) add_player_power(PowerId::CLARITY, -1);
    if (outcome != Outcome::UNDECIDED) return;
    // A Stratagem selection interrupted the draw; it resumes when resolved.
    if (pending.op != ChoiceOp::NONE) return;
    relics_hand_drawn(*this);

    // powers that act on the drawn hand
    if (player_power(PowerId::ENTROPY) > 0) {
        int n = player_power(PowerId::ENTROPY);
        while (n-- > 0 && handCount > 0) {
            const int idx = cardGenerationRng.next_int(0, handCount - 1);
            transform_card(hand[idx]);
        }
    }
    if (player_power(PowerId::AGGRESSION) > 0) {
        int attacks[MAX_PILE];
        int n = 0;
        for (int i = 0; i < discardCount; ++i) {
            if (card_is_attack(discard[i])) attacks[n++] = i;
        }
        if (n > 0) {
            const int idx = attacks[cardSelectionRng.next_int(0, n - 1)];
            Card c = discard[idx];
            remove_at(discard, discardCount, idx);
            upgrade_card(c);
            add_card_to_hand(c);
        }
    }
    if (player_power(PowerId::MAYHEM) > 0) {
        auto_play_from_draw(player_power(PowerId::MAYHEM), false);
    }
    relic_persistent_finish_turn_start(*this);
}

void BattleContext::end_player_turn() {
    if (outcome != Outcome::UNDECIDED) return;
    if (turn >= 200) {  // stalemate cutoff, not a game-rule defeat
        outcome = Outcome::TRUNCATED;
        return;
    }
    // Rounds are the unit ThrummingHatchet's BeforeHandDraw looks back on.
    playedLastTurnCount = 0;
    for (int i = 0; i < playedThisTurnCount && playedLastTurnCount < MAX_PILE; ++i) {
        bool dup = false;
        for (int j = 0; j < playedLastTurnCount; ++j) {
            dup = dup || playedLastTurn[j] == playedThisTurn[i];
        }
        if (!dup) playedLastTurn[playedLastTurnCount++] = playedThisTurn[i];
    }
    playedThisTurnCount = 0;
    // end-of-turn powers
    if (player_power(PowerId::CONSTRICT) > 0) {
        damage_player(player_power(PowerId::CONSTRICT));
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::STAMPEDE) > 0) {
        int attacks = player_power(PowerId::STAMPEDE);
        while (attacks-- > 0 && handCount > 0 && outcome == Outcome::UNDECIDED) {
            int candidates[MAX_HAND];
            int n = 0;
            for (int i = 0; i < handCount; ++i) if (card_is_attack(hand[i])) candidates[n++] = i;
            if (n == 0) break;
            const int idx = candidates[cardSelectionRng.next_int(0, n - 1)];
            Card c = hand[idx];
            remove_at(hand, handCount, idx);
            // StampedePower -> CardCmd.AutoPlay: the whole play lifecycle
            // (counters, Rage/after-play hooks, Duplication) must run.
            auto_play_random(c, false);
        }
    }
    // Each bomb instance counts down and explodes independently; power duration
    // (Unpowered) ignores strength and vulnerable.
    for (int i = 0; i < bombCount;) {
        if (--bombTurns[i] > 0) { ++i; continue; }
        const int dmg = bombDamage[i];
        for (int j = i; j + 1 < bombCount; ++j) {
            bombTurns[j] = bombTurns[j + 1];
            bombDamage[j] = bombDamage[j + 1];
        }
        --bombCount;
        attack_all(dmg, 1, false);
        if (outcome != Outcome::UNDECIDED) return;
    }
    if (player_power(PowerId::PLATING) > 0)
        gain_block(player_power(PowerId::PLATING), false, false);
    if (player_power(PowerId::REGEN) > 0) {
        heal_hp(player_power(PowerId::REGEN));
        add_player_power(PowerId::REGEN, -1);
    }
    relics_turn_end(*this);
    relics_after_turn(*this);
    if (outcome != Outcome::UNDECIDED) return;

    discard_hand();
    if (outcome != Outcome::UNDECIDED) return;
    flush_ethereal_exhaust_hooks();
    if (player.tempStrength != 0) {
        player.strength -= player.tempStrength;
        player.tempStrength = 0;
    }
    if (player.tempDexterity != 0) {
        player.dexterity -= player.tempDexterity;
        player.tempDexterity = 0;
    }
    if (player_power(PowerId::RITUAL) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RITUAL));
    if (player_power(PowerId::RAGE) > 0) add_player_power(PowerId::RAGE, -player_power(PowerId::RAGE));
    // DuplicationPower.AfterTurnEnd(owner side): copies expire at the end of
    // the turn in which they were applied.
    if (player_power(PowerId::DUPLICATION) > 0)
        add_player_power(PowerId::DUPLICATION, -player_power(PowerId::DUPLICATION));
    // One-Two Punch expires at end of turn.  FreeAttackPower has no end-of-turn
    // removal: it is consumed by the next attack that is actually played.
    if (player_power(PowerId::ONE_TWO_PUNCH) > 0) add_player_power(PowerId::ONE_TWO_PUNCH, -player_power(PowerId::ONE_TWO_PUNCH));
    if (player_power(PowerId::SETUP_STRIKE) > 0) add_player_power(PowerId::SETUP_STRIKE, -player_power(PowerId::SETUP_STRIKE));
    if (player_power(PowerId::EQUILIBRIUM) > 0) add_player_power(PowerId::EQUILIBRIUM, 0);
    if (player_power(PowerId::RETAIN_HAND) > 0) add_player_power(PowerId::RETAIN_HAND, -1);
    if (player_power(PowerId::NO_BLOCK) > 0) add_player_power(PowerId::NO_BLOCK, -1);
    if (player_power(PowerId::TENDER) > 0) {
        add_player_power(PowerId::STRENGTH, cardsPlayedThisTurn);
        player.dexterity += cardsPlayedThisTurn;
    }
    player.power[static_cast<int>(PowerId::RINGING)] = 0;
    // GrapplePower.AfterTurnEnd removes the debuff at the end of the turn
    // (TheGambit kills immediately in damage_player, never at turn end).
    for (int i = 0; i < monsterCount; ++i) {
        monsters[i].power[static_cast<int>(PowerId::GRAPPLE)] = 0;
        monsters[i].grappleCount = 0;
    }

    for (int i = 0; i < panacheCount; ++i) panacheLeft[i] = 5;
    for (int i = 0; i < monsterCount; ++i) monsters[i].skittishTriggeredThisTurn = false;
    monster_turn();
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < monsterCount; ++i) {
        if (monsters[i].tempStrengthLoss != 0) {
            monsters[i].strength += monsters[i].tempStrengthLoss;
            monsters[i].tempStrengthLoss = 0;
        }
    }
    // IntangiblePower.AfterTurnEnd: expires after the enemy turn it protected
    // against (it does not tick at the start of the next player turn).
    if (player_power(PowerId::INTANGIBLE) > 0) add_player_power(PowerId::INTANGIBLE, -1);
    if (player.vulnerable > 0 && !vulnerableSkipTick) --player.vulnerable;
    if (player.weak > 0 && !weakSkipTick) --player.weak;
    if (player.frail > 0 && !frailSkipTick) --player.frail;
    weakSkipTick = false;
    frailSkipTick = false;
    vulnerableSkipTick = false;
    // PlatingPower.AfterTurnEnd(side Enemy): the player's plating decays once
    // per enemy turn (enemy plating decays by the player count, i.e. one).
    if (player_power(PowerId::PLATING) > 0) add_player_power(PowerId::PLATING, -1);
    if (player_power(PowerId::SHRINK) > 0) add_player_power(PowerId::SHRINK, -1);
    add_player_power(PowerId::FLAME_BARRIER, 0);
    player.power[static_cast<int>(PowerId::FLAME_BARRIER)] = 0;
    // ColossusPower.AfterTurnEnd(side Enemy) ticks its duration once per enemy
    // turn; it does not disappear after a single turn.
    if (player_power(PowerId::COLOSSUS) > 0) add_player_power(PowerId::COLOSSUS, -1);
    player.power[static_cast<int>(PowerId::NO_DRAW)] = 0;
    player.power[static_cast<int>(PowerId::EQUILIBRIUM)] = 0;
    start_player_turn();
}

void BattleContext::monster_turn() {
    inMonsterTurn = true;
    vitalSparkTriggeredThisEnemyTurn = false;
    // SlowPower.AfterSideTurnStart: the card count resets when the monsters'
    // own side begins its turn.
    for (int i = 0; i < monsterCount; ++i) monsters[i].slowCardsThisTurn = 0;
    // SandpitPower.AfterSideTurnStart decrements before any enemy acts.  Its
    // removal kills the targeted player outright, bypassing death prevention.
    for (int i = 0; i < monsterCount; ++i) {
        Monster &m = monsters[i];
        int &sandpit = m.power[static_cast<int>(PowerId::SANDPIT)];
        if (!m.alive || sandpit <= 0) continue;
        if (--sandpit == 0) {
            player.hp = 0;
            check_outcome();
            inMonsterTurn = false;
            return;
        }
    }
    for (int i = 0; i < monsterCount; ++i) {
        if (!monsters[i].alive) continue;
        monster_act(*this, monsters[i]);
        check_outcome();
        if (outcome != Outcome::UNDECIDED) break;
    }
    if (outcome == Outcome::UNDECIDED) {
        // DemisePower.AfterTurnEnd(owner side): damage is Unblockable and
        // Unpowered, and the power remains for later enemy turns.
        for (int i = 0; i < monsterCount; ++i) {
            if (!monsters[i].alive) continue;
            const int amount = monsters[i].power[static_cast<int>(PowerId::DEMISE)];
            if (amount <= 0) continue;
            damage_monster(i, amount, true, false, true);
            check_outcome();
            if (outcome != Outcome::UNDECIDED) break;
        }
    }
    inMonsterTurn = false;
}

void BattleContext::discard_hand() {
    // end-of-turn in-hand status/curses triggers (C# HasTurnEndInHandEffect).
    const int handAtEnd = handCount;
    for (int i = 0; i < handCount && outcome == Outcome::UNDECIDED; ++i) {
        const Card &c = hand[i];
        switch (c.id) {
            case CardId::BURN:
            case CardId::TOXIC:
            case CardId::INFECTION:
                damage_player(card_var(c, VarId::DAMAGE));
                break;
            case CardId::BECKON:
                damage_player(card_var(c, VarId::HP_LOSS), true);
                break;
            // Curses -----------------------------------------------------
            case CardId::DECAY:  // DamageVar 2, unpowered but blockable
                damage_player(card_var(c, VarId::DAMAGE));
                break;
            case CardId::BAD_LUCK:  // 13 unblockable/unpowered
                damage_player(card_var(c, VarId::HP_LOSS), true);
                break;
            case CardId::REGRET:  // HP loss equal to cards in hand at turn end
                damage_player(handAtEnd, true);
                break;
            case CardId::DOUBT: {
                // A debuff applied to the player skips its first tick; Artifact
                // intercepts it like any other visible debuff.
                add_player_power(PowerId::WEAK, card_var(c, VarId::WEAK));
                break;
            }
            case CardId::SHAME: {
                add_player_power(PowerId::FRAIL, card_var(c, VarId::FRAIL));
                break;
            }
            case CardId::DEBT: {
                const int loss = std::min(card_var(c, VarId::GOLD), gold);
                gold -= loss;
                break;
            }
            default:
                break;
        }
    }
    Card kept[MAX_HAND];
    int keptN = 0;
    const bool retainAll = player_power(PowerId::RETAIN_HAND) > 0 ||
                           player_power(PowerId::EQUILIBRIUM) > 0 ||
                           relic_has(*this, RelicId::RUNIC_PYRAMID);
    while (handCount > 0) {
        Card c = hand[--handCount];
        // Ethereal is resolved before retention (C# CombatManager end-of-turn).
        if (card_has(c, CF_ETHEREAL) || c.etherealThisCombat ||
            player_power(PowerId::HEX) > 0) {
            move_to_exhaust(c, true);
        } else if (card_has(c, CF_RETAIN) || retainAll) {
            if (keptN < MAX_HAND) kept[keptN++] = c;
        } else {
            move_to_discard(c);
        }
    }
    for (int i = keptN - 1; i >= 0; --i) hand[handCount++] = kept[i];
}
}
