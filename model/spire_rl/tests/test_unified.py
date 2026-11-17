"""Unified observation (in/out of combat) and the unified network."""
import random

import numpy as np
import pytest
import torch

from spire_rl.sim import sim
from spire_rl import unified_obs as uo
from spire_rl.unified_net import UnifiedNet, UnifiedNetConfig, ValueWeights, collate, combine


def _run_to_combat(seed="UNIFIED1"):
    rng = random.Random(0)
    rc = sim.RunContext()
    rc.init_seed(seed, 0)
    while rc.screen != sim.RunScreen.COMBAT:
        acts = rc.legal_actions()
        rc.step(*acts[rng.randrange(len(acts))])
    return rc


def _into_fight(rc, steps=5):
    rc = rc.clone()
    for k in range(steps):
        legal = rc.battle.legal_actions()
        if rc.screen != sim.RunScreen.COMBAT or not legal:
            break
        rc.step_combat(*legal[k % len(legal)])
    return rc


def _macro_state():
    rc = sim.RunContext()
    rc.init_seed("UNIFIED2", 0)
    return rc


def test_out_of_combat_is_the_macro_observation():
    rc = _macro_state()
    m = rc.macro_observation()
    o = uo.observe(rc)
    assert not o.in_combat
    np.testing.assert_array_equal(o.kind, m["kind"])
    np.testing.assert_array_equal(o.id, m["id"])
    np.testing.assert_array_equal(o.num[:, :uo.MACRO_NUM], np.asarray(m["num"]).reshape(len(m["kind"]), -1))
    assert not o.num[:, uo.MACRO_NUM:].any()
    np.testing.assert_array_equal(o.edges, np.asarray(m["edges"]).reshape(-1, 2))
    np.testing.assert_array_equal(o.cand_type, m["cand_type"])
    np.testing.assert_array_equal(o.cand_index, m["cand_index"])
    assert (o.cand_type < uo.RUN_TYPES).all() and not o.player_row.any()
    assert o.act == 0 and o.floor == int(rc.floor)


def test_in_combat_layout_and_patched_global_row():
    rc = _into_fight(_run_to_combat())
    bc = rc.battle
    o = uo.observe(rc)
    m = rc.macro_observation()
    c = bc.entity_observation()
    n_macro = int((np.asarray(m["kind"]) != uo.K_POTION).sum())
    assert o.in_combat and len(o.kind) == n_macro + len(c["kind"])
    assert (o.kind[:n_macro] < uo.MACRO_KINDS).all() and (o.kind[n_macro:] >= uo.MACRO_KINDS).all()
    assert uo.K_POTION not in o.kind[:n_macro].tolist()           # stale run potions dropped
    # the GLOBAL row follows the fight, not the pre-combat run state
    assert o.global_row[uo.G_HP] == pytest.approx(bc.player_hp / 100.0)
    assert o.global_row[uo.G_HPFRAC] == pytest.approx(bc.player_hp / bc.player_max_hp)
    assert o.global_row[uo.G_POTIONS] == pytest.approx(bc.potion_count / 5.0)
    gi = int(np.where(o.kind == uo.K_GLOBAL)[0][0])
    row = o.global_row.copy(); row[list(uo.FIGHT_VARYING)] = 0.0
    np.testing.assert_array_equal(o.num[gi, :uo.MACRO_NUM], row)      # constant during the fight
    # candidates = legal combat actions, pointing at combat entities
    legal = bc.legal_actions()
    assert len(o.cand_type) == len(legal)
    assert [int(t) - uo.RUN_TYPES for t in o.cand_type] == [a[0] for a in legal]
    for t in np.concatenate([o.cand_t1, o.cand_t2]):
        assert t == -1 or n_macro <= t < len(o.kind)
    # map edges survive the potion removal and still point at map nodes
    assert len(o.edges) == len(np.asarray(m["edges"]).reshape(-1, 2))
    assert (o.kind[o.edges] == 5).all()


@pytest.mark.parametrize("steps", [0, 4])
def test_in_combat_observation_ignores_hidden_state(steps):
    rc = _into_fight(_run_to_combat(), steps)
    ctx = uo.run_context(rc.macro_observation())
    base = uo.combat_obs(ctx, rc.battle.entity_observation())
    for seed in (1, 2):
        bc = rc.battle.clone()
        bc.resample_hidden(seed)
        o = uo.combat_obs(ctx, bc.entity_observation())
        for k in ("kind", "id", "num", "edges", "cand_type", "cand_t1", "cand_t2", "cand_num", "global_row", "player_row"):
            np.testing.assert_array_equal(getattr(base, k), getattr(o, k), err_msg=k)


def test_search_leaves_use_the_same_layout():
    from spire_rl.combat_net import collate_packed  # noqa: F401  (packed format shared with NetSearch)
    rc = _run_to_combat()
    ctx = uo.run_context(rc.macro_observation())
    s = sim.NetSearch(rc.battle, 8, seed=1)
    d = sim.net_search_advance([s], 1)
    assert list(d["index"]) == [0]
    leaf = {k: np.asarray(d[k]) for k in ("kind", "id", "num", "cand_type", "cand_target", "cand_target2", "cand_num")}
    leaf["num"] = leaf["num"].reshape(len(leaf["kind"]), -1)
    o = uo.combat_obs(ctx, leaf)
    ref = uo.observe(rc, ctx)
    for k in ("kind", "id", "num", "cand_type", "cand_t1", "cand_t2", "global_row"):
        np.testing.assert_array_equal(getattr(ref, k), getattr(o, k), err_msg=k)


def _net():
    torch.manual_seed(0)
    return UnifiedNet(UnifiedNetConfig(dim=32, ctx_layers=2, combat_layers=1, heads=2)).eval()


def _permute(o: uo.UObs, rng) -> uo.UObs:
    """Shuffle the run-context entities and the combat entities (each part stays a set)."""
    perm = np.concatenate([rng.permutation(o.n_ctx), o.n_ctx + rng.permutation(len(o.kind) - o.n_ctx)])
    inv = np.empty_like(perm); inv[perm] = np.arange(len(perm))
    remap = lambda t: np.where(t >= 0, inv[np.maximum(t, 0)], -1)
    return uo.UObs(o.kind[perm], o.id[perm], o.num[perm], inv[o.edges] if len(o.edges) else o.edges, o.global_row,
                   o.player_row, o.cand_type, o.cand_index, remap(o.cand_t1), remap(o.cand_t2), o.cand_num, o.in_combat,
                   o.n_ctx)


def test_network_is_a_set_function_in_and_out_of_combat():
    net = _net()
    rng = np.random.default_rng(0)
    for o in (uo.observe(_macro_state()), uo.observe(_into_fight(_run_to_combat()))):
        with torch.no_grad():
            a = net(collate([o]))
            b = net(collate([_permute(o, rng)]))
        torch.testing.assert_close(a["logp"], b["logp"], atol=1e-5, rtol=1e-5)
        torch.testing.assert_close(a["q_logit"], b["q_logit"], atol=1e-5, rtol=1e-5)


def test_batching_matches_single_and_hp_reaches_the_heads():
    net = _net()
    obs = [uo.observe(_macro_state()), uo.observe(_into_fight(_run_to_combat())), uo.observe(_run_to_combat("UNIFIED3"))]
    with torch.no_grad():
        both = net(collate(obs))
        for i, o in enumerate(obs):
            one = net(collate([o]))
            c = len(o.cand_type)
            torch.testing.assert_close(one["logp"][0, :c], both["logp"][i, :c], atol=1e-5, rtol=1e-5)
            torch.testing.assert_close(one["q_logit"][0], both["q_logit"][i], atol=1e-5, rtol=1e-5)
    # the GLOBAL row feeds the heads directly, not only through the GLOBAL entity
    b = collate([obs[0]])
    b.global_row.requires_grad_(True)
    net(b)["q_logit"][0, 0].backward()
    assert b.global_row.grad[0, uo.G_HPFRAC].abs() > 0


def test_combine_value():
    q = torch.tensor([[0.5, 0.4, 0.2]] * 3)
    act = torch.tensor([0, 1, 2])
    full = combine(q, act, ValueWeights(r=(1.0, 1.0, 1.0), w=(1.0, 1.0)))
    # w = 1, r = 1: expected number of acts passed from here
    torch.testing.assert_close(full, torch.tensor([0.5 + 0.5 * 0.4 + 0.5 * 0.4 * 0.2, 0.5 + 0.5 * 0.4, 0.5]))
    u = combine(q, act)                     # user's setting: r3 = 3, w1 = 0.2, w2 = 0.5
    torch.testing.assert_close(u, torch.tensor([0.5 * (1 + 0.2 * 0.4 * (1 + 0.5 * 3 * 0.2)), 0.5 * (1 + 0.5 * 3 * 0.4), 3 * 0.5]))


def test_cached_context_matches_full_forward_for_search_leaves():
    """The run-context encoding of a fight is computed once and reused for every leaf."""
    net = _net()
    rc = _run_to_combat()
    ctx = uo.run_context(rc.macro_observation())
    root = uo.observe(rc, ctx)
    leaves = [uo.observe(_into_fight(rc, k), ctx) for k in (1, 3, 6)]
    with torch.no_grad():
        cached = net.encode_context(collate([root]))
        b = collate(leaves)
        full = net(b)
        reuse = net(b, ctx=(cached[0].expand(len(leaves), -1, -1), cached[1].expand(len(leaves), -1)))
    torch.testing.assert_close(full["logp"], reuse["logp"], atol=1e-5, rtol=1e-5)
    torch.testing.assert_close(full["q_logit"], reuse["q_logit"], atol=1e-5, rtol=1e-5)


def test_recorded_combat_round_trips_to_the_live_observation(tmp_path):
    from types import SimpleNamespace
    from spire_rl import unified_data as ud
    rc = _run_to_combat("UNIFIED4")
    start = rc.clone()
    sink = []
    hook = ud.make_recording_hook({"normal": 16, "elite": 16, "boss": 16}, sink)
    hook(SimpleNamespace(rc=rc, game_seed=77), 5)
    rec = sink[0]
    assert rec.obs and rec.ok
    d = ud.pack(sink, {77: (20, False)})                 # died on floor 20: act 1 passed, act 2 not
    np.savez_compressed(tmp_path / "part_0.npz", **d)
    samples = ud.load_part(str(tmp_path / "part_0.npz"))
    assert len(samples) == len(rec.obs)
    s0 = samples[0]
    assert len(start.battle.legal_actions()) > 1          # so the first recorded decision is the start state
    live = uo.observe(start)
    if True:  # noqa: SIM108 (kept as a block for readability)
        for k in ("kind", "id", "cand_type", "cand_t1", "cand_t2", "edges"):
            np.testing.assert_array_equal(getattr(s0.obs, k), getattr(live, k), err_msg=k)
        for k in ("num", "global_row", "player_row", "cand_num"):           # float16 storage
            np.testing.assert_allclose(getattr(s0.obs, k), getattr(live, k), atol=2e-3, err_msg=k)
        assert s0.obs.act == live.act and s0.obs.floor == live.floor
    assert s0.q.tolist() == [1.0, 0.0, 0.0] and s0.q_mask.tolist() == [1.0, 1.0, 0.0]
    assert abs(s0.policy.sum() - 1.0) < 1e-5 and len(s0.policy) == len(s0.obs.cand_type)
    assert s0.aux[0] in (0.0, 1.0)


def _uniform_search_fight(rc, sims, **kw):
    """Play one fight with NetSearch and uniform priors / constant value; returns how many
    won-fight leaves were handed to the caller and the visit totals."""
    terminal_requests, totals = 0, []
    while rc.screen == sim.RunScreen.COMBAT and rc.battle.legal_actions():
        s = sim.NetSearch(rc.battle, sims, seed=11, **kw)
        while s.advance():
            c = len(s.pending_observation()["cand_type"])
            if c == 0:
                terminal_requests += 1
                s.provide([], 0.9)
            else:
                s.provide([1.0] * c, 0.5)
        totals.append(sum(s.root_visits()))
        rc.step_combat(*s.best_action())
    return terminal_requests, totals


def _near_win(seed, before=2):
    """A state ``before`` decisions before the end of a fight the rollout MCTS wins."""
    rc = _run_to_combat(seed)
    states = []
    while rc.screen == sim.RunScreen.COMBAT and rc.battle.legal_actions():
        states.append(rc.clone())
        acts, _, _ = rc.battle.mcts_root(256, 4.242640687, 7, True, 0.05, 4.0)
        rc.step_combat(*acts[0])
    assert rc.battle.outcome == sim.Outcome.PLAYER_VICTORY
    return states[-1 - before]


def test_net_search_terminal_wins_are_evaluated_by_the_caller():
    # (From the fight start, the uniform search loses these fights and never sees a win.)
    rc = _near_win("UNIFIED5")
    req, totals = _uniform_search_fight(rc.clone(), 48, normalize_q=True, eval_terminal_wins=True)
    assert req > 0                               # the winning lines reached the caller
    assert all(t == 47 for t in totals)          # the root's own expansion uses one simulation
    req_off, _ = _uniform_search_fight(rc.clone(), 48)
    assert req_off == 0                          # default: C++ terminal value, as before


# Recorded with the build before the normalize_q / eval_terminal_wins options (2026-11-16,
# this Mac): the defaults must reproduce it exactly.
_OLD_BUILD_UNIFIED6 = ([3, 6, 9, 12, 15, 18],
                       [(1, 0, 0, 0)] * 8 + [(0, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0),
                                             (0, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0)])


def test_net_search_defaults_reproduce_the_previous_build():
    rc = _run_to_combat("UNIFIED6")
    s = sim.NetSearch(rc.battle, 64, seed=5)
    while s.advance():
        c = len(s.pending_observation()["cand_type"])
        s.provide([float(k + 1) for k in range(c)], 0.3)
    rc2, acts = rc.clone(), []
    while rc2.screen == sim.RunScreen.COMBAT and rc2.battle.legal_actions():
        s2 = sim.NetSearch(rc2.battle, 48, seed=11)
        while s2.advance():
            s2.provide([1.0] * len(s2.pending_observation()["cand_type"]), 0.5)
        a = tuple(s2.best_action()); acts.append(a); rc2.step_combat(*a)
    assert (list(s.root_visits()), acts) == _OLD_BUILD_UNIFIED6
