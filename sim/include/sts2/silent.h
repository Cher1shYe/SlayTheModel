#pragma once
#include "sts2/battle.h"
#include "sts2/silent_state.h"

namespace sts2 {
bool silent_effect(BattleContext &bc, Card &card, int target);
// Resume a suspended OnPlay before enchantment OnPlay / AfterCardPlayed.
// Returns true when it has completed, false when another choice/child is open.
bool silent_resume_effect(BattleContext &bc);
void silent_before_card_played(BattleContext &bc, const Card &card);
void silent_after_card_played(BattleContext &bc, Card &card);
void silent_card_entered_combat(BattleContext &bc, Card &card, bool isClone);
void silent_card_drawn(BattleContext &bc, Card &card, bool fromHandDraw);
void silent_card_discarded(BattleContext &bc, const Card &card);
void silent_before_hand_draw(BattleContext &bc);
void silent_after_player_turn_start(BattleContext &bc);
void silent_reset_turn_counters(BattleContext &bc);
void silent_player_turn_start(BattleContext &bc);
void silent_player_turn_end(BattleContext &bc);
void silent_enemy_turn_start(BattleContext &bc);
void silent_enemy_turn_end(BattleContext &bc);
void silent_trigger_poison(BattleContext &bc, int target);
void silent_after_attack_damage(BattleContext &bc, int target, int unblocked);
double silent_damage_additive(const BattleContext &bc, const Card *card, bool powered);
double silent_damage_multiplier(const BattleContext &bc, int target, bool powered);
double silent_block_multiplier(const BattleContext &bc);
bool silent_card_playable(const BattleContext &bc, const Card &card);
TargetType silent_card_target(const BattleContext &bc, const Card &card);
int silent_extra_play_count(BattleContext &bc, const Card &card);
// Choice resolution runs after generic code removes the chosen hand entity.
bool silent_resolve_choice(BattleContext &bc, const Card &chosen, int handIndex);
// Run after PendingChoice is cleared, passing its old op. The resulting Sly
// play may itself open a new choice. Fixed discard selection is one batch.
bool silent_finish_choice(BattleContext &bc, ChoiceOp op);
void silent_create_shivs(BattleContext &bc, int count, bool upgraded = false,
                         bool inky = false);
void silent_store_nightmare(BattleContext &bc, const Card &selected);
}
