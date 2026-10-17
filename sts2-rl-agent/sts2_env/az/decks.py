"""Frozen M6.2 recipes and explicitly audited Ironclad factories.

This content version is distinct from both historical starter versions. The
factory contract does not imply support by an information/encoder schema.
"""
from collections import Counter
from types import MappingProxyType

from sts2_env.cards import ironclad
from .content import DECK_CONTENT, EXPANDED_CONTENT, G1_CONTENT, GEN_CONTENT, UP_CONTENT, TOP_CONTENT, LIFE_CONTENT, SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT
from .content import BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT

MIN_DECK_SIZE = 6
MAX_DECK_SIZE = 20
MAX_COPIES = 5

# No discovery by getattr/card registry: adding content requires explicit review.
FACTORIES = MappingProxyType({
    "STRIKE_IRONCLAD": ironclad.make_strike_ironclad,
    "DEFEND_IRONCLAD": ironclad.make_defend_ironclad,
    "BASH": ironclad.make_bash,
    "POMMEL_STRIKE": ironclad.make_pommel_strike,
    "SHRUG_IT_OFF": ironclad.make_shrug_it_off,
    "BLOODLETTING": ironclad.make_bloodletting,
    "INFLAME": ironclad.make_inflame,
    "OFFERING": ironclad.make_offering,
})

FAMILIES = MappingProxyType({
    "ironclad-starter": (),
    "ironclad-cycle": ("POMMEL_STRIKE", "SHRUG_IT_OFF"),
    "ironclad-strength": ("INFLAME", "POMMEL_STRIKE"),
    "ironclad-burst": ("BLOODLETTING", "OFFERING", "POMMEL_STRIKE"),
})

FAMILY_CARDS = MappingProxyType({
    "ironclad-starter": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"),
    "ironclad-cycle": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "POMMEL_STRIKE", "SHRUG_IT_OFF"),
    "ironclad-strength": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "INFLAME", "POMMEL_STRIKE", "SHRUG_IT_OFF"),
    "ironclad-burst": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "BLOODLETTING", "OFFERING", "POMMEL_STRIKE", "SHRUG_IT_OFF"),
})


EXPANDED_FACTORIES = MappingProxyType({**FACTORIES,
    "BODY_SLAM": ironclad.make_body_slam, "IRON_WAVE": ironclad.make_iron_wave,
    "TWIN_STRIKE": ironclad.make_twin_strike, "ASHEN_STRIKE": ironclad.make_ashen_strike,
    "BLUDGEON": ironclad.make_bludgeon, "HEMOKINESIS": ironclad.make_hemokinesis,
    "IMPERVIOUS": ironclad.make_impervious, "THUNDERCLAP": ironclad.make_thunderclap,
})
EXPANDED_FAMILIES = MappingProxyType({**FAMILIES,
    "ironclad-block": ("BODY_SLAM", "IRON_WAVE", "IMPERVIOUS"),
    "ironclad-exhaust": ("ASHEN_STRIKE", "OFFERING", "IMPERVIOUS"),
})
EXPANDED_FAMILY_CARDS = MappingProxyType({**FAMILY_CARDS,
    "ironclad-cycle": (*FAMILY_CARDS["ironclad-cycle"], "IRON_WAVE", "THUNDERCLAP"),
    "ironclad-strength": (*FAMILY_CARDS["ironclad-strength"], "TWIN_STRIKE", "THUNDERCLAP", "BLUDGEON"),
    "ironclad-burst": (*FAMILY_CARDS["ironclad-burst"], "HEMOKINESIS", "BLUDGEON", "TWIN_STRIKE"),
    "ironclad-block": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "SHRUG_IT_OFF", "BODY_SLAM", "IRON_WAVE", "IMPERVIOUS"),
    "ironclad-exhaust": ("STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ASHEN_STRIKE", "OFFERING", "IMPERVIOUS", "HEMOKINESIS", "BLOODLETTING"),
})


G1_FACTORIES = MappingProxyType({**EXPANDED_FACTORIES,
    "TRUE_GRIT": ironclad.make_true_grit, "BURNING_PACT": ironclad.make_burning_pact})
G1_FAMILIES = MappingProxyType({**EXPANDED_FAMILIES,
    "ironclad-exhaust": ("ASHEN_STRIKE", "TRUE_GRIT", "BURNING_PACT")})
G1_FAMILY_CARDS = MappingProxyType({k: (*v, "TRUE_GRIT", "BURNING_PACT") if k != "ironclad-starter" else v
                                  for k, v in EXPANDED_FAMILY_CARDS.items()})

GEN_FACTORIES = MappingProxyType({**G1_FACTORIES, "ANGER": ironclad.make_anger})
GEN_FAMILIES = MappingProxyType({**G1_FAMILIES,
    "ironclad-exhaust": (*G1_FAMILIES["ironclad-exhaust"], "ANGER")})
GEN_FAMILY_CARDS = MappingProxyType({k: (*v, "ANGER") if k != "ironclad-starter" else v for k,v in G1_FAMILY_CARDS.items()})

UP_FACTORIES = MappingProxyType({**GEN_FACTORIES, "ARMAMENTS": ironclad.make_armaments})
UP_FAMILIES = MappingProxyType({**GEN_FAMILIES,
    "ironclad-block": (*GEN_FAMILIES["ironclad-block"], "ARMAMENTS"),
    "ironclad-exhaust": (*GEN_FAMILIES["ironclad-exhaust"], "ARMAMENTS")})
UP_FAMILY_CARDS = MappingProxyType({k: (*v, "ARMAMENTS") if k != "ironclad-starter" else v for k,v in GEN_FAMILY_CARDS.items()})


TOP_FACTORIES = MappingProxyType({**UP_FACTORIES, "HEADBUTT": ironclad.make_headbutt})
TOP_FAMILIES = MappingProxyType({**UP_FAMILIES,
    "ironclad-cycle": (*UP_FAMILIES["ironclad-cycle"], "HEADBUTT"),
    "ironclad-exhaust": (*UP_FAMILIES["ironclad-exhaust"], "HEADBUTT")})
TOP_FAMILY_CARDS = MappingProxyType({k: (*v, "HEADBUTT") if k != "ironclad-starter" else v for k,v in UP_FAMILY_CARDS.items()})


from sts2_env.cards import colorless
LIFE_FACTORIES = MappingProxyType({**TOP_FACTORIES, "STOMP": ironclad.make_stomp,
                                  "RESTLESSNESS": colorless.make_restlessness})
LIFE_FAMILIES = MappingProxyType({**TOP_FAMILIES,
    "ironclad-strength": (*TOP_FAMILIES["ironclad-strength"], "STOMP"),
    "ironclad-cycle": (*TOP_FAMILIES["ironclad-cycle"], "RESTLESSNESS")})
LIFE_FAMILY_CARDS = MappingProxyType({k: (*v, "STOMP", "RESTLESSNESS") if k != "ironclad-starter" else v
                                    for k,v in TOP_FAMILY_CARDS.items()})


SEL_FACTORIES = MappingProxyType({**LIFE_FACTORIES, "WHIRLWIND": ironclad.make_whirlwind,
    "PURITY": colorless.make_purity, "EQUILIBRIUM": colorless.make_equilibrium})
SEL_FAMILIES = MappingProxyType({**LIFE_FAMILIES,
    "ironclad-burst": (*LIFE_FAMILIES["ironclad-burst"], "WHIRLWIND"),
    "ironclad-block": (*LIFE_FAMILIES["ironclad-block"], "EQUILIBRIUM"),
    "ironclad-exhaust": (*LIFE_FAMILIES["ironclad-exhaust"], "PURITY")})
SEL_FAMILY_CARDS = MappingProxyType({k: (*v, "WHIRLWIND", "PURITY", "EQUILIBRIUM") if k != "ironclad-starter" else v
                                    for k,v in LIFE_FAMILY_CARDS.items()})


from sts2_env.cards import necrobinder, status
MORPH_FACTORIES = MappingProxyType({**SEL_FACTORIES,
    "PRIMAL_FORCE": ironclad.make_primal_force, "REAVE": necrobinder.make_reave,
    "GIANT_ROCK": status.make_giant_rock, "SOUL": status.make_soul})
MORPH_FAMILIES = MappingProxyType({**SEL_FAMILIES,
    "ironclad-cycle": (*SEL_FAMILIES["ironclad-cycle"], "REAVE"),
    "ironclad-strength": (*SEL_FAMILIES["ironclad-strength"], "PRIMAL_FORCE")})
MORPH_FAMILY_CARDS = MappingProxyType({k: (*v, "REAVE", "PRIMAL_FORCE") if k != "ironclad-starter" else v
                                      for k,v in SEL_FAMILY_CARDS.items()})


def validate_deck(deck, family, content_version=DECK_CONTENT):
    """Validate before allocating any engine card IDs; never normalize silently."""
    families = MORPH_FAMILIES if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else SEL_FAMILIES if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else LIFE_FAMILIES if content_version == LIFE_CONTENT else TOP_FAMILIES if content_version == TOP_CONTENT else UP_FAMILIES if content_version == UP_CONTENT else GEN_FAMILIES if content_version == GEN_CONTENT else G1_FAMILIES if content_version == G1_CONTENT else EXPANDED_FAMILIES if content_version == EXPANDED_CONTENT else FAMILIES
    family_cards = MORPH_FAMILY_CARDS if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else SEL_FAMILY_CARDS if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else LIFE_FAMILY_CARDS if content_version == LIFE_CONTENT else TOP_FAMILY_CARDS if content_version == TOP_CONTENT else UP_FAMILY_CARDS if content_version == UP_CONTENT else GEN_FAMILY_CARDS if content_version == GEN_CONTENT else G1_FAMILY_CARDS if content_version == G1_CONTENT else EXPANDED_FAMILY_CARDS if content_version == EXPANDED_CONTENT else FAMILY_CARDS
    factories = MORPH_FACTORIES if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else SEL_FACTORIES if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else LIFE_FACTORIES if content_version == LIFE_CONTENT else TOP_FACTORIES if content_version == TOP_CONTENT else UP_FACTORIES if content_version == UP_CONTENT else GEN_FACTORIES if content_version == GEN_CONTENT else G1_FACTORIES if content_version == G1_CONTENT else EXPANDED_FACTORIES if content_version == EXPANDED_CONTENT else FACTORIES
    if content_version in (EXPANSION_CONTENT, ALL_CONTENT):
        from .content_expansion import initial_factories
        factories = initial_factories()
        families = {'ironclad-colorless-audit': ()}
        family_cards = {'ironclad-colorless-audit': tuple(factories)}
    if family not in families:
        raise ValueError("Unsupported deck family")
    if type(deck) is not tuple or not deck:
        raise ValueError("Deck must be a nonempty tuple")
    counts, entries = Counter(), set()
    for entry in deck:
        if (type(entry.card_id) is not str or entry.card_id not in factories
                or entry.card_id not in family_cards[family]):
            raise ValueError("Unsupported card for deck family")
        if type(entry.upgraded) is not bool or type(entry.count) is not int or entry.count < 1:
            raise ValueError("Invalid deck field types/count")
        key = (entry.card_id, entry.upgraded)
        if key in entries:
            raise ValueError("Duplicate deck entry; combine counts explicitly")
        entries.add(key)
        counts[entry.card_id] += entry.count
    if not MIN_DECK_SIZE <= sum(counts.values()) <= MAX_DECK_SIZE:
        raise ValueError("Unsupported deck size")
    if max(counts.values()) > MAX_COPIES:
        raise ValueError("Card copy limit exceeded across upgrade variants")
    if any(counts[name] == 0 for name in families[family]):
        raise ValueError("Missing defining card for deck family")
    return deck


def create_deck(deck, family, content_version=DECK_CONTENT):
    validate_deck(deck, family, content_version)
    factories = MORPH_FACTORIES if content_version in (MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else SEL_FACTORIES if content_version in (SEL_CONTENT, SET_CONTENT, MORPH_CONTENT, MULTI_CONTENT, SUMMON_CONTENT, BOSS_CONTENT, EXPANSION_CONTENT, ALL_CONTENT) else LIFE_FACTORIES if content_version == LIFE_CONTENT else TOP_FACTORIES if content_version == TOP_CONTENT else UP_FACTORIES if content_version == UP_CONTENT else GEN_FACTORIES if content_version == GEN_CONTENT else G1_FACTORIES if content_version == G1_CONTENT else EXPANDED_FACTORIES if content_version == EXPANDED_CONTENT else FACTORIES
    if content_version in (EXPANSION_CONTENT, ALL_CONTENT):
        from .content_expansion import initial_factories
        factories = initial_factories()
    return [factories[entry.card_id](upgraded=entry.upgraded)
            for entry in deck for _ in range(entry.count)]


def card_token(card):
    return card.card_id.name + ("+" if card.upgraded else "")


def make_token(token):
    name = token.removesuffix("+")
    from .content_expansion import FACTORIES as EXTRA
    if name in EXTRA:
        return EXTRA[name](upgraded=token.endswith('+'))
    if name not in MORPH_FACTORIES:
        raise ValueError("Unsupported card token")
    return MORPH_FACTORIES[name](upgraded=token.endswith("+"))


STATUS_TOKENS = ('DAZED', 'BURN', 'WOUND', 'SLIMED', 'TOXIC', 'INFECTION', 'BECKON', 'FRANTIC_ESCAPE')


def make_any_token(token):
    """Token factory that also covers inherited combat-generated status cards."""
    if token in STATUS_TOKENS:
        from sts2_env.cards import status
        return getattr(status, 'make_' + token.lower())()
    return make_token(token)


def deck_tokens(deck):
    return tuple(sorted(entry.card_id + ("+" if entry.upgraded else "")
                        for entry in deck for _ in range(entry.count)))



