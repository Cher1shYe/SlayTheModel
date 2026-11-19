#include "sts2/effects.h"
#include <algorithm>

namespace sts2 {

bool status_effect(BattleContext &bc, Card &card, int target) {
    (void) target;
    switch (card.id) {
        case CardId::LUMINESCE:
            bc.player.energy += card_var(card, VarId::ENERGY);
            return true;
        case CardId::SLIMED:
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::FRANTIC_ESCAPE: {
            // Single-player encounters have one target per Sandpit instance.
            for (int i = 0; i < bc.monsterCount; ++i) {
                Monster &m = bc.monsters[i];
                int &sandpit = m.power[static_cast<int>(PowerId::SANDPIT)];
                if (m.alive && sandpit > 0) { ++sandpit; break; }
            }
            // EnergyCost.AddThisCombat(1), even without a Sandpit. The flag
            // only records "made free"; the stack keeps native order.
            card.freeCombat = false;
            card_modify_cost(card, 1, false, 0);
            return true;
        }
        case CardId::DEBRIS:
        case CardId::BECKON:
            return true;  // no immediate effect
        case CardId::WOUND:
        case CardId::DAZED:
        case CardId::BURN:
        case CardId::VOID:
        case CardId::INFECTION:
        case CardId::SOOT:
        case CardId::TOXIC:
            return true;  // unplayable / hook-driven
        default:
            return false;
    }
}

}  // namespace sts2
