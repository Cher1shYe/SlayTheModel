"""Public contracts for X payments, optional multi-select and timed hand retention."""
from dataclasses import dataclass

MAX_PUBLIC_ENERGY = 1203  # initial 3 + <=400 decisions adding/resetting at most 3 each


@dataclass(frozen=True)
class TurnPayment:
    token: str
    energy: int


SIMPLE_MAX_PUBLIC_ENERGY = 4003  # 3 initial + at most 10 gain per decision, <=400 decisions.

def validate_payments(history, max_energy=MAX_PUBLIC_ENERGY):
    if (type(history.payments) is not tuple or any(type(p) is not TurnPayment for p in history.payments)
            or tuple(p.token for p in history.payments) != history.played_this_turn):
        raise ValueError("Payment history does not match public plays")
    for p in history.payments:
        if type(p) is not TurnPayment or type(p.energy) is not int or not 0 <= p.energy <= (max_energy if p.token.removesuffix("+") in ("WHIRLWIND","VOLLEY","CASCADE") else 3):
            raise ValueError("Invalid actual energy payment")
    if type(history.retain_turns) is not int or not 0 <= history.retain_turns <= 400:
        raise ValueError("Invalid retain duration")


def validate_choice_shape(card, choice):
    if card.token.removesuffix('+')=='DISCOVERY':
        if choice.min_choices!=1 or choice.max_choices!=1 or not choice.allow_skip or choice.selected:raise ValueError('Unexpected Discovery selection constraints')
        return
    if card.token.removesuffix("+") == "PURITY":
        if (not choice.options or choice.min_choices != 0 or choice.max_choices != dict(card.effect_vars)["cards"]
                or not choice.allow_skip):
            raise ValueError("Unexpected Purity selection constraints")
    elif choice.min_choices != 1 or choice.max_choices != 1 or choice.allow_skip or choice.selected:
        raise ValueError("Unexpected single choice constraints")
