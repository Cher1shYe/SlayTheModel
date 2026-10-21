import pytest

from sts2_env.az.execution import validate_play_finish


def test_nested_upgrade_of_resolving_card():
    events = [('start', 'HAVOC', 3, 1, -1, False),
              ('start', 'HOWL_FROM_BEYOND', 3, 0, -1, True),
              ('upgrade', 'HAVOC', 'HAVOC+', 3),
              ('finish', 'HOWL_FROM_BEYOND', 3, True),
              ('finish', 'HAVOC+', 3, True)]
    validate_play_finish(events, 1, 3)
    validate_play_finish(events, 0, 4)


@pytest.mark.parametrize('middle,token,turn', [
    ([], 'HAVOC+', 3),
    ([('upgrade', 'ANGER', 'ANGER+', 3)], 'HAVOC+', 3),
    ([('upgrade', 'HAVOC', 'HAVOC+', 2)], 'HAVOC+', 3),
    ([('upgrade', 'HAVOC', 'HAVOC+', 3)], 'ANGER+', 3),
    ([], 'HAVOC', 4),
])
def test_unwitnessed_or_mismatched_finish_rejected(middle, token, turn):
    events = [('start', 'HAVOC', 3, 1, -1, False), *middle,
              ('finish', token, turn, False)]
    with pytest.raises(ValueError, match='Mismatched public play'):
        validate_play_finish(events, 0, len(events)-1)
