import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

from sts2_env.az.execution import restore_hand_draw_listener
from sts2_env.core.enums import PowerId
from sts2_env.powers.damage_modifiers import VigorPower


def test_removed_vigor_is_only_a_noop_listener():
    owner = SimpleNamespace(powers={})
    listener = restore_hand_draw_listener(owner, 'VIGOR')
    listener.before_hand_draw_late(owner, None)
    assert listener.amount == 0 and owner.powers == {}
    original = VigorPower(5)
    owner.powers[PowerId.VIGOR] = original
    assert restore_hand_draw_listener(owner, 'VIGOR') is original


def test_missing_stateful_listener_is_rejected(monkeypatch):
    from sts2_env.core import creature
    class Stateful(VigorPower):
        def before_hand_draw_late(self, owner, combat):
            raise AssertionError('must not call')
    monkeypatch.setattr(creature, 'get_power_class', lambda _: Stateful)
    with pytest.raises(ValueError, match='Missing stateful'):
        restore_hand_draw_listener(SimpleNamespace(powers={}), 'VIGOR')


def test_saved_tunneler_root_reconstructs_without_resurrecting_vigor():
    from sts2_env.az.entity_transition import public_from_dict
    from sts2_env.az.all_content import sample_particle
    path = Path(__file__).parent / 'fixtures' / 'vigor_pending_hook.json.gz'
    info = public_from_dict(json.loads(gzip.decompress(path.read_bytes())))
    for seed in (0, 1, 7):
        particle = sample_particle(info, np.random.default_rng(seed))
        assert particle.info.key() == info.key()
