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
    // SideTurnStart: per-turn history counters reset before energy and draw.
    silent_reset_turn_counters(*this);
    defect_begin_turn(*this);
    necrobinder_player_turn_start(*this);
    regent_reset_turn(*this);
    regent_after_side_turn_start(*this);
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
    // BlurPower.BeforeSideTurnStart: block is not removed this turn.
    if (player_power(PowerId::BARRICADE) <= 0 && player_power(PowerId::BLUR) <= 0) {
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
    // WasteAwayPower.ModifyMaxEnergy: reduce the player's maximum energy.
    baseEnergy = std::max(0, baseEnergy - player_power(PowerId::WASTE_AWAY));
    player.energy = relics_energy_for_turn(*this, baseEnergy) + nextTurnEnergy;
    nextTurnEnergy = 0;
    relic_persistent_after_energy_reset(*this);
    // RadiancePower.AfterEnergyReset: +1 energy, then one stack expires.
    if (player_power(PowerId::RADIANCE) > 0) {
        player.energy += 1;
        add_player_power(PowerId::RADIANCE, -1);
    }
    defect_after_energy_reset(*this);
    necrobinder_after_energy_reset(*this);
    regent_after_energy_reset(*this);
    player.energy += necrobinder_extra_energy(*this);
    // "Next turn" powers grant their payload once, then expire.
    if (player_power(PowerId::ENERGY_NEXT_TURN) > 0) {
        const int n = player_power(PowerId::ENERGY_NEXT_TURN);
        player.energy += n;
        add_player_power(PowerId::ENERGY_NEXT_TURN, -n);
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
            if (d.pool == characterPool && d.rarity == Rarity::COMMON &&
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

    // ---- character BeforeHandDraw hooks ----
    necrobinder_after_side_turn_start(*this);
    silent_before_hand_draw(*this);
    defect_before_hand_draw(*this);
    necrobinder_before_hand_draw(*this);
    regent_before_hand_draw(*this);
    if (outcome != Outcome::UNDECIDED) return;

    int drawCountThisTurn = relics_modify_draw(*this, player.drawPerTurn) + nextTurnDraw;
    nextTurnDraw = 0;
    drawCountThisTurn = defect_modify_hand_draw(*this, drawCountThisTurn);
    drawCountThisTurn += necrobinder_extra_draw(*this);
    // ToolsOfTheTradePower.ModifyHandDraw: the discard happens after the
    // enlarged hand draw, not as a separate draw in AfterPlayerTurnStart.
    drawCountThisTurn += player_power(PowerId::TOOLS_OF_THE_TRADE);
    // TyrannyPower.ModifyHandDraw: draws Amount extra, then exhausts Amount
    // cards from hand in AfterPlayerTurnStart.
    drawCountThisTurn += player_power(PowerId::TYRANNY);
    if (player_power(PowerId::DRAW_CARDS_NEXT_TURN) > 0) {
        const int n = player_power(PowerId::DRAW_CARDS_NEXT_TURN);
        drawCountThisTurn += n;
        add_player_power(PowerId::DRAW_CARDS_NEXT_TURN, -n);
    }
    // MindRotPower.ModifyHandDraw: reduce the turn-start hand draw.
    if (player_power(PowerId::MIND_ROT) > 0)
        drawCountThisTurn = std::max(0, drawCountThisTurn - player_power(PowerId::MIND_ROT));
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

    // AfterPlayerTurnStart / AfterSideTurnStart character hooks.
    silent_after_player_turn_start(*this);
    if (pending.op != ChoiceOp::NONE || outcome != Outcome::UNDECIDED) return;
    defect_player_turn_start(*this);
    necrobinder_after_player_turn_start(*this);
    silent_player_turn_start(*this);
    defect_after_side_turn_start(*this);
    if (outcome != Outcome::UNDECIDED) return;

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
    // TyrannyPower.AfterPlayerTurnStart: exhaust the extra cards it drew. This
    // may open a hand selector, which the caller drives before acting.
    regent_after_player_turn_start(*this);
    // Imbued.AfterAutoPrePlayPhaseEntered: every Imbued card auto-plays once,
    // on turn 1 only. The card normally waits at the bottom of the draw pile;
    // scan the hand too in case a small deck drew it.
    if (turn <= 1 && outcome == Outcome::UNDECIDED && pending.op == ChoiceOp::NONE) {
        Card imbued[MAX_PILE];
        int n = 0;
        for (int i = 0; i < drawCount && n < MAX_PILE; ++i)
            if (draw[i].enchantment == EnchantmentId::IMBUED && !draw[i].enchantmentDisabled)
                imbued[n++] = draw[i];
        for (int i = 0; i < handCount && n < MAX_PILE; ++i)
            if (hand[i].enchantment == EnchantmentId::IMBUED && !hand[i].enchantmentDisabled)
                imbued[n++] = hand[i];
        if (n > 0) auto_play_cards(imbued, n);
    }
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
    // PaelsEye.BeforeSideTurnEndEarly: on a turn with no card plays, exhaust
    // the remaining hand and take an extra player turn (once per combat).
    if (relic_has(*this, RelicId::PAELS_EYE) && !(paelsEyeState & PAELS_EYE_USED) &&
        cardsPlayedThisTurn == 0) {
        Card remaining[MAX_PILE];
        const int n = handCount;
        for (int i = 0; i < n; ++i) remaining[i] = hand[i];
        handCount = 0;
        for (int i = 0; i < n; ++i) {
            move_to_exhaust(remaining[i]);
            if (outcome != Outcome::UNDECIDED) return;
        }
        paelsEyeState |= PAELS_EYE_EXTRA_TURN;
    }
    relics_turn_end(*this);
    relics_after_turn(*this);
    if (outcome != Outcome::UNDECIDED) return;

    // OrbQueue.BeforeTurnEnd and Hailstorm precede hand end-of-turn/Ethereal.
    defect_before_side_turn_end(*this);
    if (outcome != Outcome::UNDECIDED) return;
    discard_hand();
    if (outcome != Outcome::UNDECIDED) return;
    flush_ethereal_exhaust_hooks();
    // PlayerCombatState.EndOfTurnCleanup runs after the flush: every card in
    // combat drops its EndOfTurn local cost modifiers (expiration 2).
    for (Card *pile : {hand, draw, discard, exhaust, playPile, returnNextTurn}) {
        const int count = pile == hand ? handCount : pile == draw ? drawCount
                        : pile == discard ? discardCount : pile == exhaust ? exhaustCount
                        : pile == playPile ? playCount : returnNextTurnCount;
        for (int i = 0; i < count; ++i) card_clear_cost_modifiers(pile[i], 2);
    }
    silent_player_turn_end(*this);
    necrobinder_player_turn_end(*this);
    regent_player_turn_end(*this);
    defect_after_side_turn_end(*this);
    if (outcome != Outcome::UNDECIDED) return;
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
    // DisintegrationPower.AfterSideTurnEndLate(player side): unpowered,
    // blockable damage. Runs on every player side end, including extra turns.
    if (player_power(PowerId::DISINTEGRATION) > 0 && outcome == Outcome::UNDECIDED) {
        damage_player(player_power(PowerId::DISINTEGRATION), false, false);
        if (outcome != Outcome::UNDECIDED) return;
    }
    // Pael's Eye grants its extra turn without an enemy turn, then expires.
    if (paelsEyeState & PAELS_EYE_EXTRA_TURN) {
        paelsEyeState &= ~PAELS_EYE_EXTRA_TURN;
        paelsEyeState |= PAELS_EYE_USED;
        start_player_turn();
        return;
    }
    // SwitchFromPlayerToEnemySide: AmbergrisPower grants the player another
    // turn instead of starting the enemy side, then decrements.
    if (ambergrisExtraTurns > 0) {
        --ambergrisExtraTurns;
        start_player_turn();
        return;
    }
    monster_turn();
    if (outcome != Outcome::UNDECIDED) return;
    for (int i = 0; i < monsterCount; ++i) {
        if (monsters[i].tempStrengthLoss != 0) {
            monsters[i].strength += monsters[i].tempStrengthLoss;
            monsters[i].tempStrengthLoss = 0;
            // TemporaryStrengthPower removes its own instance when restoring.
            monsters[i].power[static_cast<int>(PowerId::ENFEEBLING_TOUCH)] = 0;
            monsters[i].power[static_cast<int>(PowerId::DARK_SHACKLES)] = 0;
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
    // KnowledgeDemon.CurseOfKnowledgeMove: offer Disintegration (damage from
    // the per-counter table) plus the set's other curse. The chosen card is a
    // transient offer; its OnChosen applies the matching debuff power.
    if (knowledgeCursePending && outcome == Outcome::UNDECIDED) {
        knowledgeCursePending = false;
        const int index = knowledgeCurseIndex >= 0 && knowledgeCurseIndex <= 2
                              ? knowledgeCurseIndex : 0;
        static const CardId kOther[3] = {CardId::MIND_ROT, CardId::SLOTH_STATUS,
                                         CardId::WASTE_AWAY};
        static const int kDisintegration[3] = {6, 7, 8};
        static const int kOtherPower[3] = {1, 3, 1};
        Card offers[2];
        offers[0] = make_card(CardId::DISINTEGRATION, false, require_card_uid());
        offers[0].bonusDamage = kDisintegration[index];
        offers[1] = make_card(kOther[index], false, require_card_uid());
        offers[1].bonusDamage = kOtherPower[index];
        Card source = make_card(CardId::INVALID, false, 0);
        start_offer(ChoiceOp::KNOWLEDGE_CURSE, offers, 2, source, false, false);
        pending.hasSource = false;
        knowledgeCurseResume = 1;
        return;
    }
    start_player_turn();
}

void BattleContext::monster_turn() {
    inMonsterTurn = true;
    vitalSparkTriggeredThisEnemyTurn = false;
    silent_enemy_turn_start(*this);
    check_outcome();
    if (outcome != Outcome::UNDECIDED) { inMonsterTurn = false; return; }
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
    if (outcome == Outcome::UNDECIDED) {
        // RitualPower.AfterTurnEnd(owner side): skips the turn it was applied.
        for (int i = 0; i < monsterCount; ++i) {
            Monster &m = monsters[i];
            if (m.ritualJustApplied) { m.ritualJustApplied = false; continue; }
            if (m.alive && power_ref(m, PowerId::RITUAL) > 0)
                add_monster_power(i, PowerId::STRENGTH, power_ref(m, PowerId::RITUAL));
        }
        // Doom resolves before the generic enemy-turn end hooks.
        necrobinder_enemy_turn_end(*this);
        regent_enemy_turn_end(*this);
        check_outcome();
        if (outcome == Outcome::UNDECIDED) silent_enemy_turn_end(*this);
    }
    if (outcome == Outcome::UNDECIDED) {
        // BattlewornDummyTimeLimitPower.AfterSideTurnEnd(Enemy): decrement,
        // then on the last stack set RanOutOfTime and escape the owner.
        for (int i = 0; i < monsterCount; ++i) {
            Monster &m = monsters[i];
            int &limit = m.power[static_cast<int>(PowerId::BATTLEWORN_DUMMY_TIME_LIMIT)];
            if (!m.alive || limit <= 0) continue;
            if (limit > 1) { --limit; continue; }
            limit = 0;
            // Escape removes the creature without a death event; hp stays > 0.
            m.alive = false;
            m.combatEndBlocker = false;
        }
        check_outcome();
    }
    // CoveredPower.AfterSideTurnEnd(Enemy) always expires at the end of the
    // enemy side turn; KnockdownPower expires when its owner's side ends (all
    // owners are monsters here). Multiplayer-only powers still follow their
    // state lifetime in single player.
    player.power[static_cast<int>(PowerId::COVERED)] = 0;
    for (int i = 0; i < monsterCount; ++i)
        monsters[i].power[static_cast<int>(PowerId::KNOCKDOWN)] = 0;
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
            case CardId::WITHER:
                // Wither.FakeUpgrade adds 3 damage per level without changing
                // the card's normal upgrade state.
                damage_player(card_var(c, VarId::DAMAGE) + 3 * c.fakeUpgradeLevel);
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
    // v0.111.0 fixture evidence: Well Laid Plans retains the whole hand at
    // end of turn (no selector call, Amount is not a per-turn cap). The old
    // cb602cef decompile's "select up to Amount" model does not match.
    const bool retainAll = player_power(PowerId::RETAIN_HAND) > 0 ||
                           player_power(PowerId::EQUILIBRIUM) > 0 ||
                           player_power(PowerId::WELL_LAID_PLANS) > 0 ||
                           relic_has(*this, RelicId::RUNIC_PYRAMID);
    // Preserve hand order for both the discard pile and retained cards.
    for (int i = 0; i < handCount; ++i) {
        const Card c = hand[i];
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
    handCount = keptN;
    for (int i = 0; i < keptN; ++i) hand[i] = kept[i];
    relics_after_flush(*this, hand, keptN);
}
}
