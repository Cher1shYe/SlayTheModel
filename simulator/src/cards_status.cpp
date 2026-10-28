#include "sts2/effects.h"

namespace sts2 {

bool status_effect(BattleContext &bc, Card &card, int target) {
    (void) target;
    switch (card.id) {
        case CardId::SLIMED:
            bc.draw_cards(card_var(card, VarId::CARDS));
            return true;
        case CardId::FRANTIC_ESCAPE:
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
