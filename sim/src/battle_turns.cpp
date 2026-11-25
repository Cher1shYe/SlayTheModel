#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
#include "sts2/relic_persistent.h"
#include "sts2/silent.h"
#include "sts2/defect.h"
#include "sts2/necrobinder.h"
#include "sts2/regent.h"
#include <algorithm>
namespace sts2 {

// Cards that auto-play themselves from the exhaust pile (Howl from Beyond, Bombardment).
static void auto_play_exhausted(BattleContext &b, CardId id) {
    std::uint16_t uids[MAX_PILE];
    int n = 0;
    for (int i = 0; i < b.exhaustCount; ++i)
        if (b.exhaust[i].id == id) uids[n++] = b.exhaust[i].uid;
    for (int i = 0; i < n && b.outcome == Outcome::UNDECIDED; ++i) {
        for (int j = 0; j < b.exhaustCount; ++j) {
            if (b.exhaust[j].uid != uids[i]) continue;
            const Card c = b.exhaust[j];
            for (int k = j; k + 1 < b.exhaustCount; ++k) b.exhaust[k] = b.exhaust[k + 1];
            --b.exhaustCount;
            b.auto_play_random(c, false);
            break;
        }
    }
}
int &power_ref(Player &,PowerId);
static void remove_at(Card *cards,int &count,int index){for(int i=index;i+1<count;++i)cards[i]=cards[i+1];--count;}

void BattleContext::start_player_turn(bool extraTurn) {
    ++turn;
    if (!extraTurn) ++combatRound;
    boundAfflictedThisTurn = 0;   // CardAfflictedEntry.HappenedThisTurn
    turnFlow.stage = TURN_FLOW_IDLE;
    turnFlow.relicCursor = 0;
    turnFlow.extraTurn = extraTurn;
    // Creature.BeforeTurnStart: PowerModel.AmountOnTurnStart snapshot.
    turnFlow.drawCardsNextTurnAtStart = player_power(PowerId::DRAW_CARDS_NEXT_TURN);
    // Per-turn character counters reset with the new PlayerCombatState turn.
    silent_reset_turn_counters(*this);
    defect_begin_turn(*this);
    necrobinder_player_turn_start(*this);
    regent_reset_turn(*this);
    // AggressionPower.BeforeSideTurnStart: move Amount random attacks from the
    // discard pile to hand and upgrade them, before the draw/shuffle.
    if (player_power(PowerId::AGGRESSION) > 0 && discardCount > 0) {
        std::uint16_t uids[MAX_PILE];
        int n = 0;
        for (int i = 0; i < discardCount; ++i)
            if (card_is_attack(discard[i])) uids[n++] = discard[i].uid;
        cardSelectionRng.shuffle(uids, n);
        const int take = std::min(n, player_power(PowerId::AGGRESSION));
        for (int k = 0; k < take; ++k) {
            for (int i = 0; i < discardCount; ++i) {
                if (discard[i].uid != uids[k]) continue;
                Card c = discard[i];
                remove_at(discard, discardCount, i);
                add_card_to_hand(c);
                // CardPileCmd.Add, then Upgrade: a card that overflowed the hand is upgraded too.
                if (Card *moved = find_in_hand(c.uid)) { if (card_upgradable(*moved)) upgrade_card(*moved); }
                else if (Card *over = find_in_discard(c.uid)) { if (card_upgradable(*over)) upgrade_card(*over); }
                break;
            }
        }
    }
    // Hook.BeforeSideTurnStart listener order: the player's powers (Aggression, above), the
    // player's relics, then enemy powers (Plating). v29.
    relics_before_side_turn_start(*this);
    if (outcome != Outcome::UNDECIDED) return;
    // PlatingPower.BeforeSideTurnStart: at the start of round 1 enemies gain
    // block equal to their plating.
    if (combatRound == 1) {
        for (int i = 0; i < monsterCount; ++i) {
            const int plating = monsters[i].power[static_cast<int>(PowerId::PLATING)];
            if (monsters[i].alive && plating > 0) monsters[i].block += plating;
        }
    }
    // Hook.BeforeSideTurnStart is done; CombatManager now calls PrepareForNextTurn
    // (RollMove) for every enemy, then the AfterSideTurnStart listeners run.
    if (!extraTurn) roll_pending_moves(*this);
    player.tookUnblockedDamageThisTurn = false;
    // Hook.ShouldClearBlock: Barricade and Blur keep the player's block.
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
    // Hook.AfterBlockCleared: Self-Forming Clay (a power natively), then relics in relic-bar order.
    relics_after_block_cleared(*this);
    if (outcome != Outcome::UNDECIDED) return;
    int baseEnergy = player.energyPerTurn;
    // WasteAwayPower.ModifyMaxEnergy: max energy - Amount.
    if (player_power(PowerId::WASTE_AWAY) > 0) baseEnergy = std::max(0, baseEnergy - player_power(PowerId::WASTE_AWAY));
    if (player_power(PowerId::PYRE) > 0) baseEnergy += player_power(PowerId::PYRE);
    baseEnergy += necrobinder_extra_energy(*this);  // Demesne / Friendship ModifyMaxEnergy
    player.energy = relics_energy_for_turn(*this, baseEnergy) + nextTurnEnergy;
    nextTurnEnergy = 0;
    relic_persistent_after_energy_reset(*this);
    // RadiancePower.AfterEnergyReset: +1 energy, then one stack expires.
    if (player_power(PowerId::RADIANCE) > 0) {
        player.energy += 1;
        add_player_power(PowerId::RADIANCE, -1);
    }
    // Hook.AfterEnergyReset listeners.
    // EnergyNextTurnPower: gain its Amount, then remove it.
    if (player_power(PowerId::ENERGY_NEXT_TURN) > 0) {
        const int next = player_power(PowerId::ENERGY_NEXT_TURN);
        player.energy += next;
        add_player_power(PowerId::ENERGY_NEXT_TURN, -next);
    }
    defect_after_energy_reset(*this);
    necrobinder_after_energy_reset(*this);
    regent_after_energy_reset(*this);
    if (outcome != Outcome::UNDECIDED) return;

    cardsPlayedThisTurn = 0;
    slothCardsPlayedThisTurn = 0;
    manualCardsPlayedThisTurn = 0;
    attacksPlayedThisTurn = 0;
    skillsPlayedThisTurn = 0;
    hpLostThisTurn = 0;
    exhaustedThisTurn = 0;
    cardsDrawnThisTurn = 0;
    gainedBlockFromCardThisTurn = false;
    blockGainEntriesThisTurn = 0;
    blockGainEntriesThisPlay = 0;
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

    // Cards whose cost was changed "this turn" expire now, wherever they are;
    // free-until-played costs persist until that copy is played.  Hidden Gem's
    // replay is BaseReplayCount (permanent for the combat), not a turn effect.
    for (int i = 0; i < handCount; ++i) card_restore_cost(hand[i]);
    for (int i = 0; i < drawCount; ++i) card_restore_cost(draw[i]);
    for (int i = 0; i < discardCount; ++i) card_restore_cost(discard[i]);
    // PlayerCombatState.EndOfTurnCleanup: every card drops EndOfTurn modifiers.
    for (Card *pile : {hand, draw, discard, exhaust, playPile})
        for (int i = 0, n = pile == hand ? handCount : pile == draw ? drawCount : pile == discard ? discardCount
                                     : pile == exhaust ? exhaustCount : playCount; i < n; ++i)
            card_clear_cost_modifiers(pile[i], 2);

    for (int i = 0; i < returnNextTurnCount; ++i) add_card_to_hand(returnNextTurn[i]);
    returnNextTurnCount = 0;

    // ---- BeforeHandDraw hooks (all run before the hand is drawn) ----------
    silent_before_hand_draw(*this);
    defect_before_hand_draw(*this);
    necrobinder_before_hand_draw(*this);
    regent_before_hand_draw(*this);
    if (outcome != Outcome::UNDECIDED) return;
    // Foregone Conclusion may have opened a draw-pile selection.
    turnFlow.stage = TURN_FLOW_RELIC_PRE_DRAW;
    resume_turn_flow();
}

// Remaining BeforeHandDraw listeners, then CardPileCmd.Draw for the hand.
void BattleContext::continue_pre_draw() {
    // ThrummingHatchet.BeforeHandDraw: the exact instance played last round
    // returns from whichever pile holds it (normally the discard pile).
    recall_played_last_turn(CardId::THRUMMING_HATCHET);
    recall_played_last_turn(CardId::BOLAS);
    // HelloWorldPower.BeforeHandDraw: add distinct unlocked Ironclad commons
    // before the normal hand draw.
    if (player_power(PowerId::HELLO_WORLD) > 0) {
        CardId options[static_cast<int>(CardId::COUNT)];
        int n = combat_card_options(characterPool, options);
        n = static_cast<int>(std::remove_if(options, options + n, [](CardId id) {
            return card_def(id).rarity != Rarity::COMMON;
        }) - options);
        Card generated[MAX_PILE];
        const int made = distinct_for_combat(options, n, std::min(player_power(PowerId::HELLO_WORLD), MAX_PILE), generated);
        for (int k = 0; k < made; ++k) {
            add_card_to_hand(generated[k]);
            notify_card_generated(generated[k]);
        }
    }

    int drawCountThisTurn = relics_modify_draw(*this, player.drawPerTurn) + nextTurnDraw;
    // MindRotPower.ModifyHandDraw: max(0, count - Amount).
    if (player_power(PowerId::MIND_ROT) > 0)
        drawCountThisTurn = std::max(0, drawCountThisTurn - player_power(PowerId::MIND_ROT));
    nextTurnDraw = 0;
    // ClarityPower.ModifyHandDraw: one extra card for each remaining turn.
    const bool clarity = player_power(PowerId::CLARITY) > 0;
    // Innate cards go on top of the draw pile on turn 1; the opening draw is
    // max(normal draw, innate count), capped at the 10-card hand (C# CombatManager).
    if (turn == 1) {
        // Native index 0 is the top (C++ keeps the top at the end). First every
        // ShouldStartAtBottomOfDrawPile card (Imbued) moves to the bottom in pile
        // order, then each other Innate card moves to the top in pile order, so
        // the Innate card lowest in the pile ends up on top.
        Card ordered[MAX_PILE];
        int n = 0;
        int innate = 0;
        const auto bottom = [](const Card &c) { return c.enchantment == EnchantmentId::IMBUED; };
        for (int i = drawCount - 1; i >= 0; --i)
            if (bottom(draw[i])) ordered[n++] = draw[i];
        std::reverse(ordered, ordered + n);
        for (int i = 0; i < drawCount; ++i) {
            if (!bottom(draw[i]) && !card_has(draw[i], CF_INNATE)) ordered[n++] = draw[i];
        }
        for (int i = drawCount - 1; i >= 0; --i) {
            if (!bottom(draw[i]) && card_has(draw[i], CF_INNATE)) { ordered[n++] = draw[i]; ++innate; }
        }
        for (int i = 0; i < n; ++i) draw[i] = ordered[i];
        drawCount = n;
        knownTopCount = innate;
        drawCountThisTurn = std::min(MAX_HAND, std::max(drawCountThisTurn, innate));
    }
    if (clarity) drawCountThisTurn += 1;
    // DrawCardsNextTurnPower.ModifyHandDraw only counts once present at turn
    // start; TyrannyPower.ModifyHandDraw always adds its Amount.
    if (turnFlow.drawCardsNextTurnAtStart != 0)
        drawCountThisTurn += player_power(PowerId::DRAW_CARDS_NEXT_TURN);
    drawCountThisTurn += regent_extra_hand_draw(*this);
    drawCountThisTurn = defect_modify_hand_draw(*this, drawCountThisTurn);  // Machine Learning
    drawCountThisTurn += necrobinder_extra_draw(*this);                     // Demesne
    drawCountThisTurn += std::max(0, player_power(PowerId::TOOLS_OF_THE_TRADE));
    // A Stratagem selection may interrupt the draw; it resumes when resolved.
    turnFlow.stage = TURN_FLOW_HAND_DRAW;
    draw_cards(drawCountThisTurn, true);
    if (clarity) add_player_power(PowerId::CLARITY, -1);
}

// Drives the resumable part of the player-turn setup.  Every stage that can
// open a selection records the next stage first; resolving the selection
// (maybe_finish_pending) calls back here.
void BattleContext::resume_turn_flow() {
    if (turnFlowRunning) return;
    struct Guard { bool &flag; Guard(bool &f):flag(f){flag=true;} ~Guard(){flag=false;} } guard(turnFlowRunning);
    while (turnFlow.stage != TURN_FLOW_IDLE) {
        if (outcome != Outcome::UNDECIDED) { turnFlow.stage = TURN_FLOW_IDLE; return; }
        if (pending.op != ChoiceOp::NONE || activePlay.active || suspendedPlayCount || autoPlayQueueCount)
            return;
        switch (turnFlow.stage) {
        case TURN_FLOW_PAELS_EYE_END:
            end_player_turn();
            break;
        case TURN_FLOW_RELIC_PRE_DRAW:
            relics_before_hand_draw(*this);
            if(pending.op!=ChoiceOp::NONE || activePlay.active || autoPlayQueueCount)return;
            turnFlow.relicCursor=0;turnFlow.stage=TURN_FLOW_PRE_DRAW;
            break;
        case TURN_FLOW_RELIC_APTS:
            relics_after_player_turn_start(*this);
            if(pending.op!=ChoiceOp::NONE || activePlay.active || autoPlayQueueCount)return;
            turnFlow.relicCursor=0;turnFlow.stage=TURN_FLOW_SILENT_APTS;
            break;
        case TURN_FLOW_PRE_DRAW:
            continue_pre_draw();
            break;
        case TURN_FLOW_HAND_DRAW:
            if (pendingDrawRemainder > 0) {
                const int count = pendingDrawRemainder;
                pendingDrawRemainder = 0;
                draw_cards(count, true);
                break;
            }
            turnFlow.stage = TURN_FLOW_POWER_APTS;
            after_hand_drawn();
            break;
        case TURN_FLOW_POWER_APTS:
            turnFlow.stage = TURN_FLOW_RELIC_APTS;
            powers_after_player_turn_start();
            break;
        // Hook.AfterPlayerTurnStart, one listener at a time.
        case TURN_FLOW_SILENT_APTS:
            turnFlow.stage = TURN_FLOW_NECRO_APTS;
            silent_after_player_turn_start(*this);
            break;
        case TURN_FLOW_NECRO_APTS:
            turnFlow.stage = TURN_FLOW_REGENT_APTS;
            necrobinder_after_player_turn_start(*this);
            break;
        case TURN_FLOW_REGENT_APTS:
            turnFlow.stage = TURN_FLOW_SIDE_START;
            regent_after_player_turn_start(*this);
            break;
        case TURN_FLOW_SIDE_START:
        default:
            turnFlow.stage = TURN_FLOW_AUTO_PRE_PLAY;
            // Hook.AfterPlayerTurnStartLate (Blood Vial) after every AfterPlayerTurnStart listener.
            relics_after_player_turn_start_late(*this);
            if (outcome != Outcome::UNDECIDED) return;
            // DemonFormPower / PrepTimePower.AfterSideTurnStart run after the hand is drawn.
            if (player_power(PowerId::DEMON_FORM) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::DEMON_FORM));
            if (player_power(PowerId::PREP_TIME) > 0) add_player_power(PowerId::VIGOR, player_power(PowerId::PREP_TIME));
            // Hook.AfterSideTurnStart(Player), then OrbQueue.AfterTurnStart.
            // Plating decays on its owner's turn start, including extra turns.
            if (turn != 1 && player_power(PowerId::PLATING) > 0)
                add_player_power(PowerId::PLATING, -1);
            silent_player_turn_start(*this);
            defect_after_side_turn_start(*this);
            necrobinder_after_side_turn_start(*this);
            regent_after_side_turn_start(*this);
            // DrawCardsNextTurnPower.AfterSideTurnStart removes a power that
            // was present at turn start.
            if (turnFlow.drawCardsNextTurnAtStart != 0 && player_power(PowerId::DRAW_CARDS_NEXT_TURN) > 0)
                add_player_power(PowerId::DRAW_CARDS_NEXT_TURN, -player_power(PowerId::DRAW_CARDS_NEXT_TURN));
            turnFlow.drawCardsNextTurnAtStart = 0;
            if (outcome != Outcome::UNDECIDED) return;
            // The player's relics (relic-bar order), then enemy powers.
            relics_after_side_turn_start(*this);
            if (outcome != Outcome::UNDECIDED) return;
            // RampartPower.AfterSideTurnStart(Player): every Rampart owner supplies
            // its Amount to all TurretOperator allies.
            for (int i = 0; i < monsterCount; ++i) {
                if (turnFlow.extraTurn || !monsters[i].alive ||
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
            defect_player_turn_start(*this);  // OrbQueue.AfterTurnStart, after the hook
            if (outcome != Outcome::UNDECIDED) return;
            break;
        case TURN_FLOW_AUTO_PRE_PLAY:
            turnFlow.stage = TURN_FLOW_FINISH_START;
            auto_pre_play_phase();
            break;
        case TURN_FLOW_FINISH_START:
            turnFlow.stage = TURN_FLOW_IDLE;
            // RunAutoPrePlayPhase -> Hook.AfterAutoPrePlayPhaseEnteredLate.
            whispering_earring_auto_play();
            return;
        }
    }
}

// Hook.AfterCardDrawn for the hand is done; hand-drawn relic and power effects.
void BattleContext::after_hand_drawn() {
    relics_hand_drawn(*this);
}

// Hook.AfterPlayerTurnStart for the player's own powers.
void BattleContext::powers_after_player_turn_start() {
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
    for (int i = 0; i < rollingCount && outcome == Outcome::UNDECIDED; ++i) {
        attack_all(rollingDamage[i], 1, false);
        rollingDamage[i] += 5;
        power_ref(player, PowerId::ROLLING_BOULDER) += 5;
    }
    if (outcome != Outcome::UNDECIDED) return;
    // EntropyPower: the player chooses Amount hand cards; each transforms on CombatCardSelection.
    if (player_power(PowerId::ENTROPY) > 0 && handCount > 0) {
        Card dummy{};
        dummy.uid = 0xFFFF;
        start_choice(ChoiceOp::TRANSFORM, ChoicePile::HAND, std::min(player_power(PowerId::ENTROPY), handCount),
                     false, dummy, false);
        if (pending.op != ChoiceOp::NONE) pending.hasSource = false;
    }
}

// CombatManager.RunAutoPrePlayPhase: Hook.AfterAutoPrePlayPhaseEntered.
void BattleContext::auto_pre_play_phase() {
    // RunAutoPrePlayPhase: CheckForEmptyHand comes first.
    relics_check_empty_hand(*this);
    if (pending.op != ChoiceOp::NONE) {
        turnFlow.stage = TURN_FLOW_AUTO_PRE_PLAY;
        return;
    }
    // Bombardment.AfterAutoPrePlayPhaseEnteredEarly.
    auto_play_exhausted(*this, CardId::BOMBARDMENT);
    if (outcome != Outcome::UNDECIDED) return;
    if (player_power(PowerId::MAYHEM) > 0) {
        auto_play_from_draw(player_power(PowerId::MAYHEM), false);
    }
    relics_auto_pre_play(*this);   // powers, then relics, then cards
    // Imbued.AfterAutoPrePlayPhaseEntered (cards follow powers and relics in
    // the listener list): on turn 1 every Imbued card auto-plays from its pile.
    if (turn <= 1) {
        std::uint16_t imbued[MAX_PILE];
        int n = 0;
        for (Card *pile : {hand, draw, discard, exhaust}) {
            const int count = pile == hand ? handCount : pile == draw ? drawCount : pile == discard ? discardCount : exhaustCount;
            if (pile == draw) {  // native pile order is top first
                for (int i = count - 1; i >= 0 && n < MAX_PILE; --i)
                    if (pile[i].enchantment == EnchantmentId::IMBUED) imbued[n++] = pile[i].uid;
            } else {
                for (int i = 0; i < count && n < MAX_PILE; ++i)
                    if (pile[i].enchantment == EnchantmentId::IMBUED) imbued[n++] = pile[i].uid;
            }
        }
        for (int k = 0; k < n && outcome == Outcome::UNDECIDED; ++k) {
            Card c{};
            bool found = false;
            for (Card *pile : {hand, draw, discard, exhaust}) {
                int &count = pile == hand ? handCount : pile == draw ? drawCount : pile == discard ? discardCount : exhaustCount;
                for (int i = 0; i < count && !found; ++i)
                    if (pile[i].uid == imbued[k]) {
                        c = pile[i];
                        if (pile == draw) remove_draw_at(i);
                        else { for (int j = i; j + 1 < count; ++j) pile[j] = pile[j + 1]; --count; }
                        found = true;
                    }
                if (found) break;
            }
            if (found) auto_play_random(c, false);
        }
    }
}

void BattleContext::end_player_turn() {
    if (outcome != Outcome::UNDECIDED) return;
    if (turn >= 200) {  // stalemate cutoff, not a game-rule defeat
        outcome = Outcome::TRUNCATED;
        return;
    }
    const bool eyeReady=relic_has(*this,RelicId::PAELS_EYE) && relic_aux(*this,RelicId::PAELS_EYE)==0 &&
        manualCardsPlayedThisTurn==0 && !(turn==1 && relic_has(*this,RelicId::WHISPERING_EARRING));
    if(eyeReady && turnFlow.stage!=TURN_FLOW_PAELS_EYE_END && !turnFlow.paelsEyeExtraTurn) {
        turnFlow.paelsEyeExtraTurn=true;
        turnFlow.paelsEyeExhaustCount=handCount;turnFlow.paelsEyeExhaustIndex=0;
        for(int i=0;i<handCount;++i)turnFlow.paelsEyeExhaustUids[i]=hand[i].uid;
        turnFlow.stage=TURN_FLOW_PAELS_EYE_END;
    }
    if(turnFlow.stage==TURN_FLOW_PAELS_EYE_END) {
        while(turnFlow.paelsEyeExhaustIndex<turnFlow.paelsEyeExhaustCount) {
            const int uid=turnFlow.paelsEyeExhaustUids[turnFlow.paelsEyeExhaustIndex++];
            // The native command snapshots the starting hand; draws caused by
            // exhaustion are not added to this list.
            for(int i=0;i<handCount;++i)if(hand[i].uid==uid) {
                Card card=hand[i];remove_at(hand,handCount,i);move_to_exhaust(card);break;
            }
            if(pending.op!=ChoiceOp::NONE || activePlay.active || autoPlayQueueCount)return;
            if(outcome!=Outcome::UNDECIDED)return;
        }
        turnFlow.stage=TURN_FLOW_IDLE;turnFlow.paelsEyeExhaustCount=turnFlow.paelsEyeExhaustIndex=0;
        std::fill(std::begin(turnFlow.paelsEyeExhaustUids),std::end(turnFlow.paelsEyeExhaustUids),0);
    }
    // Hook.AfterAutoPostPlayPhaseEntered precedes every end-of-turn effect.
    if (player_power(PowerId::STAMPEDE) > 0) {
        int attacks = player_power(PowerId::STAMPEDE);
        while (attacks-- > 0 && handCount > 0 && outcome == Outcome::UNDECIDED) {
            int candidates[MAX_HAND];
            int n = 0;
            for (int i = 0; i < handCount; ++i)
                if (card_is_attack(hand[i]) && !card_has(hand[i], CF_UNPLAYABLE)) candidates[n++] = i;
            if (n == 0) break;
            const int idx = candidates[shuffleRng.next_int_range(0, n)];  // StampedePower: Rng.Shuffle
            Card c = hand[idx];
            remove_at(hand, handCount, idx);
            // StampedePower -> CardCmd.AutoPlay: the whole play lifecycle
            // (counters, Rage/after-play hooks, Duplication) must run.
            auto_play_random(c, false);
        }
    }
    // Card listeners run Hand, Draw, Discard, Exhaust: I Am Invincible before Howl from Beyond.
    {
        int copies = 0;
        for (int i = 0; i < drawCount; ++i) copies += draw[i].id == CardId::I_AM_INVINCIBLE;
        for (int i = 0; i < copies && outcome == Outcome::UNDECIDED && pending.op == ChoiceOp::NONE &&
                        drawCount > 0 && draw[drawCount - 1].id == CardId::I_AM_INVINCIBLE; ++i)
            auto_play_from_draw(1, false);
    }
    auto_play_exhausted(*this, CardId::HOWL_FROM_BEYOND);
    if (outcome != Outcome::UNDECIDED) return;
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
    // Hook.BeforeSideTurnEndVeryEarly (Orichalcum) precedes every end-of-turn effect.
    const bool blockWasZeroAtTurnEnd = player.block == 0;
    // Hook.BeforeSideTurnEndEarly: Plating and Regen, before The Bomb and the relics.
    if (player_power(PowerId::PLATING) > 0)
        gain_block(player_power(PowerId::PLATING), false, false);
    if (player_power(PowerId::REGEN) > 0) {
        heal_hp(player_power(PowerId::REGEN));
        add_player_power(PowerId::REGEN, -1);
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
    relics_turn_end(*this, blockWasZeroAtTurnEnd);
    relics_after_turn(*this);
    if (outcome != Outcome::UNDECIDED) return;

    // Hook.BeforeSideTurnEnd (OrbQueue.BeforeTurnEnd precedes hand effects).
    defect_before_side_turn_end(*this);
    if (outcome != Outcome::UNDECIDED) return;
    // ChainsOfBindingPower.BeforeSideTurnEnd: reset the play flag, clear every Bound.
    boundCardPlayed = false;
    {
        Card *piles[] = {hand, draw, discard, exhaust, playPile, returnNextTurn};
        const int counts[] = {handCount, drawCount, discardCount, exhaustCount, playCount, returnNextTurnCount};
        for (int p = 0; p < 6; ++p) for (int i = 0; i < counts[p]; ++i) piles[p][i].bound = false;
    }
    discard_hand();
    if (outcome != Outcome::UNDECIDED) return;
    flush_ethereal_exhaust_hooks();
    // Hook.AfterSideTurnEnd(Player): powers first. Constrict comes after every end-of-turn
    // block gain, so that block absorbs it.
    if (player_power(PowerId::CONSTRICT) > 0) {
        damage_player(player_power(PowerId::CONSTRICT));
        if (outcome != Outcome::UNDECIDED) return;
    }
    relics_after_side_turn_end(*this);
    if (outcome != Outcome::UNDECIDED) return;
    silent_player_turn_end(*this);
    necrobinder_player_turn_end(*this);
    regent_player_turn_end(*this);
    defect_after_side_turn_end(*this);
    if (outcome != Outcome::UNDECIDED) return;
    // These owner-side duration hooks also run before an extra player turn.
    player.power[static_cast<int>(PowerId::NO_DRAW)] = 0;
    if (player_power(PowerId::SHRINK) > 0) add_player_power(PowerId::SHRINK, -1);
    if (player.tempStrength != 0) {
        player.strength -= player.tempStrength;
        player.tempStrength = 0;
    }
    if (player.tempDexterity != 0) {
        player.dexterity -= player.tempDexterity;
        player.tempDexterity = 0;
    }
    // Public source wrappers for the already-applied temporary stat totals.
    // They expire with those totals; do not apply the stat change a second time.
    for(const auto id : {PowerId::SETUP_STRIKE,PowerId::FEEDING_FRENZY,PowerId::FLEX_POTION,
                        PowerId::SPEED_POTION,PowerId::REPTILE_TRINKET})
        player.power[static_cast<int>(id)] = 0;
    if (player_power(PowerId::RITUAL) > 0) add_player_power(PowerId::STRENGTH, player_power(PowerId::RITUAL));
    if (player_power(PowerId::RAGE) > 0) add_player_power(PowerId::RAGE, -player_power(PowerId::RAGE));
    player.power[static_cast<int>(PowerId::REBOUND)] = 0;  // ReboundPower.AfterSideTurnEnd
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
        add_player_power(PowerId::STRENGTH, tenderCardsPlayedThisTurn);
        add_player_power(PowerId::DEXTERITY, tenderCardsPlayedThisTurn);
        tenderCardsPlayedThisTurn = 0;
    }
    player.power[static_cast<int>(PowerId::RINGING)] = 0;
    // TangledPower.AfterSideTurnEnd removes itself (and the Entangled afflictions).
    player.power[static_cast<int>(PowerId::TANGLED)] = 0;
    // SmoggyPower.AfterSideTurnEnd clears every Smog affliction.
    skillsLocked = false;
    // GrapplePower.AfterTurnEnd removes the debuff at the end of the turn
    // (TheGambit kills immediately in damage_player, never at turn end).
    for (int i = 0; i < monsterCount; ++i) {
        monsters[i].power[static_cast<int>(PowerId::GRAPPLE)] = 0;
        monsters[i].grappleCount = 0;
    }

    // DisintegrationPower.AfterSideTurnEndLate(player side): Amount unpowered damage.
    if (outcome == Outcome::UNDECIDED && player_power(PowerId::DISINTEGRATION) > 0) {
        damage_player(player_power(PowerId::DISINTEGRATION));
        check_outcome();
        if (outcome != Outcome::UNDECIDED) return;
    }
    for (int i = 0; i < panacheCount; ++i) panacheLeft[i] = 5;
    for (int i = 0; i < monsterCount; ++i) monsters[i].skittishTriggeredThisTurn = false;
    // CombatManager.SwitchFromPlayerToEnemySide: an extra player turn skips
    // the entire enemy side. AfterTakingExtraTurn consumes one Ambergris stack
    // before the next player's start hooks. Do not tick enemy-side durations.
    if (player_power(PowerId::AMBERGRIS) > 0 || turnFlow.paelsEyeExtraTurn) {
        if(player_power(PowerId::AMBERGRIS)>0)add_player_power(PowerId::AMBERGRIS, -1);
        if(relic_has(*this,RelicId::PAELS_EYE))relic_aux_set(*this,RelicId::PAELS_EYE,1);
        turnFlow.paelsEyeExtraTurn=false;
        start_player_turn(true);
        return;
    }
    if (!monster_turn()) return;                // suspended for a choice (Knowledge Demon)
    after_monster_turn();
}

void BattleContext::after_monster_turn() {
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
    // TaintedPower.AfterSideTurnEnd(Enemy): removed.
    player.power[static_cast<int>(PowerId::TAINTED)] = 0;
    if (player.vulnerable > 0 && !vulnerableSkipTick) --player.vulnerable;
    if (player.weak > 0 && !weakSkipTick) --player.weak;
    if (player.frail > 0 && !frailSkipTick) --player.frail;
    weakSkipTick = false;
    frailSkipTick = false;
    vulnerableSkipTick = false;
    add_player_power(PowerId::FLAME_BARRIER, 0);
    player.power[static_cast<int>(PowerId::FLAME_BARRIER)] = 0;
    // ColossusPower.AfterTurnEnd(side Enemy) ticks its duration once per enemy
    // turn; it does not disappear after a single turn.
    if (player_power(PowerId::COLOSSUS) > 0) add_player_power(PowerId::COLOSSUS, -1);
    player.power[static_cast<int>(PowerId::EQUILIBRIUM)] = 0;
    start_player_turn();
}

bool BattleContext::monster_turn() {
    // Every pending transition was rolled when the player's turn started; this only
    // matters for direct callers (tests, tools) that run enemy turns back to back.
    roll_pending_moves(*this);
    inMonsterTurn = true;
    vitalSparkTriggeredThisEnemyTurn = false;
    // SlowPower.AfterSideTurnStart: the card count resets when the monsters'
    // own side begins its turn.
    for (int i = 0; i < monsterCount; ++i) monsters[i].slowCardsThisTurn = 0;
    silent_enemy_turn_start(*this);
    check_outcome();
    if (outcome != Outcome::UNDECIDED) { inMonsterTurn = false; return true; }
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
            return true;
        }
    }
    for (int i = 0; i < monsterCount; ++i) monsters[i].spawnedThisEnemyTurn = false;
    // CombatManager: foreach enemy in Enemies.ToList() -- the native list order, fixed
    // when the enemy turn starts.
    suspendedOrderN = enemy_order(suspendedOrder);
    suspendedTurnK = 0;
    return monster_turn_continue();
}

bool BattleContext::monster_turn_continue() {
    for (int k = suspendedTurnK; k < suspendedOrderN; ++k) {
        const int i = suspendedOrder[k];
        if (!monsters[i].alive || monsters[i].spawnedThisEnemyTurn) continue;
        monster_act(*this, monsters[i]);
        check_outcome();
        if (outcome != Outcome::UNDECIDED) break;
        if (pending.op == ChoiceOp::KNOWLEDGE_CURSE) {   // wait for the player's choice
            suspendedTurnK = k + 1;
            return false;
        }
    }
    suspendedTurnK = -1;
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
        // Hook.AfterSideTurnEnd(Enemy): Doom resolves before other listeners.
        necrobinder_enemy_turn_end(*this);
        silent_enemy_turn_end(*this);
        regent_enemy_turn_end(*this);
        check_outcome();
    }
    inMonsterTurn = false;
    return true;
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
            case CardId::WITHER:  // DamageVar 3 (+3 per FakeUpgrade), unpowered, blockable
                damage_player(card_var(c, VarId::DAMAGE) + static_cast<int>(c.bonusDamage));
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
    // Hook.ShouldFlush == false keeps the whole hand.
    const bool retainAll = player_power(PowerId::RETAIN_HAND) > 0 ||
                           player_power(PowerId::EQUILIBRIUM) > 0 ||
                           player_power(PowerId::WELL_LAID_PLANS) > 0 ||
                           relic_has(*this, RelicId::RUNIC_PYRAMID);
    // CombatManager.FlushPlayerHand walks the hand front to back: retained
    // cards keep their order and the rest enter the discard pile in hand order.
    Card cards[MAX_HAND];
    const int count = handCount;
    std::copy(hand, hand + count, cards);
    handCount = 0;
    for (int i = 0; i < count; ++i) {
        const Card &c = cards[i];
        // Ethereal is resolved before retention (C# CombatManager end-of-turn).
        if (card_has(c, CF_ETHEREAL) || c.etherealThisCombat ||
            (c.hexed && player_power(PowerId::HEX) > 0)) {
            move_to_exhaust(c, true);
        } else if (card_has(c, CF_RETAIN) || retainAll) {
            if (keptN < MAX_HAND) kept[keptN++] = c;
        } else {
            move_to_discard(c);
        }
    }
    for (int i = 0; i < keptN; ++i) hand[handCount++] = kept[i];
}
}
