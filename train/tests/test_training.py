"""Driver guards, sparse packing and an end-to-end PPO smoke run (tiny network, CPU)."""
import json
import random

import numpy as np

from spire_rl import driver as D
from spire_rl import public_obs as p
from spire_rl import rollout, rewards
from spire_rl.sim import sim


def _first(screen, seed=9001, limit=400):
    rng = random.Random(seed)
    rc = sim.RunContext(); rc.init(seed, 10)
    for _ in range(limit):
        s = p.from_simulator(rc)
        if s.facts["screen"] == screen and len(s.actions) > 1:
            return rc, s
        plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
        p.step_simulator(rc, s, rng.choice(plays) if plays else rng.randrange(len(s.actions)))
    raise AssertionError(screen)


def test_pack_roundtrip():
    _, s = _first("combat")
    o = p.encode(s)
    back = rollout.unpack(rollout.pack(o))
    for k in ("num", "global_row", "player_row", "cand_num", "kind", "id", "cand_t1"):
        assert np.array_equal(getattr(o, k), getattr(back, k)), k
    assert back.schema_id == o.schema_id and back.n_ctx == o.n_ctx


def test_repeated_combat_decision_allows_only_end_turn():
    _, s = _first("combat")
    d = D.Driver()
    assert d.decide(s).allowed.all()
    again = d.decide(s).allowed
    kinds = [a.key.kind for a in s.actions]
    assert again.sum() == 1 and kinds[int(np.flatnonzero(again)[0])] == "end_turn"


def test_repeated_room_decision_drops_taken_candidates():
    _, s = _first("map")
    d = D.Driver()
    d.decide(s); d.chose(0)
    d.decide(s); d.chose(0)
    third = d.decide(s).allowed
    assert not third[0] and third[1:].all()


def test_stall_and_cap_are_losses():
    _, s = _first("combat")
    d = D.Driver()
    d.decide(s)
    d._best_turn = s.facts["combat"]["turn"] - D.STALL_TURNS
    assert d.decide(s).verdict == "stall"
    d = D.Driver(); d.decisions = D.DECISION_CAP
    assert d.decide(s).verdict == "cap"


def test_reward_terms():
    r = rewards.Reward()
    a = rewards.Progress(5, 50, 80, 0, 0, False, False)
    total, parts = r(a, rewards.Progress(6, 40, 80, 1, 0, False, False))
    assert abs(parts["floor"] - 0.01) < 1e-9 and abs(parts["elite"] - 0.02) < 1e-9
    assert abs(parts["hp"] - 0.1 * (40 - 50) / 80) < 1e-9
    _, parts = r(a, rewards.Progress(5, 0, 80, 0, 0, True, False))
    assert parts["death"] == -0.1 and abs(parts["hp"] + 0.1 * 50 / 80) < 1e-9   # terminal potential 0


def test_ppo_smoke_and_resume(tmp_path):
    from spire_rl import ppo
    args = ["--run", str(tmp_path / "run"), "--dim", "32", "--ctx-layers", "1", "--combat-layers", "1",
            "--heads", "2", "--workers", "1", "--games", "4", "--samples", "64", "--minibatch", "32",
            "--micro", "16", "--infer-batch", "16", "--device", "cpu"]
    ppo.main(args + ["--max-updates", "1"])
    ppo.main(args + ["--max-updates", "2"])
    log = [json.loads(x) for x in (tmp_path / "run" / "log.jsonl").read_text().splitlines()]
    assert [x["update"] for x in log] == [1, 2] and log[-1]["samples"] == 128
    assert (tmp_path / "run" / "latest.pt").exists() and (tmp_path / "run" / "ema.pt").exists()
    assert all(not x.get("errors") for x in log)
