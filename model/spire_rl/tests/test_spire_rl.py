"""Checks required by the training plan (section 9)."""
from __future__ import annotations

import copy
import dataclasses
import random

import numpy as np
import pytest
import torch

from spire_rl import checkpoint as ckpt
from spire_rl.config import PRESETS, CombatConfig, RewardConfig, make_config
from spire_rl.data import Episode, collate
from spire_rl.env import CombatEvent, EpisodeLog, MacroEnv, Observation, Outcome, aux_labels, raw_reward
from spire_rl.model import SpireNet, count_parameters
from spire_rl.ppo import compute_gae, ppo_update, recompute_check
from spire_rl.train import build_model, env_spec

torch.manual_seed(0)
CFG = make_config("tiny")
WINDOW = CFG.model.window


@pytest.fixture(scope="module")
def episodes():
    """Real observations from short random-policy runs (cheap MCTS)."""
    env = MacroEnv(CombatConfig(normal_simulations=4, boss_simulations=8), RewardConfig())
    out = []
    for seed in range(3):
        rng = random.Random(seed)
        res = env.reset(100 + seed, seed)
        ep = Episode(seed, 100 + seed, 0)
        ep.info["log"] = env.log
        obs = res.next_obs
        while obs is not None and len(ep) < 14:
            a = rng.randrange(obs.num_candidates)
            ep.obs.append(obs)
            ep.actions.append(a)
            r = env.step(a, obs, 1.0)
            ep.reward.append(np.array([r.reward_raw / 5, *r.components], np.float32))
            obs = r.next_obs
            ep.outcome = r.outcome
        if ep.outcome == Outcome.RUNNING:
            ep.outcome = Outcome.TRUNCATED
        ep.logp = [0.0] * len(ep)
        ep.value = [0.0] * len(ep)
        out.append(ep)
    return out


@pytest.fixture(scope="module")
def model():
    m = build_model(CFG, torch.device("cpu"))
    m.eval()
    return m


def targets_of(eps, limit=6):
    return [(ep, t) for ep in eps for t in range(min(len(ep), limit))]


def test_parameter_budgets():
    spec = env_spec(CFG)
    counts = {}
    for name in ("main", "large-0.7b", "large-1b"):
        with torch.device("meta"):
            counts[name] = count_parameters(SpireNet(PRESETS[name], spec))
    assert 0.19e9 < counts["main"] < 0.21e9
    assert 0.65e9 < counts["large-0.7b"] < 0.75e9
    assert 0.90e9 < counts["large-1b"] <= 1.0e9


def test_illegal_and_padding_probability_is_zero(model, episodes):
    out = model(collate(targets_of(episodes), WINDOW))
    b = collate(targets_of(episodes), WINDOW)
    p = torch.softmax(out.logits, -1)
    assert torch.all(p[~b.cand_mask] == 0)
    assert torch.allclose(p.sum(-1), torch.ones(p.shape[0]))


def test_padding_does_not_change_valid_outputs(model, episodes):
    tg = targets_of(episodes)
    together = model(collate(tg, WINDOW))
    for i, target in enumerate(tg):
        alone = model(collate([target], WINDOW))
        c = int(alone.logits.shape[1])
        assert torch.allclose(alone.logits[0], together.logits[i, :c], atol=1e-4)
        assert torch.allclose(alone.value[0], together.value[i], atol=1e-4)


def _permute_obs(o: Observation, perm: np.ndarray) -> Observation:
    inv = np.empty_like(perm)
    inv[perm] = np.arange(len(perm))
    remap = lambda a: np.where(a >= 0, inv[np.maximum(a, 0)], -1).astype(np.int32)
    return Observation(o.kind[perm], o.id[perm], o.num[perm], inv[o.edges] if o.edges.size else o.edges,
                       o.cand_type, o.cand_index, remap(o.cand_target), remap(o.cand_target2), o.cand_num, o.phase)


def test_entity_order_is_irrelevant_and_candidate_order_follows(model, episodes):
    ep = episodes[0]
    base = model(collate([(ep, 0)], WINDOW))
    perm = np.random.default_rng(0).permutation(ep.obs[0].kind.shape[0])
    ep2 = copy.copy(ep)
    ep2.obs = [_permute_obs(ep.obs[0], perm)] + ep.obs[1:]
    shuffled = model(collate([(ep2, 0)], WINDOW))
    assert torch.allclose(base.logits, shuffled.logits, atol=1e-4)
    # Reversing the candidate list reverses the logits.
    o = ep.obs[0]
    rev = slice(None, None, -1)
    ep3 = copy.copy(ep)
    ep3.obs = [dataclasses.replace(o, cand_type=o.cand_type[rev].copy(), cand_index=o.cand_index[rev].copy(),
                                   cand_target=o.cand_target[rev].copy(), cand_target2=o.cand_target2[rev].copy(),
                                   cand_num=o.cand_num[rev].copy())] + ep.obs[1:]
    flipped = model(collate([(ep3, 0)], WINDOW))
    assert torch.allclose(base.logits[0], flipped.logits[0].flip(0), atol=1e-4)


def test_future_does_not_affect_past(model, episodes):
    ep = max(episodes, key=len)
    t = min(3, len(ep) - 1)
    before = model(collate([(ep, t)], WINDOW))
    ep2 = copy.copy(ep)
    ep2.actions = list(ep.actions)
    ep2.reward = [r.copy() for r in ep.reward]
    for k in range(t, len(ep)):            # the target's own action/reward and everything later
        ep2.actions[k] = 0
        ep2.reward[k] = ep2.reward[k] + 7.0
    after = model(collate([(ep2, t)], WINDOW))
    assert torch.allclose(before.logits, after.logits, atol=1e-5)
    if t >= 1:                              # but the past does matter
        ep2.reward[t - 1] = ep2.reward[t - 1] + 7.0
        changed = model(collate([(ep2, t)], WINDOW))
        assert not torch.allclose(before.value, changed.value, atol=1e-6)


def test_logprob_recompute_matches_with_frozen_parameters(model, episodes):
    tg = targets_of(episodes)
    with torch.no_grad():
        out = model(collate(tg, WINDOW))
    logp = torch.log_softmax(out.logits, -1)
    eps = [copy.copy(ep) for ep in episodes]
    for ep in eps:
        ep.logp = [0.0] * len(ep)
    by_id = {ep.episode_id: ep for ep in eps}
    tg2 = [(by_id[ep.episode_id], t) for ep, t in tg]
    for i, (ep, t) in enumerate(tg2):
        ep.logp[t] = float(logp[i, ep.actions[t]])
    assert recompute_check(model, tg2, WINDOW, torch.device("cpu"), False) < 1e-5


def test_gae_terminal_and_truncation():
    ep = Episode(0, 0, 0)
    ep.actions = [0, 0, 0]
    ep.value = [0.5, 0.5, 0.5]
    ep.reward = [np.array([r, 0, 0, 0], np.float32) for r in (0.0, 0.0, 1.0)]
    ep.outcome = Outcome.WIN
    compute_gae(ep, 1.0, 1.0)
    assert np.allclose(ep.returns, [1.0, 1.0, 1.0])              # Monte Carlo return, no bootstrap
    ep.outcome, ep.bootstrap_value = Outcome.TRUNCATED, 2.0
    compute_gae(ep, 1.0, 1.0)
    assert np.allclose(ep.returns, [3.0, 3.0, 3.0])              # bootstraps V(final) once
    ep.outcome = Outcome.DEATH
    ep.reward = [np.zeros(4, np.float32)] * 3
    compute_gae(ep, 1.0, 1.0)
    assert np.allclose(ep.returns, 0.0)                           # death: no bootstrap, return 0


def test_reward_formula():
    r = RewardConfig()
    assert raw_reward(np.array([0, 0, 1]), 0.0, r) == 5.0       # real win at alpha 0
    assert raw_reward(np.array([3, 1, 0]), 0.0, r) == 0.0       # normal failure path earns 0
    assert raw_reward(np.array([1, 0, 0]), 1.0, r) == pytest.approx(0.05)
    assert raw_reward(np.array([2, 1, 0]), 0.5, r) == pytest.approx(0.5 * (0.1 + 0.5))


def test_aux_labels_masked_when_unobserved():
    log = EpisodeLog(combats=[CombatEvent(0, True, 0.7, 0), CombatEvent(2, False, 0.0, 0)],
                     act_at_decision=[0, 0, 0, 0], max_act=0)
    lab = aux_labels(log, 4, Outcome.DEATH)
    assert lab[0, :3].tolist() == [1.0, pytest.approx(0.7), 0.0] and lab[0, 3:].tolist() == [1, 1, 1]
    assert lab[1, 0] == 0.0 and lab[3, 3] == 1.0                  # died before the next fight -> 0
    trunc = aux_labels(EpisodeLog(act_at_decision=[0, 0], max_act=0), 2, Outcome.TRUNCATED)
    assert trunc[:, 3:].sum() == 0                                 # nothing observed -> all masked


def test_microbatch_accumulation_matches_full_batch(episodes):
    tg = targets_of(episodes, limit=4)
    for ep in episodes:
        ep.aux = aux_labels(ep.info["log"], len(ep), ep.outcome)
        compute_gae(ep, 1.0, 0.99)
    grads = []
    for micro in (len(tg), 1):
        torch.manual_seed(0)
        m = build_model(CFG, torch.device("cpu"))
        opt = torch.optim.SGD(m.parameters(), lr=0.0)
        cfg = dataclasses.replace(CFG.ppo, epochs=1, batch_targets=len(tg), microbatch=micro, target_kl=1e9)
        ppo_update(m, opt, tg, cfg, 0.01, WINDOW, torch.device("cpu"), random.Random(0))
        grads.append(torch.cat([p.grad.flatten() for p in m.parameters() if p.grad is not None]))
    assert torch.allclose(grads[0], grads[1], atol=1e-5, rtol=1e-4)


def test_incompatible_checkpoint_is_refused(tmp_path, model):
    path = tmp_path / "best.pt"
    ckpt.save(path, CFG, model, {"episodes_started": 0})
    payload = ckpt.load(path)
    assert payload["fingerprint"] == CFG.fingerprint()
    assert all(t.device.type == "cpu" for t in payload["model"].values())   # loaded to CPU first
    assert "optimizer" not in payload                                          # weights only
    payload["identity"]["macro_obs_version"] = -1
    torch.save(payload, path)
    with pytest.raises(ckpt.IncompatibleCheckpoint):
        ckpt.load(path)


def test_env_records_only_real_choices_and_credits_floors_once():
    env = MacroEnv(CombatConfig(normal_simulations=4, boss_simulations=8), RewardConfig())
    res = env.reset(4242, 1)
    obs, total_floors, rng = res.next_obs, 0, random.Random(1)
    while obs is not None:
        assert obs.num_candidates >= 2                 # forced steps are executed, not recorded
        assert np.all(obs.cand_target < obs.kind.shape[0])
        r = env.step(rng.randrange(obs.num_candidates), obs, 1.0)
        total_floors += int(r.components[0])
        obs = r.next_obs
    assert r.outcome in (Outcome.WIN, Outcome.DEATH, Outcome.TRUNCATED)
    assert total_floors <= int(env.rc.floor)           # never credited twice


def test_unopened_card_rewards_stay_hidden():
    """On the rewards screen a card reward is a slot token, never its cards."""
    from spire_rl.sim import sim
    kinds = {name: i for i, name in enumerate(
        ["GLOBAL", "CONTEXT", "DECK_CARD", "RELIC", "POTION", "MAP_NODE", "BOSS", "OFFER_CARD",
         "OFFER_RELIC", "OFFER_POTION", "REWARD", "EVENT_OPTION", "SPHERE_CELL"])}
    assert len(kinds) == len(sim.macro_vocab())
    rewards_screen = int(sim.RunScreen.REWARDS)
    seen_slot = False
    for seed in range(6):
        env = MacroEnv(CombatConfig(normal_simulations=4, boss_simulations=8), RewardConfig())
        obs, rng = env.reset(500 + seed, seed).next_obs, random.Random(seed)
        while obs is not None:
            if obs.phase // 2 == rewards_screen:
                offer = obs.kind == kinds["OFFER_CARD"]
                reward_source = obs.num[offer][:, 53] if offer.any() else np.zeros(0)
                assert not (reward_source == 1).any()       # SRC_REWARD offers only on CARD_REWARD
                seen_slot |= bool(((obs.kind == kinds["REWARD"]) & (obs.id == 3)).any())
            obs = env.step(rng.randrange(obs.num_candidates), obs, 1.0).next_obs
    assert seen_slot


def test_evaluation_is_reproducible(model):
    from spire_rl.train import evaluate
    cfg = make_config("tiny", val_seeds=(9_000_000, 4), combat={"normal_simulations": 4, "boss_simulations": 8})
    a = evaluate(model, cfg, torch.device("cpu"), "val", num_envs=3)
    b = evaluate(model, cfg, torch.device("cpu"), "val", num_envs=2)   # different thread interleaving
    keys = ("wins", "floor_mean", "reach_act2", "failures", "truncations")
    assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_archive_round_trip(tmp_path, episodes, model):
    from spire_rl.archive import read_rollout, write_rollout
    path = tmp_path / "rollout.npz"
    write_rollout(path, episodes, {"behaviour_updates": 3})
    meta, back = read_rollout(path)
    assert meta["behaviour_updates"] == 3 and len(back) == len(episodes)
    for a, b in zip(episodes, back):
        assert (a.episode_id, a.outcome, a.actions) == (b.episode_id, b.outcome, b.actions)
        for oa, ob in zip(a.obs, b.obs):
            for name in ("kind", "id", "num", "edges", "cand_type", "cand_target", "cand_num"):
                assert np.array_equal(getattr(oa, name), getattr(ob, name))
    # The archived history reproduces the same network input.
    assert torch.allclose(model(collate(targets_of(episodes), WINDOW)).logits,
                          model(collate(targets_of(back), WINDOW)).logits)


def test_paired_compare():
    from spire_rl.tools import paired_compare
    a = {"per_seed": [{"seed": s, "won": s < 6} for s in range(20)]}
    b = {"per_seed": [{"seed": s, "won": 4 <= s < 8} for s in range(20)]}
    r = paired_compare(a, b)
    assert (r["both"], r["only_a"], r["only_b"], r["neither"]) == (2, 4, 2, 12)
    assert r["mcnemar_exact_p"] == pytest.approx(2 * (1 + 6 + 15) / 64)
    with pytest.raises(ValueError):
        paired_compare(a, {"per_seed": [{"seed": 99, "won": True}]})


def test_bf16_autocast_forward_and_backward(episodes):
    """The CUDA default runs under BF16 autocast; CPU autocast exercises the same dtype mixing."""
    torch.manual_seed(0)
    m = build_model(CFG, torch.device("cpu"))
    b = collate(targets_of(episodes), WINDOW)
    assert b.edge_src.numel() > 0                       # the map message passing is exercised
    with torch.autocast("cpu", dtype=torch.bfloat16):
        out = m(b)
    loss = torch.log_softmax(out.logits.float(), -1)[:, 0].sum() + out.value.float().sum() + out.aux.float().sum()
    loss.backward()
    assert torch.isfinite(loss)
    assert all(p.grad is None or torch.isfinite(p.grad).all() for p in m.parameters())


def test_training_tables_use_cumulative_episodes(tmp_path):
    """metrics.jsonl / metrics.csv (the step-level table) have a monotone cumulative x axis."""
    import csv
    import json
    from spire_rl.train import train
    cfg = make_config("tiny", total_episodes=6, eval_every=3, val_seeds=(9_000_000, 2),
                      combat={"normal_simulations": 4, "boss_simulations": 8})
    train(cfg, tmp_path / "run", torch.device("cpu"), stop_after_updates=3, log=lambda *_: None)
    rows = [json.loads(line) for line in (tmp_path / "run" / "metrics.jsonl").read_text().splitlines()]
    eps = [r["episodes"] for r in rows]
    assert eps == sorted(eps) and eps[-1] == sum(r["rollout_episodes"] for r in rows)
    table = list(csv.DictReader((tmp_path / "run" / "metrics.csv").open()))
    assert [int(r["episodes"]) for r in table] == eps and "reward_raw_mean" in table[0]
    files = {p.name for p in (tmp_path / "run").iterdir()}
    assert "best.pt" in files and not any(f.startswith(("latest", "weights_ep")) for f in files)
    with pytest.raises(FileExistsError):
        train(cfg, tmp_path / "run", torch.device("cpu"), stop_after_updates=1, log=lambda *_: None)
