"""Validated mappings from live event options to simulator ArmG features.

Only initial pages with a verified game/simulator correspondence are accepted.
Unknown events, dynamic pages, and mixed option kinds must fall back explicitly.
"""
from dataclasses import dataclass


# Values are simulator option indices, not the order of the rendered buttons.
# Checked against the game's EventOption constructors and simulator events.cpp.
INITIAL_OPTIONS = {
    'AROMA_OF_CHAOS': ('LET_GO', 'MAINTAIN_CONTROL'),
    'DENSE_VEGETATION': ('TRUDGE_ON', 'REST'),
    'SUNKEN_STATUE': ('GRAB_SWORD', 'DIVE_INTO_WATER'),
    'WELLSPRING': ('BOTTLE', 'BATHE'),
    'TABLET_OF_TRUTH': ('DECIPHER_1', 'SMASH'),
    'UNREST_SITE': ('REST', 'KILL'),
    'SAPPHIRE_SEED': ('EAT', 'PLANT'),
    'THIS_OR_THAT': ('PLAIN', 'ORNATE'),
    'ROOM_FULL_OF_CHEESE': ('GORGE', 'SEARCH'),
    'POTION_COURIER': ('GRAB_POTIONS', 'RANSACK'),
    'BRAIN_LEECH': ('SHARE_KNOWLEDGE', 'RIP'),
    'REFLECTIONS': ('TOUCH_A_MIRROR', 'SHATTER'),
    'SPIRIT_GRAFTER': ('LET_IT_IN', 'REJECTION'),
    'LOST_WISP': ('CLAIM', 'SEARCH'),
}

_NEOW_POSITIVE = 'ARCANE_SCROLL BOOMING_CONCH POMANDER GOLDEN_PEARL LEAD_PAPERWEIGHT NEW_LEAF NEOWS_TORMENT PRECISE_SCISSORS LOST_COFFER NUTRITIOUS_OYSTER STONE_HUMIDIFIER LAVA_ROCK SMALL_CAPSULE'.split()
_DARV_BOSS = 'ASTROLABE BLACK_STAR CALLING_BELL EMPTY_CAGE PANDORAS_BOX RUNIC_PYRAMID SNECKO_EYE ECTOPLASM SOZU PHILOSOPHERS_STONE VELVET_CHOKER'.split()
_NONU = 'BLESSED_ANTLER BRILLIANT_SCARF DELICATE_FROND DIAMOND_DIADEM FUR_COAT GLITTER JEWELRY_BOX LOOMING_FRUIT SIGNET_RING BEAUTIFUL_BRACELET'.split()
_TANX = 'CLAWS CROSSBOW IRON_CLUB MEAT_CLEAVER SAI SPIKED_GAUNTLETS TANXS_WHISTLE THROWING_AXE WAR_HAMMER TRI_BOOMERANG'.split()

# Candidate pools are constrained per slot where the simulator does so.
ANCIENT_POOLS = {
    'NEOW': (_NEOW_POSITIVE, _NEOW_POSITIVE, 'CURSED_PEARL LARGE_CAPSULE LEAFY_POULTICE PRECARIOUS_SHEARS SCROLL_BOXES SILVER_CRUCIBLE'.split()),
    'OROBAS': ('ELECTRIC_SHRYMP GLASS_EYE SAND_CASTLE PRISMATIC_GEM SEA_GLASS'.split(), 'ALCHEMICAL_COFFER DRIFTWOOD RADIANT_PEARL'.split(), 'TOUCH_OF_OROBAS ARCHAIC_TOOTH'.split()),
    'PAEL': ('PAELS_FLESH PAELS_HORN PAELS_TEARS'.split(), 'PAELS_WING PAELS_CLAW PAELS_TOOTH PAELS_GROWTH'.split(), 'PAELS_EYE PAELS_BLOOD PAELS_LEGION'.split()),
    'TEZCATARA': ('NUTRITIOUS_SOUP VERY_HOT_COCOA YUMMY_COOKIE'.split(), 'BIIIG_HUG STORYBOOK SEAL_OF_GOLD TOASTY_MITTENS'.split(), 'GOLDEN_COMPASS PUMPKIN_CANDLE TOY_BOX'.split()),
    'NONUPEIPE': (_NONU, _NONU, _NONU),
    'TANX': (_TANX, _TANX, _TANX),
    'VAKUU': ('BLOOD_SOAKED_ROSE WHISPERING_EARRING FIDDLE'.split(), 'PRESERVED_FOG SERE_TALON DISTINGUISHED_CAPE'.split(), 'CHOICES_PARADOX MUSIC_BOX LORDS_PARASOL JEWELED_MASK'.split()),
    'DARV': (_DARV_BOSS, _DARV_BOSS, _DARV_BOSS + ['DUSTY_TOME']),
}


class UnsupportedEvent(ValueError):
    """The live event cannot be mapped reliably to the simulator."""


@dataclass(frozen=True)
class LiveEventEncoding:
    event_id: int
    option_indices: tuple[int, ...]
    choice_count: int
    page: int = 0
    relic_indices: tuple[int, ...] = ()

    def observation_block(self, relic_count: int) -> list[float]:
        """Event segment of the simulator public observation for an initial page."""
        event = [0.0] * 64
        event[self.event_id] = 1.0
        for index in range(4):
            relic = self.relic_indices[index] if index < len(self.relic_indices) else 0
            if not 0 <= relic < relic_count:
                raise UnsupportedEvent('relic index outside simulator')
            # Initial pages have zero eventData. Ancient relic offers are visible.
            event += [float(index < self.choice_count), 0.0, float(relic > 0), relic / 300.0,
                      0.0, float(index == self.page)] + [0.0] * relic_count
            # Simulator's invalid/default relic is enum value 0, and its
            # public observation still one-hots that default.
            if relic_count:
                event[-relic_count + relic] = 1.0
        return event + [0.0] * 4


def encode_live_event(observation: dict, actions: list[dict], sim) -> LiveEventEncoding:
    model = observation.get('room_model_id')
    if observation.get('surface') != 'event' or not isinstance(model, str) or not model.startswith('EVENT.'):
        raise UnsupportedEvent('missing live event identity')
    name = model.removeprefix('EVENT.')
    options = INITIAL_OPTIONS.get(name)
    pools = ANCIENT_POOLS.get(name)
    if options is None and pools is None:
        raise UnsupportedEvent(f'event has no verified simulator mapping: {name}')
    events = {sim.event_info(i)[0]: i for i in range(sim.event_count())}
    event_id = events.get(name)
    if event_id is None or not 0 <= event_id < 64:
        raise UnsupportedEvent(f'event not present in simulator: {name}')
    if pools is not None:
        if len(actions) != 3:
            raise UnsupportedEvent('ancient requires three visible options')
        relic_ids = []
        names = []
        for action, pool in zip(actions, pools):
            key = action.get('target_id')
            prefix = f'{name}.pages.INITIAL.options.'
            if action.get('kind') != 'choose_event_option' or not isinstance(key, str) or not key.startswith(prefix):
                raise UnsupportedEvent('ancient page or option is not verified')
            relic_name = key[len(prefix):]
            relic = sim.RelicId.__members__.get(relic_name)
            if relic_name not in pool or relic is None or int(relic) <= 0:
                raise UnsupportedEvent(f'unknown ancient relic: {relic_name}')
            names.append(relic_name)
            relic_ids.append(int(relic))
        if len(set(names)) != 3:
            raise UnsupportedEvent('duplicate ancient relic options')
        return LiveEventEncoding(event_id, (0, 1, 2), 3, relic_indices=tuple(relic_ids))
    indices = []
    for action in actions:
        if action.get('kind') != 'choose_event_option':
            raise UnsupportedEvent('event includes non-option action')
        key = action.get('target_id')
        prefix = f'{name}.pages.INITIAL.options.'
        if not isinstance(key, str) or not key.startswith(prefix):
            raise UnsupportedEvent('event page or option is not verified')
        try:
            indices.append(options.index(key[len(prefix):]))
        except ValueError as exc:
            raise UnsupportedEvent(f'unknown event option: {key}') from exc
    if not indices or len(set(indices)) != len(indices):
        raise UnsupportedEvent('event has no options or duplicate options')
    return LiveEventEncoding(event_id, tuple(indices), len(options))
