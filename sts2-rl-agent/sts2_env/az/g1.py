"""Audited public continuation for hand-exhaust choices, never real closures."""
from functools import partial

from .card_state import CardStateCodec, CardStatePolicy
from .choice_state import capture_choice
from .selection_batch import validate_choice_shape, MAX_PUBLIC_ENERGY
from .decks import G1_FACTORIES, GEN_FACTORIES, UP_FACTORIES, TOP_FACTORIES, LIFE_FACTORIES, SEL_FACTORIES, MORPH_FACTORIES
from .content import G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
from .content import BOSS_CONTENT

TOKENS = tuple(name + suffix for name in G1_FACTORIES for suffix in ("", "+"))
CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                       for name, factory in G1_FACTORIES.items() for suffix in ("", "+")})

GEN_TOKENS = tuple(name + suffix for name in GEN_FACTORIES for suffix in ("", "+"))
GEN_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                          for name,factory in GEN_FACTORIES.items() for suffix in ("", "+")})


UP_TOKENS = tuple(name + suffix for name in UP_FACTORIES for suffix in ("", "+"))
UP_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                         for name,factory in UP_FACTORIES.items() for suffix in ("", "+")})


TOP_TOKENS = tuple(name + suffix for name in TOP_FACTORIES for suffix in ("", "+"))
TOP_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                          for name,factory in TOP_FACTORIES.items() for suffix in ("", "+")})


LIFE_TOKENS = tuple(name + suffix for name in LIFE_FACTORIES for suffix in ("", "+"))
LIFE_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                           for name,factory in LIFE_FACTORIES.items() for suffix in ("", "+")},
                          CardStatePolicy(temporary_cost=True))


SEL_TOKENS = tuple(name + suffix for name in SEL_FACTORIES for suffix in ("", "+"))
SEL_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                           for name,factory in SEL_FACTORIES.items() for suffix in ("", "+")},
                          CardStatePolicy(temporary_cost=True, max_x_energy_spent=MAX_PUBLIC_ENERGY))


MORPH_TOKENS = tuple(name + suffix for name in MORPH_FACTORIES for suffix in ("", "+"))
MORPH_CODEC = CardStateCodec({name + suffix: partial(factory, upgraded=bool(suffix))
                            for name,factory in MORPH_FACTORIES.items() for suffix in ("", "+")},
                           CardStatePolicy(temporary_cost=True, max_x_energy_spent=MAX_PUBLIC_ENERGY))


# G2.2b: DAZED is a generated-only unupgraded status, so the vocabulary gains
# exactly one token and no fake "DAZED+".  Its reference metadata is
# "Cannot be upgraded", which is why it never appears in the upgrade ledger.
from sts2_env.cards.status import make_dazed  # noqa: E402

SUMMON_TOKENS = (*MORPH_TOKENS, "DAZED")
SUMMON_CODEC = CardStateCodec({**MORPH_CODEC.factories, "DAZED": make_dazed}, MORPH_CODEC.policy)


def allowed_choices(content):
    return (("TRUE_GRIT+", "BURNING_PACT", "BURNING_PACT+")
            + (("ARMAMENTS",) if content in (UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) else ())
            + (("PURITY", "PURITY+") if content in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) else ())
            + (("HEADBUTT", "HEADBUTT+") if content in (TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) else ()))


def codec_for(version):
    if version == BOSS_CONTENT:
        from .boss_cards import CODEC as BOSS_CODEC
        return BOSS_CODEC
    if version not in (G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT):
        raise ValueError("Unknown G1 codec content")
    return SUMMON_CODEC if version == SUMMON_CONTENT else MORPH_CODEC if version in (MORPH_CONTENT, MULTI_CONTENT) else SEL_CODEC if version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT) else LIFE_CODEC if version == LIFE_CONTENT else TOP_CODEC if version == TOP_CONTENT else UP_CODEC if version == UP_CONTENT else GEN_CODEC if version == GEN_CONTENT else CODEC


def observe_choice(world, content_version=G1_CONTENT):
    CODEC = codec_for(content_version)
    if world.pending_choice is None:
        return None, None
    if len(world.play_pile) != 1:
        raise ValueError("G1 requires one publicly pending card")
    card = CODEC.capture(world.play_pile[0])
    from .actions import action_size
    if card.token not in allowed_choices(content_version):
        raise ValueError("Unaudited choice continuation")
    is_discard = card.token.removesuffix("+") == "HEADBUTT"
    pile_name, pile = ("discard", world.discard_pile) if is_discard else ("hand", world.hand)
    choice = capture_choice(world.pending_choice, {pile_name: pile}, CODEC,
                            mechanism=card.token, action_size=action_size(content_version))
    indices = tuple(i for i,c in enumerate(pile) if card.token != "ARMAMENTS" or not c.upgraded)
    validate_choice_shape(card, choice)
    if tuple(o.index for o in choice.options) != indices:
        raise ValueError("Unexpected public choice shape")
    return card, choice


def restore_continuation(world, info):
    """Construct only hypothetical engine state from the public pending card."""
    CODEC = codec_for(info.content_version)
    if info.choice is None:
        return
    card = CODEC.restore(info.pending_card)
    card.owner = world.player
    paid = info.history.payments[-1].energy if info.content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) else card.cost
    card.energy_spent = paid
    world.play_pile.append(card)
    from .actions import action_size
    cards = info.choice.bind_options({"hand": world.hand, "discard": world.discard_pile}, CODEC, action_size(info.content_version))

    def resolve(selected):
        if selected is not None:
            if card.card_id.name == "HEADBUTT":
                world.insert_card_into_draw_pile(selected, random_position=False)
            elif card.card_id.name == "ARMAMENTS":
                world.upgrade_card(selected)
            else:
                world.exhaust_card(selected)
        if card.card_id.name == "BURNING_PACT":
            world.draw_cards(world.player, card.effect_vars["cards"])

    if card.card_id.name == "PURITY":
        world.request_multi_card_choice(prompt="Resolve public multi choice", cards=cards,
            source_pile="hand", resolver=lambda selected: [world.exhaust_card(c) for c in selected],
            min_count=info.choice.min_choices, max_count=info.choice.max_choices, allow_skip=info.choice.allow_skip)
        world.pending_choice.selected_indices = set(info.choice.selected)
    else:
        world.request_card_choice(prompt="Resolve public card choice", cards=cards,
                                  source_pile=info.choice.options[0].pile, resolver=resolve)
    # Admitted cards pause after their immediate effect and before the after-play
    # hooks. Energy/block before the choice were already applied and are not replayed.
    world._pending_play = dict(card=card, target=world.enemies[info.history.pending_target if info.content_version in (MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT) else 0] if card.card_id.name == "HEADBUTT" else None, owner=world.player,
        remaining_plays=0, play_count=1, energy_spent=paid, energy_value=paid,
        force_exhaust=False, is_auto_play=False, awaiting_after_hook=True)
