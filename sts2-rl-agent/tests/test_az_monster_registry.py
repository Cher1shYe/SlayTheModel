"""Static monster/encounter inventory contracts (no mission, no model)."""
import pytest

from sts2_env.az.monster_registry import (CREATORS, ENCOUNTERS, audit,
                                         describe_monster)
from sts2_env.core.constants import MAX_ENEMIES


@pytest.fixture(scope='module')
def report():
    return audit()


def test_act_encounter_tables_are_enumerated():
    assert len(ENCOUNTERS) >= 80
    for act in ('act1', 'act2', 'act3', 'act4'):
        assert any(name for name in ENCOUNTERS)
    assert {'setup_shrinker_beetle_weak', 'setup_slimes_weak', 'setup_cultists_normal',
            'setup_queen_boss', 'setup_waterfall_giant_boss'} <= set(ENCOUNTERS)


def test_every_admitted_monster_has_a_reproducible_graph(report):
    assert report['total_monsters'] >= 100
    for name, info in report['monsters'].items():
        if not info.admitted:
            continue
        assert info.moves and info.initial_moves
        assert not info.ambiguous_pairs
        moves = set(info.moves)
        for move, targets in info.successors:
            assert move in moves
            assert set(targets) <= moves, f'{name}:{move} -> {targets}'
        signatures = dict(info.intent_signatures)
        assert len(signatures) == len(info.moves)
        for move, signature in info.intent_signatures:
            assert signature


def test_generic_admission_covers_all_but_boss_phase_contract(report):
    blocked = sorted(name for name, entry in report['encounters'].items() if not entry['admitted'])
    assert blocked == ['setup_test_subject_boss']
    assert len(report['admitted_encounters']) == report['total_encounters'] - 1


def test_test_subject_is_refused_by_the_generic_rule(report):
    info = report['monsters']['TEST_SUBJECT']
    assert not info.admitted
    assert any('RESPAWN' in a or 'RESPAWN' in b or 'RESPAWN' in c
               for a, b, c in info.ambiguous_pairs)


def test_rosters_stay_within_engine_capacity(report):
    for name, entry in report['encounters'].items():
        assert not entry['error'], (name, entry['error'])
        for roster in entry['rosters']:
            assert 1 <= len(roster) <= MAX_ENEMIES, (name, roster)
            for monster in roster:
                assert monster in report['monsters'], (name, monster)


def test_describe_monster_rejects_unknown_creator_keywords():
    with pytest.raises(TypeError):
        describe_monster('NIBBIT', CREATORS['create_nibbit'], samples=2, unknown_kw=1)


def test_branch_states_are_reported_not_guessed(report):
    branchy = [name for name, info in report['monsters'].items() if info.branch_states]
    assert branchy, 'the native tables do use random/conditional branches'
    for name in branchy:
        info = report['monsters'][name]
        if info.admitted:
            assert all(target in info.moves for _, targets in info.successors for target in targets)
