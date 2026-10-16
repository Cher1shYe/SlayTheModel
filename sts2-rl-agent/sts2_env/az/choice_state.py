"""G1 public selection payload and phase-aware action contract.

Only explicitly visible piles can supply options. Hidden draw order is never
accepted. This codec deliberately does not serialize or copy engine resolvers:
content-specific continuation reconstruction is required before AZ admission.
"""
from dataclasses import dataclass

from .card_state import PublicCardState

CHOICE_STATE_VERSION = "az-public-choice-v1"
VISIBLE_PILES = ("hand", "discard", "exhaust")


@dataclass(frozen=True)
class PublicChoiceOption:
    pile: str
    index: int
    card: PublicCardState


@dataclass(frozen=True)
class PublicChoiceState:
    mechanism: str
    options: tuple[PublicChoiceOption, ...]
    selected: tuple[int, ...]
    min_choices: int
    max_choices: int
    allow_skip: bool
    version: str = CHOICE_STATE_VERSION

    @property
    def is_multi(self):
        return self.min_choices != 1 or self.max_choices != 1

    def validate(self, codec, action_size=115):
        if self.version != CHOICE_STATE_VERSION or type(self.mechanism) is not str or not self.mechanism:
            raise ValueError("Invalid choice mechanism/version")
        if type(action_size) is not int or action_size < 2 or len(self.options) >= action_size:
            raise ValueError("Choice exceeds action schema; truncation forbidden")
        if (type(self.options) is not tuple or type(self.selected) is not tuple
                or type(self.min_choices) is not int or type(self.max_choices) is not int
                or not 0 <= self.min_choices <= self.max_choices
                or type(self.allow_skip) is not bool):
            raise ValueError("Invalid selection constraints")
        if self.min_choices > len(self.options) and not self.allow_skip:
            raise ValueError("Unreachable selection minimum")
        if (any(type(i) is not int or not 0 <= i < len(self.options) for i in self.selected)
                or tuple(sorted(set(self.selected))) != self.selected
                or len(self.selected) > self.max_choices or (not self.is_multi and self.selected)):
            raise ValueError("Invalid selected indices")
        refs = set()
        for option in self.options:
            if (type(option) is not PublicChoiceOption or option.pile not in VISIBLE_PILES
                    or type(option.index) is not int or option.index < 0):
                raise ValueError("Unsupported/nonpublic choice source")
            ref = (option.pile, option.index)
            if ref in refs:
                raise ValueError("Duplicate choice reference")
            refs.add(ref)
            codec.validate(option.card)
        return self

    def legal_mask(self, codec, action_size=115):
        self.validate(codec, action_size)
        mask = [False] * action_size
        mask[0] = (len(self.selected) >= self.min_choices or (self.allow_skip and not self.selected))
        for i in range(len(self.options)):
            mask[1 + i] = not self.is_multi or i in self.selected or len(self.selected) < self.max_choices
        return tuple(mask)

    def decode_action(self, action, codec, action_size=115):
        mask = self.legal_mask(codec, action_size)
        if type(action) is not int or not 0 <= action < action_size or not mask[action]:
            raise ValueError("Illegal selection action")
        # 0 confirms/skips here; it never ends a turn during a choice.
        return None if action == 0 else action - 1

    def bind_options(self, visible_piles, codec, action_size=115):
        """Bind to hypothetical cards, never the original world's callbacks."""
        self.validate(codec, action_size)
        result = []
        for option in self.options:
            pile = visible_piles.get(option.pile, ())
            if option.index >= len(pile) or codec.capture(pile[option.index]) != option.card:
                raise ValueError("Choice reference no longer matches public pile")
            result.append(pile[option.index])
        if len({id(card) for card in result}) != len(result):
            raise ValueError("Distinct public options alias the same hypothetical card")
        return result


def capture_choice(choice, visible_piles, codec, *, mechanism, action_size=115):
    options = []
    for option in choice.options:
        if option.source_pile not in VISIBLE_PILES:
            raise ValueError("Choice requires an explicit public reveal contract")
        pile = visible_piles.get(option.source_pile, ())
        # Identity is used only locally to find a position. No instance_id goes
        # into the payload; identical cards at different positions stay distinct.
        indices = [i for i, card in enumerate(pile) if card is option.card]
        if len(indices) != 1:
            raise ValueError("Ambiguous/missing public choice reference")
        options.append(PublicChoiceOption(option.source_pile, indices[0], codec.capture(option.card)))
    return PublicChoiceState(mechanism, tuple(options), tuple(sorted(choice.selected_indices)),
                             choice.min_choices, choice.max_choices, choice.allow_skip).validate(codec, action_size)
