import gzip
import json
from pathlib import Path
import numpy as np
from sts2_env.az.entity_transition import public_from_dict
from sts2_env.az.all_content import sample_particle


def test_exhaust_event_survives_later_dampen_upgrade():
    path = Path(__file__).parent/'fixtures/knights_exhaust_upgrade.json.gz'
    info = public_from_dict(json.loads(gzip.decompress(path.read_bytes())))
    assert info.history.exhausted_this_turn == ('CINDER',)
    assert 'CINDER+' in info.exhaust and 'CINDER' not in info.exhaust
    for seed in (0, 1, 32):
        particle = sample_particle(info, np.random.default_rng(seed))
        world = particle.world
        assert particle.info.key() == info.key()
        assert world.was_card_exhausted_this_turn(world.player)
        assert not world.was_card_exhausted_this_turn(world.enemies[0])
        assert len(world._exhaust_events_this_turn) == 1
        assert world._exhaust_events_this_turn[0].owner is world.player
        assert not world._exhaust_events_this_turn[0].upgraded
        assert [c for c in world.exhaust_pile if c.card_id.name == 'CINDER'][0].upgraded
