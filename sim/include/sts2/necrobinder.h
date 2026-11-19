#pragma once
#include "sts2/battle.h"
#include "sts2/necrobinder_state.h"

namespace sts2 {
bool necrobinder_effect(BattleContext &bc, Card &card, int target);
bool necrobinder_resume_effect(BattleContext &bc);
void necrobinder_before_combat(BattleContext &bc);
void necrobinder_player_turn_start(BattleContext &bc); // reset before energy
void necrobinder_after_energy_reset(BattleContext &bc); // Bound Phylactery late
void necrobinder_after_side_turn_start(BattleContext &bc); // before hand draw
void necrobinder_before_hand_draw(BattleContext &bc);
void necrobinder_after_player_turn_start(BattleContext &bc); // SummonNextTurn
void necrobinder_player_turn_end(BattleContext &bc); // after hand flush
void necrobinder_enemy_turn_end(BattleContext &bc); // Doom BEFORE enemy end hooks
void necrobinder_before_card_played(BattleContext &bc, const Card &card);
void necrobinder_after_card_played(BattleContext &bc, Card &card);
void necrobinder_card_entered_combat(BattleContext &bc, Card &card, bool isClone);
void necrobinder_card_drawn(BattleContext &bc, const Card &card, bool fromHandDraw);
void necrobinder_card_generated(BattleContext &bc, const Card &card);
void necrobinder_after_death(BattleContext &bc, bool removalPrevented);
// Call after an actual power delta, with -1 for the player, and whether player
// was the applier. Includes legacy weak/vulnerable/strength helper paths.
void necrobinder_after_power_changed(BattleContext &bc, int target, PowerId power,
                                    int delta, bool playerApplied);
void necrobinder_after_damage_given(BattleContext &bc, int target,
                                   const DamageDealt &result, bool powered);
// Post-block incoming powered attack redirection, BEFORE player-specific HP
// modifiers (Tungsten/Buffer). Returns overkill that continues to the player.
int necrobinder_redirect_damage(BattleContext &bc, int unblocked, bool powered);
int necrobinder_resolved_cost(const BattleContext &bc, const Card &card, int cost);
double necrobinder_damage_multiplier(const BattleContext &bc, const Card *card,
                                    int target, bool powered);
double necrobinder_monster_damage_multiplier(const BattleContext &bc, int target);
int necrobinder_extra_energy(const BattleContext &bc);
int necrobinder_extra_draw(const BattleContext &bc);
bool necrobinder_card_playable(const BattleContext &bc, const Card &card);
// Resolve in place: do not remove a selected hand/draw card for these four ops.
bool necrobinder_resolve_choice(BattleContext &bc, const Card &chosen);
bool necrobinder_is_osty_attack(CardId id);
void necrobinder_summon(BattleContext &bc, int amount);
void necrobinder_kill_osty(BattleContext &bc);
int necrobinder_damage_osty(BattleContext &bc, int amount, bool unblockable = false);
void necrobinder_attack_osty(BattleContext &bc, Card &card, int target,
                           double base, int hits = 1, bool all = false,
                           bool random = false);
void necrobinder_create_souls(BattleContext &bc, int count,
                             ChoicePile destination = ChoicePile::DRAW,
                             bool upgraded = false);
void necrobinder_doom_kill(BattleContext &bc, bool playerSide = false);
}
