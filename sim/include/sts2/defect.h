#pragma once

#include "sts2/defect_state.h"

namespace sts2 {
struct BattleContext;
struct Card;
struct ActivePlay;
enum class PowerId : std::uint16_t;

void defect_init(BattleContext &bc);
void defect_add_orb_slots(BattleContext &bc, int amount);
void defect_channel(BattleContext &bc, OrbId orb);
void defect_channel_random(BattleContext &bc);
void defect_evoke(BattleContext &bc, int index, bool dequeue = true);
void defect_orb_passive(BattleContext &bc, int index, int target = -1);
int defect_unique_orbs(const BattleContext &bc);

bool defect_effect(BattleContext &bc, Card &card, int target);
// Called after a choice/draw/child auto-play resumes the owning frame. Returns
// true when complete (including no pending Defect continuation), false while
// the card still awaits a player choice or child card.
bool defect_resume_effect(BattleContext &bc, ActivePlay &play);
bool defect_resolve_choice(BattleContext &bc, std::uint16_t uid);

// Reset history when the turn number advances. Native side-start effects run
// after SetupPlayerTurn (energy reset, hand draw, player-start hooks).
void defect_begin_turn(BattleContext &bc);
void defect_after_side_turn_start(BattleContext &bc);
void defect_after_energy_reset(BattleContext &bc);
void defect_before_hand_draw(BattleContext &bc);
void defect_player_turn_start(BattleContext &bc);
void defect_before_side_turn_end(BattleContext &bc);
void defect_after_side_turn_end(BattleContext &bc);
int defect_modify_hand_draw(const BattleContext &bc, int count);

// Result location and play count are determined once, before the first series
// begins. Before/after-card hooks run for each replay iteration.
bool defect_returns_to_hand(BattleContext &bc, const Card &card, int energySpent, bool dupe);
int defect_modify_play_count(BattleContext &bc, const Card &card, int count);
void defect_play_started(BattleContext &bc, const Card &card, int energySpent, bool firstInSeries);
void defect_before_card_played(BattleContext &bc, ActivePlay &play);
void defect_after_card_played(BattleContext &bc, ActivePlay &play);
void defect_after_card_drawn(BattleContext &bc, const Card &card);
void defect_after_card_generated(BattleContext &bc, const Card &card);
int defect_damage_additive(const BattleContext &bc, const Card &card, int energySpent);
// Call after add_player_power has actually changed the amount (Artifact may
// prevent a negative application). delta is the accepted signed change.
void defect_power_changed(BattleContext &bc, PowerId id, int delta);
Card defect_random_power(BattleContext &bc);

}  // namespace sts2
