"""Combat entity observation, NetSearch, root-visit export and the combat network."""
import random

import numpy as np
import pytest
import torch

from spire_rl.sim import sim
from spire_rl import combat_play as cp
from spire_rl.combat_net import CombatNet, CombatNetConfig, collate_obs, collate_packed, losses


def _first_combat(seed="COMBATNET1"):
    rng = random.Random(0)
    rc = sim.RunContext()
    rc.init_seed(seed, 0)
    while rc.screen != sim.RunScreen.COMBAT:
        acts = rc.legal_actions()
        rc.step(*acts[rng.randrange(len(acts))])
    return rc


def _later_state(rc, steps=6):
    """Advance a few real decisions into the fight (cards in discard, known draw pile sizes)."""
    rc = rc.clone()
    for k in range(steps):
        legal = rc.battle.legal_actions()
        if rc.screen != sim.RunScreen.COMBAT or not legal:
            break
        rc.step_combat(*legal[k % len(legal)])
    return rc


def test_entity_observation_shapes_and_candidates():
    rc = _later_state(_first_combat())
    bc = rc.battle
    o = bc.entity_observation()
    legal = bc.legal_actions()
    n = len(o["kind"])
    assert o["num"].shape == (n, sim.COMBAT_ENTITY_NUM)
    assert len(o["cand_type"]) == len(legal)
    assert [int(t) for t in o["cand_type"]] == [a[0] for a in legal]
    for t1, t2 in zip(o["cand_target"], o["cand_target2"]):
        assert -1 <= t1 < n and -1 <= t2 < n
    vocab = sim.combat_id_vocab()
    assert all(0 <= i < vocab[k] for k, i in zip(o["kind"], o["id"]))
    assert o["kind"][0] == 0 and o["kind"][1] == 1      # PLAYER, ENCOUNTER


@pytest.mark.parametrize("steps", [0, 3, 8])
def test_entity_observation_ignores_hidden_order(steps):
    """Resampling the hidden state (draw order, RNG) must not change the observation."""
    bc = _later_state(_first_combat(), steps).battle
    base = bc.entity_observation()
    for seed in (1, 2, 3):
        other = bc.clone()
        other.resample_hidden(seed)
        o = other.entity_observation()
        for k in base:
            np.testing.assert_array_equal(base[k], o[k], err_msg=k)


def test_mcts_root_matches_mcts_and_counts_visits():
    bc = _first_combat().battle
    acts, sims, visits = bc.mcts_root(96, seed=7)
    ref, _, _ = bc.mcts(96, 4.242640687, 7, True, False, 0.05, 4.0)
    assert acts[0] == ref[0]
    assert len(visits) == len(bc.legal_actions()) and sum(visits) == sims == 96


def test_net_search_uniform_and_errors():
    bc = _first_combat().battle
    s = sim.NetSearch(bc, 40, seed=3)
    evals = 0
    while s.advance():
        c = len(s.pending_observation()["cand_type"])
        with pytest.raises(Exception):
            s.provide([1.0] * (c + 1), 0.5)
        s.provide([1.0] * c, 0.5)
        evals += 1
    assert s.simulations_done == 40 and sum(s.root_visits()) == 39   # the root evaluation has no edge
    assert tuple(s.best_action()) in [tuple(a) for a in bc.legal_actions()]
    assert not s.waiting


def test_net_search_batch_api_matches_single():
    bc = _first_combat().battle
    def run(batch):
        ss = [sim.NetSearch(bc, 24, seed=k) for k in range(3)]
        if batch:
            while True:
                d = sim.net_search_advance(ss, 1)
                if not d["index"]:
                    break
                cl = d["cand_len"]
                pri = np.concatenate([np.arange(1, k + 1, dtype=float) for k in cl])
                sim.net_search_provide(ss, d["index"], pri, cl.tolist(), [0.3] * len(cl))
        else:
            for s in ss:
                while s.advance():
                    c = len(s.pending_observation()["cand_type"])
                    s.provide(list(np.arange(1, c + 1, dtype=float)), 0.3)
        return [s.root_visits() for s in ss]
    assert run(True) == run(False)


def test_combat_net_forward_and_players():
    torch.manual_seed(0)
    rc = _first_combat()
    snap = rc.snapshot()
    net = CombatNet(CombatNetConfig(dim=32, layers=1, heads=2))
    obs = [rc.battle.entity_observation(), _later_state(rc).battle.entity_observation()]
    b = collate_obs(obs)
    logp, value = net(b)
    assert logp.shape[0] == 2 and value.shape == (2,)
    assert torch.allclose(logp.exp().sum(-1), torch.ones(2), atol=1e-5)
    target = torch.zeros_like(logp)
    target[:, 0] = 1.0
    loss, parts = losses(net, b, target, torch.tensor([0.5, 0.7]))
    loss.backward()
    res = cp.play_batch([snap, snap], ("netsearch", net, {"normal": 8, "elite": 8, "boss": 8}), seed=1)
    assert all(r.ok and r.decisions > 0 and (r.won or r.died) for r in res)
    again = cp.play_batch([snap, snap], ("netsearch", net, {"normal": 8, "elite": 8, "boss": 8}), seed=1)
    assert [(r.hp_after, r.decisions) for r in res] == [(r.hp_after, r.decisions) for r in again]   # deterministic
