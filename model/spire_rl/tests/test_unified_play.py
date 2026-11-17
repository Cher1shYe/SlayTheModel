"""Batched combat play with the unified network (evaluation and self-play) and the GPU-machine
data / training entry points (CPU here)."""
import json
import random
from pathlib import Path

import numpy as np
import pytest
import torch

from spire_rl.sim import sim
from spire_rl import combat_play as cp
from spire_rl import unified_data as ud
from spire_rl import unified_play as up
from spire_rl.unified_net import UnifiedNet, UnifiedNetConfig, save

ROOT = Path(__file__).resolve().parents[3]
MACRO_CKPT = next((p for p in (ROOT / "runs/training-review/small-b-d1/last.pt", ROOT / "runs/small-b-d1/last.pt")
                   if p.exists()), ROOT / "runs/small-b-d1/last.pt")      # this Mac / the training machine


def _snapshot(seed):
    rng = random.Random(0)
    rc = sim.RunContext()
    rc.init_seed(seed, 0)
    while rc.screen != sim.RunScreen.COMBAT:
        acts = rc.legal_actions()
        rc.step(*acts[rng.randrange(len(acts))])
    return rc.snapshot()


def _net():
    torch.manual_seed(0)
    return UnifiedNet(UnifiedNetConfig(dim=32, ctx_layers=1, combat_layers=1)).eval()


BUD = {"normal": 12, "elite": 12, "boss": 12}


def test_batched_play_matches_one_combat_at_a_time():
    snaps = [_snapshot("UPLAY1"), _snapshot("UPLAY2")]
    net = _net()
    both = up.play_batch(snaps, net, None, mode="net", seed=3)
    alone = [up.play_batch([s], net, None, mode="net", seed=3 + 104729 * i)[0] for i, s in enumerate(snaps)]
    for a, b in zip(both, alone):
        assert (a.won, a.hp_after, a.decisions, a.potions_after) == (b.won, b.hp_after, b.decisions, b.potions_after)
        assert a.ok


@pytest.mark.parametrize("mode", ["norm", "rate"])
def test_search_play_records_visits_in_legal_order(mode, tmp_path):
    snaps = [_snapshot("UPLAY3"), _snapshot("UPLAY4")]
    res = up.play_batch(snaps, _net(), BUD, mode=mode, seed=1, record=True)
    for r in res:
        assert r.ok and r.decisions > 0 and len(r.obs) == len(r.actions) == len(r.visits) == r.decisions
        for v, a in zip(r.visits, r.actions):
            assert sum(v) == BUD[r.kind] - 1 and v[a] == max(v)    # root expansion uses one; most visited = chosen
        r.meta.update(game_seed=100 + res.index(r), ctx=cp.restore(snaps[res.index(r)]).macro_observation())
    d = ud.pack(res, {100: (20, False), 101: (5, False)})
    np.savez_compressed(tmp_path / "part_00000.npz", **d)
    samples = ud.load_part(str(tmp_path / "part_00000.npz"))
    assert len(samples) == sum(r.decisions for r in res)


def test_part_batches_split_every_decision_once(tmp_path):
    from spire_rl.unified_train import PartBatches
    from spire_rl.unified_pretrain import is_holdout
    snaps = [_snapshot("UPLAY5"), _snapshot("UPLAY6")]
    res = up.play_batch(snaps, _net(), BUD, mode="norm", seed=2, record=True)
    seeds = [5, 11]                                  # one held out (11), one not
    assert sorted(is_holdout(s) for s in seeds) == [False, True]
    for r, s, sn in zip(res, seeds, snaps):
        r.meta.update(game_seed=s, ctx=cp.restore(sn).macro_observation())
    np.savez_compressed(tmp_path / "part_00000.npz", **ud.pack(res, {5: (3, False), 11: (3, False)}))
    files = [str(tmp_path / "part_00000.npz")]
    count = lambda hold: sum(len(cb["n_cand"]) for cb in PartBatches(files, 7, holdout=hold))
    by_seed = {s: r.decisions for r, s in zip(res, seeds)}
    assert count(True) == sum(n for s, n in by_seed.items() if is_holdout(s))
    assert count(False) == sum(n for s, n in by_seed.items() if not is_holdout(s))


@pytest.mark.skipif(not MACRO_CKPT.exists(), reason="needs the small-b-d1 macro checkpoint")
@pytest.mark.parametrize("player", ["mcts", "selfplay"])
def test_gen_writes_parts_and_resumes(player, tmp_path):
    from spire_rl import unified_run
    args = ["gen", "--macro-ckpt", str(MACRO_CKPT), "--out", str(tmp_path / "d"), "--episodes", "2", "--envs", "2",
            "--budgets", "4,4,8", "--episodes-per-part", "1", "--first-seed-default", "123"]
    if player == "selfplay":
        save(tmp_path / "net.pt", _net())
        args += ["--net", str(tmp_path / "net.pt"), "--mode", "rate", "--cpp-threads", "2"]
    unified_run.main(args)
    prog = json.loads((tmp_path / "d/progress.json").read_text())
    assert prog["done"] == 2 and prog["next_seed"] == 125
    parts = sorted((tmp_path / "d").glob("part_*.npz"))
    assert parts
    samples = [s for p in parts for s in ud.load_part(str(p))]
    assert samples and {s.game_seed for s in samples} <= {123, 124}
    unified_run.main(args)                          # target reached: nothing more
    assert json.loads((tmp_path / "d/progress.json").read_text())["done"] == 2
