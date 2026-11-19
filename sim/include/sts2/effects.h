#pragma once

#include "sts2/battle.h"

namespace sts2 {

// Return true when the card was handled by this pool.
bool ironclad_effect(BattleContext &bc, Card &card, int target);
bool colorless_effect(BattleContext &bc, Card &card, int target);
bool status_effect(BattleContext &bc, Card &card, int target);

}  // namespace sts2
