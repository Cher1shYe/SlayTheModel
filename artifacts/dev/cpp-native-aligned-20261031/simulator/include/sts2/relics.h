#pragma once

#include "sts2/run.h"

namespace sts2 {

const RelicDef &relic_def(RelicId id);
const char *relic_name(RelicId id);
bool relic_implemented(RelicId id);

bool relic_has(const BattleContext &bc, RelicId id);
bool run_has_relic(const RunContext &rc, RelicId id);
// Owned slots remain visible after wax melts, but no longer contribute hooks.
bool run_relic_active_at(const RunContext &rc, int index);
bool run_owns_relic(const RunContext &rc, RelicId id);
int relic_aux(const BattleContext &bc, RelicId id);
// Counters backed by a C# [SavedProperty] survive combat boundaries.
bool relic_aux_persistent(RelicId id);
void relic_aux_set(BattleContext &bc, RelicId id, int value);

// Battle hooks, called from battle.cpp.
void relics_combat_start(BattleContext &bc);
int relics_energy_for_turn(BattleContext &bc, int base);
int relics_modify_draw(BattleContext &bc, int base);
void relics_card_about_to_play(BattleContext &bc, const Card &card);
void relics_turn_start(BattleContext &bc);
void relics_hand_drawn(BattleContext &bc);
int relics_modify_damage(BattleContext &bc, int dmg, int target, const Card *card);
// Hook.ModifyDamageAdditive / ModifyDamageMultiplicative are separate phases:
// additive bonuses apply before Weak/Vulnerable multipliers, multiplicative
// relics (Pen Nib) after them.
int relics_damage_additive(const BattleContext &bc, const Card &card);
int relics_damage_multiplier(const BattleContext &bc, const Card &card);
int relics_modify_hp_loss(BattleContext &bc, int amount);
void relics_damage_received(BattleContext &bc, int amount);
void relics_current_hp_changed(BattleContext &bc);
bool relics_try_revive(BattleContext &bc);
int relics_modify_block_gain(BattleContext &bc, int amount, bool fromCard);
int relics_strength_gain(BattleContext &bc, int amount);
void relics_card_played(BattleContext &bc, const Card &card);
void relics_monster_died(BattleContext &bc);
void relics_exhausted(BattleContext &bc, const Card &card, bool causedByEthereal);
void relics_shuffled(BattleContext &bc);
void relics_turn_end(BattleContext &bc);
void relics_after_turn(BattleContext &bc);
void relics_ethereal_turn_end(BattleContext &bc);
void relics_potion_obtained(BattleContext &bc);
void relics_potion_used(BattleContext &bc);
int relics_block_retain(const BattleContext &bc);
bool relics_keep_energy(const BattleContext &bc);

// Run-layer hooks.
void relics_on_obtain(RunContext &rc, RelicId id);
void relics_combat_end(RunContext &rc, bool victory, bool boss);
void relics_resume_lifecycle(RunContext &rc);
void relics_after_combat_end_lifecycle(RunContext &rc);
void run_gain_gold(RunContext &rc, int amount);
// GainGold for a decimal amount whose truncations without/with Bowler Hat's
// x1.25 are precomputed (positive: the decimal amount is > 0).
void run_gain_gold_precomputed(RunContext &rc, int plain, int withBowler, bool positive);
void run_take_noncombat_damage(RunContext &rc, int amount);
int run_energy_bonus(const RunContext &rc);
int run_turn1_energy(const RunContext &rc);
bool run_relic_allowed(const RunContext &rc, RelicId id);
// RelicModel.IsAllowedInShops (false for Amethyst Aubergine, Bowler Hat,
// Lucky Fysh, Old Coin, The Courier).
bool relic_allowed_in_shops(RelicId id);
// RelicModel.IsTradable for the relic in inventory slot `slot` (Relic Trader,
// Ranwid): not used up, no upon-pickup effect, not melted, no pets, and not a
// Starter/Event/Ancient relic.
bool run_relic_tradable(const RunContext &rc, int slot);
// RelicCmd.Remove: no relic in v0.111.0 overrides AfterRemoved; the slot and
// its per-slot state (counter, wax, melted) are removed and later slots shift.
void run_remove_relic_at(RunContext &rc, int slot);
RelicId run_random_relic(Rng &rng, RunContext &rc);

}  // namespace sts2
