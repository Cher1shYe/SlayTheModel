#pragma once

#include "sts2/run.h"

namespace sts2 {

const RelicDef &relic_def(RelicId id);
const char *relic_name(RelicId id);
bool relic_implemented(RelicId id);

bool relic_has(const BattleContext &bc, RelicId id);
bool run_has_relic(const RunContext &rc, RelicId id);
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
bool relics_try_revive(BattleContext &bc);
int relics_modify_block_gain(BattleContext &bc, int amount, bool fromCard);
void relics_strength_gain(BattleContext &bc, int amount);
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
void run_gain_gold(RunContext &rc, int amount);
void run_take_noncombat_damage(RunContext &rc, int amount);
int run_energy_bonus(const RunContext &rc);
int run_turn1_energy(const RunContext &rc);
bool run_relic_allowed(const RunContext &rc, RelicId id);
RelicId run_random_relic(Rng &rng, RunContext &rc);

}  // namespace sts2
