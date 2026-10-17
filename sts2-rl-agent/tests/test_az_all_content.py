"""All-encounter content version: generic public roster observation contract.

The card contract is shared with V4; these tests cover the observation path and
the public move-history loop for encounters outside the ten audited V4 profiles.
"""
import pytest

from sts2_env.az.all_content import finish_history, observe_all, roster_rows, validate_all
from sts2_env.az.content import ALL_CONTENT, ALL_INFORMATION
from sts2_env.az.information import PublicHistory
from sts2_env.az.monster_registry import ENCOUNTERS
from sts2_env.az.rewards import V7
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng

SAMPLE = ['setup_nibbits_weak', 'setup_nibbits_normal', 'setup_slimes_weak',
          'setup_cultists_normal', 'setup_bowlbugs_normal', 'setup_inklets_normal',
          'setup_exoskeletons_normal', 'setup_axebots_normal', 'setup_chompers_normal',
          'setup_toadpoles_normal', 'setup_kaiser_crab_boss',
          'setup_doormaker_boss', 'setup_waterfall_giant_boss']


def build(encounter, seed=11):
    deck = create_ironclad_starter_deck()
    world = CombatState(80, 80, deck, seed, relics=[], potions=[], character_id='Ironclad')
    ENCOUNTERS[encounter](world, Rng(seed))
    world.start_combat()
    world.visible_card_events = []
    world.rng = Rng(seed + 1)
    known = tuple(c.card_id.name + ('+' if c.upgraded else '') for c in deck)
    return world, known


def test_zero_strength_is_hidden_but_negative_dexterity_is_public():
    import json

    from sts2_env.az.power_memory import capture as capture_powers
    from sts2_env.core.enums import PowerId
    world, known = build('setup_nibbits_normal')
    world.apply_power_to(world.player, PowerId.STRENGTH, 0, applier=world.player)
    world.apply_power_to(world.player, PowerId.DEXTERITY, -1, applier=world.player)
    order = json.loads(capture_powers(world))['order']
    assert 'STRENGTH' not in order
    assert 'DEXTERITY' in order
    info = observe_all(world, PublicHistory(), None, 80, V7, known_deck=known,
                       encounter='setup_nibbits_normal')
    assert (-1, 'DEXTERITY', -1) in info.basic_statuses
    validate_all(info)


@pytest.mark.parametrize('encounter', SAMPLE)
def test_initial_observation_is_public_and_valid(encounter):
    world, known = build(encounter)
    info = observe_all(world, PublicHistory(), None, 80, V7, known_deck=known, encounter=encounter)
    assert info.content_version == ALL_CONTENT and info.information_version == ALL_INFORMATION
    assert info.encounter == encounter
    validate_all(info)
    assert sum(info.legal_mask) >= 1
    ledger, rows, summary = roster_rows(info.enemies)
    assert summary[0] >= summary[1] > 0
    assert len(rows) == len(info.enemies)


@pytest.mark.parametrize('encounter', SAMPLE)
def test_one_public_round_matches_the_world(encounter):
    world, known = build(encounter)
    info = observe_all(world, PublicHistory(), None, 80, V7, known_deck=known, encounter=encounter)
    base = info.history.after_action(info, 0, combat_ended=False, after_hand=())
    before_moves = [slot.moves for slot in info.enemies]
    world.end_player_turn()
    history = finish_history(info, world, base, 0)
    assert all(len(a) == len(b) + 1 for a, b in zip(history.roster_moves, before_moves))
    info2 = observe_all(world, history, None, 80, V7, known_deck=known, encounter=encounter,
                        enemy_initial_hp=tuple(slot.initial_hp for slot in info.enemies))
    validate_all(info2)
    for slot, expected in zip(info2.enemies, history.roster_moves):
        assert slot.moves == expected


def test_parity_report_tracks_every_encounter():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / 'docs/all_encounter_parity.json').read_text(encoding='utf-8'))
    assert report['encounters'] == 81
    assert report['passed'] >= 60
    assert report['delegated'] == 1
    assert (report['passed'] + report['delegated'] + report['sampled']
            + report['failed'] == report['encounters'])
    assert all(entry['detail'] for entry in report['results'].values())


def test_unknown_encounter_is_rejected_before_observation():
    world, known = build('setup_nibbits_weak')
    with pytest.raises(ValueError):
        observe_all(world, PublicHistory(), None, 80, V7, known_deck=known, encounter='')

