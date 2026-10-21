"""Codec references must agree with the native card construction path.

Public-card validation compares a live card against a freshly built reference.
`make_hand_of_greed` and `make_frantic_escape` used to ignore the decompiled
static metadata, so the same token carried `can_be_generated_in_combat=True`
or `False` depending on whether it came from create_card, a deck or a monster
effect, and a legal hand card was rejected mid-run.  Guard the parity here
instead of rediscovering it in a 40-minute training run.
"""
from dataclasses import fields

import sts2_env.az.boss_cards as boss_cards
import sts2_env.az.content_expansion as content_expansion
import sts2_env.az.g1 as g1
from sts2_env.cards.factory import create_card
from sts2_env.core.enums import CardId

CODECS = {
    'g1': g1.CODEC,
    'generated': g1.GEN_CODEC,
    'upgrade': g1.UP_CODEC,
    'topdeck': g1.TOP_CODEC,
    'lifecycle': g1.LIFE_CODEC,
    'selection': g1.SEL_CODEC,
    'morph': g1.MORPH_CODEC,
    'summon': g1.SUMMON_CODEC,
    'boss': boss_cards.CODEC,
    'expansion': content_expansion.CODEC,
}

DYNAMIC = {'instance_id', 'cost', 'combat_vars', 'single_turn_retain', 'base_damage',
           'base_block', 'effect_vars', 'keywords', 'bound'}


def test_every_reference_matches_native_static_metadata():
    drift = []
    for label, codec in CODECS.items():
        for token, factory in codec.factories.items():
            name = token.removesuffix('+')
            assert name in CardId.__members__, f'{label}: unknown token {token}'
            reference = factory()
            live = create_card(CardId[name], upgraded=token.endswith('+'))
            for field in fields(live):
                if field.name in DYNAMIC:
                    continue
                if getattr(reference, field.name, '<missing>') != getattr(live, field.name, '<missing>'):
                    drift.append(f'{label}:{token}.{field.name}')
    assert not drift, drift


def test_generation_metadata_tokens_are_admitted():
    # Regression: these tokens were rejected as "unaudited card mutation".
    codec = content_expansion.CODEC
    for token in ('HAND_OF_GREED', 'HAND_OF_GREED+', 'FRANTIC_ESCAPE'):
        assert codec.capture(codec._reference(token)).token == token


def test_live_hand_of_greed_is_observable():
    codec = content_expansion.CODEC
    card = create_card(CardId.HAND_OF_GREED, upgraded=True)
    assert card.can_be_generated_in_combat is False
    assert codec.capture(card).token == 'HAND_OF_GREED+'

def test_knights_recipe_deck_matches_native_metadata():
    # End-to-end guard for the deck path: create_deck used to skip the static
    # metadata step, so a HAND_OF_GREED in the starting deck disagreed with the
    # same token built by create_card.
    from sts2_env.az.all_decks import generate_recipe
    from sts2_env.az.decks import create_deck

    recipe = generate_recipe(4, 4, 7)  # frozen historical reproduction, independent of current sampling
    cards = create_deck(recipe.deck, recipe.family_id, recipe.content_manifest_version)
    copies = [c for c in cards if c.card_id is CardId.HAND_OF_GREED]
    assert copies, 'recipe no longer contains HAND_OF_GREED'
    assert all(c.can_be_generated_in_combat is False for c in copies)
    native = create_card(CardId.HAND_OF_GREED, upgraded=True)
    assert copies[0].can_be_generated_in_combat == native.can_be_generated_in_combat