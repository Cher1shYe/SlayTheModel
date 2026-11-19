#pragma once
#include "sts2/relics.h"

namespace sts2 {
// Native SavedProperty state lives in relicAux: BoneTea.CombatsLeft,
// FakeVenerableTeaSet.GainEnergyInNextCombat, and Byrdpip.Skin index.
void relic_persistent_on_obtain(RunContext &rc, RelicId id);
void relic_persistent_rest_entered(RunContext &rc);
bool relic_persistent_can_hatch(const RunContext &rc);
bool relic_persistent_hatch(RunContext &rc);
bool run_has_event_pet(const RunContext &rc);
void relic_persistent_before_combat(BattleContext &bc);
void relic_persistent_after_energy_reset(BattleContext &bc);
void relic_persistent_finish_turn_start(BattleContext &bc);
}
