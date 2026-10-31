#pragma once

#include "sts2/common.h"

namespace sts2 {
struct BattleContext;
struct RunContext;

// Physical belt slots retain holes. potionCount is occupied slots, never the
// length of a packed prefix; empty slots contain PotionId::INVALID (zero).
int potion_occupied_count(const int *ids, int slots);
int potion_first_empty_slot(const int *ids, int slots);
bool potion_slots_valid(const int *ids, int slots, int count);
bool potion_remove_at(int *ids, int slots, int &count, int index);
bool run_try_procure_potion(RunContext &rc, PotionId id, int slot = -1);
bool battle_try_procure_potion(BattleContext &bc, PotionId id, int slot = -1);
void potion_alchemical_coffer_on_obtain(RunContext &rc);
void potion_delicate_frond_before_combat(BattleContext &bc);

}  // namespace sts2
