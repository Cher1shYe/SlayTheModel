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
from spire_rl.data import RUN_ACTION_TYPES, SELECT_GRID_CARD, Episode, candidate_groups, collate
from spire_rl.env import CombatEvent, EpisodeLog, MacroEnv, Observation, Outcome, aux_labels, raw_reward
from spire_rl.model import SpireNet, count_parameters, value_weights
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
        ep.value_comps = [np.zeros(3, np.float32)] * len(ep)
        ep.info["value_weights"] = value_weights(1.0, RewardConfig())
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
        compute_gae(ep, 1.0, 0.99, ep.info["value_weights"])
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


@pytest.mark.parametrize("version", [1, 2])
def test_archive_reads_older_formats(tmp_path, episodes, version):
    import json
    from spire_rl.archive import read_rollout, write_rollout
    path = tmp_path / "old.npz"
    write_rollout(path, episodes, {})
    with np.load(path) as z:
        arrays = {k: z[k] for k in z.files if k != "forks_json" and (version != 1 or k != "value_comps")}
    meta = json.loads(bytes(arrays["meta"]).decode())
    meta["format"] = f"spire_rl.archive/{version}"
    arrays["meta"] = np.frombuffer(json.dumps(meta).encode(), np.uint8)
    np.savez_compressed(path, **arrays)
    _, back = read_rollout(path)
    assert [e.actions for e in back] == [e.actions for e in episodes]
    assert all(not e.info.get("forks") for e in back)


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
    """Training runs under CUDA BF16 autocast: test there when a GPU exists, else on CPU.

    Some CPUs' oneDNN builds cannot run BF16 backward ("DNNL does not support
    bf16/f16 backward", seen on avx2_vnni_2); training never uses that path, so skip.
    """
    torch.manual_seed(0)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    m = build_model(CFG, dev)
    b = collate(targets_of(episodes), WINDOW).to(dev)
    assert b.edge_src.numel() > 0                       # the map message passing is exercised
    try:
        with torch.autocast(dev.type, dtype=torch.bfloat16):
            out = m(b)
        loss = torch.log_softmax(out.logits.float(), -1)[:, 0].sum() + out.value.float().sum() + out.aux.float().sum()
        loss.backward()
    except RuntimeError as exc:
        if dev.type == "cpu" and "does not support bf16" in str(exc):
            pytest.skip(f"CPU BF16 backward unsupported here: {exc}")
        raise
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
    assert "best.pt" in files and "last.pt" in files and not any(f.startswith(("latest", "weights_ep")) for f in files)
    last = ckpt.load(tmp_path / "run" / "last.pt")
    assert last["critic"] is not None and last["progress"].get("final")          # separate critic saved
    with pytest.raises(FileExistsError):
        train(cfg, tmp_path / "run", torch.device("cpu"), stop_after_updates=1, log=lambda *_: None)


# --- 2026-11-10 review: P0 regressions -------------------------------------------------

def test_constants_match_simulator():
    from spire_rl.sim import sim
    assert SELECT_GRID_CARD == int(sim.RunActionType.SELECT_GRID_CARD)
    assert RUN_ACTION_TYPES == int(sim.RUN_ACTION_TYPES)


def test_inputs_carry_no_training_condition(model, episodes):
    """G2: the same history collected under another stage/alpha gives the same policy input."""
    other = []
    for ep in episodes:
        e = copy.copy(ep)
        e.stage = 3
        e.reward = [np.array([0.0, *r[1:]], np.float32) for r in ep.reward]   # alpha = 0 r_train
        other.append(e)
    with torch.no_grad():
        a = model(collate(targets_of(episodes), WINDOW))
        b = model(collate(targets_of(other), WINDOW))
    assert torch.equal(a.logits, b.logits) and torch.equal(a.value, b.value)


def test_factorized_policy_is_normalized_and_starts_uniform_over_groups(model, episodes):
    with torch.no_grad():
        out = model(collate(targets_of(episodes, limit=14), WINDOW))
    p = out.logits.exp()
    assert torch.allclose(p.sum(-1), torch.ones(p.shape[0]), atol=1e-5)
    gp = out.group_logp.exp()
    present = (gp > 1e-6).sum(-1)
    assert torch.allclose(gp.max(-1).values, 1.0 / present, atol=0.02)   # ~uniform over groups at init


def test_component_gae_equals_scalar_gae_on_combined_value():
    gen = np.random.default_rng(0)
    w = value_weights(0.5, RewardConfig())
    for outcome in (Outcome.DEATH, Outcome.WIN, Outcome.TRUNCATED):
        ep = Episode(0, 0, 0)
        ep.actions = [0] * 5
        ep.value_comps = list(gen.random((5, 3)).astype(np.float32))
        events = gen.integers(0, 2, (5, 3)).astype(np.float32)
        ep.reward = [np.array([float(e @ np.asarray(w)), *e], np.float32) for e in events]
        ep.bootstrap_comps = gen.random(3).astype(np.float32)
        ep.outcome = outcome
        compute_gae(ep, 1.0, 0.9, w)
        comp_adv = ep.advantages.copy()
        from spire_rl.model import combine_value
        ep.value = [float(combine_value(c, 0.5, RewardConfig())) for c in ep.value_comps]
        ep.bootstrap_value = float(combine_value(ep.bootstrap_comps, 0.5, RewardConfig()))
        compute_gae(ep, 1.0, 0.9)
        assert np.allclose(comp_adv, ep.advantages, atol=1e-5)


def test_candidate_groups_split_deselect():
    def obs(num):
        n = len(num)
        return Observation(np.zeros(2, np.int32), np.zeros(2, np.int32), np.zeros((2, 80), np.float32),
                           np.zeros((0, 2), np.int32), np.array([SELECT_GRID_CARD] * (n - 1) + [26], np.int32),
                           np.arange(n, dtype=np.int32), -np.ones(n, np.int32), -np.ones(n, np.int32),
                           np.asarray(num, np.float32), 9)
    v2 = obs([[0, 0, 0, 1, 0], [0, 0, 0, 1, 1], [0, 0, 0, 0, 0]])
    assert candidate_groups(v2).tolist() == [SELECT_GRID_CARD, RUN_ACTION_TYPES, 26]
    v1 = obs([[0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 0]])                    # observation v1: no flag
    assert candidate_groups(v1).tolist() == [SELECT_GRID_CARD, SELECT_GRID_CARD, 26]


class _GridForever:
    """Stand-in run context: a card grid whose toggles never close it."""
    is_terminal = won = truncated = False
    screen = None
    floor = act = 0

    def step(self, *_):
        return True

    def macro_observation(self):
        return {"kind": np.zeros(2, np.int32), "id": np.zeros(2, np.int32), "num": np.zeros((2, 80), np.float32),
                "edges": np.zeros((0, 2), np.int32), "cand_type": np.array([SELECT_GRID_CARD, 26], np.int32),
                "cand_index": np.arange(2, dtype=np.int32), "cand_target": -np.ones(2, np.int32),
                "cand_target2": -np.ones(2, np.int32), "cand_num": np.zeros((2, 4), np.float32), "phase": 7}


def test_menu_loop_guard_truncates_without_choosing():
    """G3: a grid that is toggled forever ends as a menu_loop truncation; no action is taken for the policy."""
    env = MacroEnv(CombatConfig(), RewardConfig(), max_macro_steps=10_000, max_grid_steps=5)
    env.rc = _GridForever()
    env.decisions = env.macro_steps = env.combat_index = env.mcts_decision_counter = 0
    env.log, env.credited_floor, env.max_act, env.grid_phase, env.grid_steps = EpisodeLog(), 0, 0, -1, 0
    obs = Observation.capture(env.rc)
    outcomes = []
    for _ in range(10):
        r = env.step(0, obs, 1.0)                      # always the toggle, never confirm
        outcomes.append(r.outcome)
        if r.outcome != Outcome.RUNNING:
            break
        obs = r.next_obs
    assert outcomes == [Outcome.RUNNING] * 4 + [Outcome.TRUNCATED]
    assert r.failure_reason == "menu_loop" and r.final_obs is not None and env.log.menu_loops == 1


# --- 2026-11-10 second batch: separate critic, sampled KL stop -----------------------

def _prepared(episodes):
    for ep in episodes:
        ep.aux = aux_labels(ep.info["log"], len(ep), ep.outcome)
        ep.value_comps = [np.zeros(3, np.float32)] * len(ep)
        compute_gae(ep, 1.0, 0.99, ep.info["value_weights"])
    return targets_of(episodes, limit=14)


def test_critic_value_passes_reduce_value_loss(episodes):
    from spire_rl.ppo import critic_update
    from spire_rl.train import build_critic
    torch.manual_seed(0)
    tg = _prepared(episodes)
    critic = build_critic(CFG, torch.device("cpu"))
    opt = torch.optim.AdamW(critic.parameters(), lr=1e-3)
    cfg = dataclasses.replace(CFG.ppo, value_epochs=1)
    first = critic_update(critic, opt, tg, cfg, CFG.critic.window, torch.device("cpu"), random.Random(0))
    for _ in range(5):
        last = critic_update(critic, opt, tg, cfg, CFG.critic.window, torch.device("cpu"), random.Random(0))
    assert last["value_loss"] < first["value_loss"]


def test_policy_update_with_critic_has_no_value_term_and_kl_stops(episodes):
    torch.manual_seed(0)
    tg = _prepared(episodes)
    m = build_model(CFG, torch.device("cpu"))
    with torch.no_grad():
        lp = torch.log_softmax(m(collate(tg, WINDOW)).logits, -1)
    for i, (ep, t) in enumerate(tg):
        ep.logp = list(ep.logp)
        ep.logp[t] = float(lp[i, ep.actions[t]])
    opt = torch.optim.SGD(m.parameters(), lr=50.0)      # absurd step -> must stop on KL
    cfg = dataclasses.replace(CFG.ppo, epochs=4, batch_targets=4, target_kl=1e-6, kl_check_every=1)
    from spire_rl.train import build_critic
    critic = build_critic(CFG, torch.device("cpu"))
    copt = torch.optim.AdamW(critic.parameters(), lr=1e-4)
    out = ppo_update(m, opt, tg, cfg, 0.01, WINDOW, torch.device("cpu"), random.Random(0), critic, copt).values
    assert out["kl_early_stop"] and out["kl_stop_reason"] in ("minibatch_kl", "sampled_kl")
    assert out["optimizer_steps"] < 4 * len(tg) / 4
    assert "value_loss" in out and out["critic_steps"] > 0               # critic still trained


# --- run 3: paired forks, warm start, critic prior ------------------------------------

def _fork_cfg():
    return make_config("tiny", combat={"normal_simulations": 4, "boss_simulations": 8},
                       fork={"rest_prob": 1.0, "map_prob": 1.0, "card_prob": 1.0, "seeds": 2, "max_combats": 1,
                             "max_decisions": 6, "card_max_decisions": 10, "max_active_branches": 100_000})


def _collect_with_forks(cfg, model, critic, n_jobs=3):
    from spire_rl.rollout import Collector, Job
    col = Collector(cfg, model, torch.device("cpu"), num_envs=2, critic=critic)
    try:
        return col.collect((Job(i, 4000 + i, 77 + i) for i in range(n_jobs)), 0, 1.0, None, sample_seed=5, forks=True)
    finally:
        col.close()


def test_paired_forks_are_complete_deterministic_and_centred(tmp_path):
    from spire_rl.archive import read_rollout, write_rollout
    from spire_rl.model import VALUE_SCALE
    from spire_rl.ppo import prepare
    from spire_rl.rollout import fork_option_returns
    from spire_rl.train import build_critic
    cfg = _fork_cfg()
    torch.manual_seed(0)
    m, c = build_model(cfg, torch.device("cpu")).eval(), build_critic(cfg, torch.device("cpu")).eval()
    a = _collect_with_forks(cfg, m, c)
    b = _collect_with_forks(cfg, m, c)
    fa = [f for ep in a.episodes for f in ep.info.get("forks", [])]
    fb = [f for ep in b.episodes for f in ep.info.get("forks", [])]
    assert len(fa) > 0 and a.stats["forks_complete"] > 0
    ra = [fork_option_returns(f, 2) for f in fa]
    assert all(r is not None for r in ra)                              # every branch reported
    # Episodes finish in thread-dependent order; compare the same decision, not list positions.
    roots_a = {(f.episode.episode_id, f.t): f for f in fa}
    roots_b = {(f.episode.episode_id, f.t): f for f in fb}
    assert roots_a.keys() == roots_b.keys()
    for key, f in roots_a.items():
        other = roots_b[key]
        assert f.options == other.options
        np.testing.assert_allclose(fork_option_returns(f, 2), fork_option_returns(other, 2), rtol=1e-5, atol=1e-8)
    assert all(f.options[0] == f.episode.actions[f.t] for f in fa)     # the taken action is option 0
    # Audit records retain the evidence, without storing branch trajectories as episodes.
    weights = np.asarray(value_weights(1.0, cfg.reward))
    for f in fa:
        for (k, s), d in f.details.items():
            assert d["search_seed"] == f.details[(0, s)]["search_seed"]
            assert d["sample_seed"] == f.details[(0, s)]["sample_seed"]
            reconstructed = (np.asarray(d["events"]) + np.asarray(d["bootstrap_comps"]) * VALUE_SCALE) @ weights
            assert f.returns[k, s] == pytest.approx(reconstructed)
            assert d["stop_reason"] and d["decisions"] > 0
    path = tmp_path / "forks.npz"
    write_rollout(path, a.episodes, {"behaviour_updates": 7})
    meta, back = read_rollout(path)
    assert meta["format"] == "spire_rl.archive/3" and meta["behaviour_updates"] == 7
    assert sum(map(len, back)) == a.transitions
    restored = [f for ep in back for f in ep.info.get("forks", [])]
    assert len(restored) == len(fa)
    for old, new in zip(fa, restored):
        assert (old.t, old.options, old.groups, old.group_level, old.screen, old.failed) == (
            new.t, new.options, new.groups, new.group_level, new.screen, new.failed)
        assert old.returns == new.returns and old.details == new.details
        np.testing.assert_array_equal(fork_option_returns(old, 2), fork_option_returns(new, 2))
    # branches never become PPO data
    assert sum(len(ep) for ep in a.episodes) == a.transitions
    targets = prepare(a.episodes, cfg.ppo, cfg.fork.seeds)
    fts = [v for ep in a.episodes for v in ep.fork_targets.values()]
    assert fts and all(abs(float(v[3].sum())) < 1e-6 for v in fts)    # centred advantages
    m.train()
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4)
    copt = torch.optim.AdamW(c.parameters(), lr=1e-4)
    out = ppo_update(m, opt, targets, dataclasses.replace(cfg.ppo, epochs=1), 0.01, cfg.model.window,
                     torch.device("cpu"), random.Random(0), c, copt, fork_coef=1.0).values
    assert out["fork_targets_seen"] > 0 and np.isfinite(out["fork_loss"])


def test_fork_stats_separate_ties_and_count_all_attempted_branches():
    from spire_rl.rollout import Fork, fork_stats
    ep = Episode(0, 42, 0)

    def fork(values, failed=False):
        return Fork(0, ep, 0, list(range(len(values))), list(range(len(values))), False, 0,
                    returns={(k, s): v for k, v in enumerate(values) for s in range(2)}, failed=failed)

    tied = fork_stats([fork([1, 1])], 2)
    assert np.isnan(tied["fork_taken_was_best"])
    assert tied["fork_decisive"] == 0 and tied["fork_tie_rate"] == 1
    # Top ties are excluded, even when a third option is worse; failed branches still cost work.
    stats = fork_stats([fork([1, 1, 0]), fork([2, 1]), fork([1, 2]), fork([9, 0], failed=True)], 2)
    assert stats["fork_taken_was_best"] == 0.5
    assert stats["fork_decisive"] == 2 and stats["fork_tie_rate"] == pytest.approx(1 / 3)
    assert stats["fork_branches"] == 18 and stats["forks_complete"] == 3
    assert stats["fork_map_taken_was_best"] == 0.5 and np.isnan(stats["fork_card_taken_was_best"])   # all on screen 0


@pytest.mark.parametrize("floor_evs,best_epoch", [([0.3, 0.2], 0), ([0.5, 0.5], 0),
                                                 ([float("nan"), 0.4], 0), ([0.8, 0.6], 1)])
def test_critic_prior_selection_includes_initial_weights(tmp_path, episodes, monkeypatch, floor_evs, best_epoch):
    from spire_rl import pretrain
    from spire_rl.archive import write_rollout
    from spire_rl.train import build_critic
    device = torch.device("cpu")
    critic = build_critic(CFG, device)
    ckpt.save(tmp_path / "last.pt", CFG, build_model(CFG, device), {}, critic)
    snapshots = [{k: v.clone() for k, v in critic.state_dict().items()}]
    for i in range(3):
        ep = copy.deepcopy(episodes[0])
        ep.episode_id, ep.outcome = i, Outcome.DEATH
        write_rollout(tmp_path / "archive" / f"rollout_{i:05d}.npz", [ep], {})
    evs = iter({"floors": v, "acts": 0.2, "win": None} for v in [0.5, *floor_evs])
    monkeypatch.setattr(pretrain, "evaluate_critic", lambda *a, **kw: next(evs))

    def update(model, *args, **kwargs):
        with torch.no_grad():
            next(model.parameters()).add_(1.0)
        snapshots.append({k: v.clone() for k, v in model.state_dict().items()})
        return {"value_loss": 0.0}

    monkeypatch.setattr(pretrain, "critic_update", update)
    out = tmp_path / "prior.pt"
    report = pretrain.pretrain_critic(CFG, [tmp_path / "archive"], out, device,
                                      init_checkpoint=tmp_path / "last.pt", epochs=2, holdout_files=1,
                                      log=lambda *_: None)
    saved = torch.load(out, weights_only=False)
    assert report["best_epoch"] == saved["epoch"] == best_epoch
    assert report["improved"] == (best_epoch > 0)
    assert all(torch.equal(v, snapshots[best_epoch][k]) for k, v in saved["critic"].items())


def test_warm_start_and_critic_prior(tmp_path):
    import json
    from spire_rl.pretrain import pretrain_critic
    from spire_rl.train import train
    cfg = make_config("tiny", total_episodes=8, eval_every=100, val_seeds=(9_000_000, 2),
                      combat={"normal_simulations": 4, "boss_simulations": 8}, ppo={"min_transitions": 4})
    train(cfg, tmp_path / "a", torch.device("cpu"), stop_after_updates=3, log=lambda *_: None)
    assert len(list((tmp_path / "a" / "archive").glob("rollout_*.npz"))) >= 2
    src = ckpt.load(tmp_path / "a" / "last.pt")
    rep = pretrain_critic(cfg, [tmp_path / "a" / "archive"], tmp_path / "prior.pt", torch.device("cpu"),
                          init_checkpoint=tmp_path / "a" / "last.pt", epochs=1, holdout_files=1, microbatch=8,
                          log=lambda *_: None)
    assert (tmp_path / "prior.pt").exists() and "floors" in rep["epochs"][0]["heldout_ev"]
    cfg2 = dataclasses.replace(cfg, total_episodes=2, fork=dataclasses.replace(cfg.fork, rest_prob=1.0, map_prob=1.0))
    train(cfg2, tmp_path / "b", torch.device("cpu"), stop_after_updates=1, log=lambda *_: None,
          init_checkpoint=tmp_path / "a" / "last.pt", critic_prior=tmp_path / "prior.pt")
    meta = json.loads((tmp_path / "b" / "config.json").read_text())
    assert meta["init_checkpoint"]["path"].endswith("last.pt") and meta["critic_from"] == "critic_prior"
    from spire_rl.archive import read_rollout
    archive_meta, eps = read_rollout(next((tmp_path / "b" / "archive").glob("rollout_*.npz")))
    assert archive_meta["fork_config"]["seeds"] == cfg2.fork.seeds
    assert archive_meta["value_weights"] == list(value_weights(1.0, cfg2.reward))
    assert any(e.info.get("forks") for e in eps)
    # the warm-started policy starts from exactly the saved weights
    from spire_rl.train import load_initial_weights
    m = build_model(cfg, torch.device("cpu"))
    load_initial_weights(m, None, tmp_path / "a" / "last.pt", None, log=lambda *_: None)
    assert all(torch.equal(v, src["model"][k]) for k, v in m.state_dict().items())


# --- run 4: small preset, per-card forks, distillation, time budget ---------------------

def test_small_preset_and_lite_critic():
    from spire_rl.config import CRITIC_LITE
    spec = env_spec(CFG)
    with torch.device("meta"):
        policy = count_parameters(SpireNet(PRESETS["small"], spec))
        critic = count_parameters(SpireNet(CRITIC_LITE, spec))
    assert 10e6 < policy < 30e6 and PRESETS["small"].window == 8
    assert critic < 4e6 and CRITIC_LITE.dropout > 0
    cfg = make_config("small")
    assert cfg.critic == CRITIC_LITE and cfg.ppo.microbatch == 32 and not cfg.ppo.activation_checkpointing
    assert cfg.ppo.lr_warmup_steps > 0 and make_config("main").ppo.lr_warmup_steps == 0
    assert not cfg.ppo.bf16 and make_config("main").ppo.bf16        # the small network runs in FP32


def test_learning_rate_warms_up_after_a_fresh_optimizer(tmp_path):
    import json
    from spire_rl.train import train
    cfg = make_config("tiny", total_episodes=40, eval_every=1000, val_seeds=(9_000_000, 2),
                      combat={"normal_simulations": 4, "boss_simulations": 8},
                      ppo={"min_transitions": 8, "lr_warmup_steps": 4, "lr": 1e-4})
    train(cfg, tmp_path / "a", torch.device("cpu"), stop_after_updates=4, log=lambda *_: None)
    rows = [json.loads(line) for line in (tmp_path / "a" / "metrics.jsonl").read_text().splitlines()]
    lrs = [r["lr"] for r in rows]
    assert lrs[0] == pytest.approx(1e-5) and lrs[-1] == pytest.approx(1e-4)       # 10% -> 100%
    assert all(a <= b for a, b in zip(lrs, lrs[1:]))


def test_card_forks_compare_every_card_and_ignore_the_critics_win_guess():
    from spire_rl.model import VALUE_SCALE
    from spire_rl.rollout import SCREEN_CARD_REWARD, SKIP_CARD, TAKE_CARD
    from spire_rl.sim import sim
    from spire_rl.train import build_critic
    assert (TAKE_CARD, SKIP_CARD) == (int(sim.RunActionType.TAKE_CARD), int(sim.RunActionType.SKIP_CARD))
    cfg = _fork_cfg()
    # One decision per branch: the random tiny policy dies in its next fight, long before a
    # real act end, so the decision cap is what exercises the bootstrap here.
    cfg = dataclasses.replace(cfg, fork=dataclasses.replace(cfg.fork, rest_prob=0.0, map_prob=0.0,
                                                            card_max_decisions=1))
    torch.manual_seed(0)
    m, c = build_model(cfg, torch.device("cpu")).eval(), build_critic(cfg, torch.device("cpu")).eval()
    with torch.no_grad():
        c.value_head.bias.fill_(0.3)                                    # a critic that "expects" wins
    res = _collect_with_forks(cfg, m, c, n_jobs=6)
    forks = [f for ep in res.episodes for f in ep.info.get("forks", [])]
    assert forks and all(f.screen == SCREEN_CARD_REWARD for f in forks)
    weights = np.asarray(value_weights(1.0, cfg.reward))
    reasons = set()
    for f in forks:
        obs = f.episode.obs[f.t]
        picks = [i for i in range(obs.num_candidates) if int(obs.cand_type[i]) in (TAKE_CARD, SKIP_CARD)]
        assert not f.group_level and f.options[0] == f.episode.actions[f.t]
        assert set(f.options) <= set(picks)
        assert len(f.options) == min(len(picks), cfg.fork.max_options) and len(set(f.options)) == len(f.options)
        for (k, s), d in f.details.items():
            reasons.add(d["stop_reason"])
            assert d["stop_reason"] != "max_combats"                    # no fight limit: to the end of the act
            assert d["bootstrap_comps"][2] == 0.0                       # win guess never enters the return
            if d["stop_reason"] == "act_change":
                assert not d["bootstrapped"]                            # only what really happened
            assert f.returns[k, s] == pytest.approx(
                (np.asarray(d["events"]) + np.asarray(d["bootstrap_comps"]) * VALUE_SCALE) @ weights)
    assert "max_decisions" in reasons                                   # some branches were bootstrapped
    assert res.stats["fork_card"] > 0 and res.stats["fork_branch_decisions"] > 0
    # with bootstrap_win the critic's (here constant 0.3) win output is added
    cfg_w = dataclasses.replace(cfg, fork=dataclasses.replace(cfg.fork, bootstrap_win=True))
    res_w = _collect_with_forks(cfg_w, m, c, n_jobs=6)
    boot = [d for ep in res_w.episodes for f in ep.info.get("forks", []) for d in f.details.values() if d["bootstrapped"]]
    assert boot and all(d["bootstrap_comps"][2] != 0.0 for d in boot)


def test_fork_advantages_are_normalized_per_screen(episodes):
    from spire_rl.ppo import prepare
    from spire_rl.rollout import Fork
    eps = copy.deepcopy(episodes[:2])
    for ep, (screen, values) in zip(eps, ((3, [0.0, 2.0]), (2, [0.0, 0.02, 0.04]))):
        ep.outcome = Outcome.DEATH
        ep.info["forks"] = [Fork(0, ep, 0, list(range(len(values))), list(range(len(values))), False, screen,
                                 returns={(k, s): v for k, v in enumerate(values) for s in range(2)})]
    prepare(eps, CFG.ppo, 2)
    np.testing.assert_allclose(eps[0].fork_targets[0][3], [-1.0, 1.0], atol=1e-6)
    np.testing.assert_allclose(eps[1].fork_targets[0][3], [-1.2247449, 0.0, 1.2247449], atol=1e-5)


def test_simulator_exception_fails_the_episode_not_the_run():
    env = MacroEnv(CombatConfig(normal_simulations=4, boss_simulations=8), RewardConfig())
    res = env.reset(123, 1)
    real = env.rc

    class Boom:
        def __getattr__(self, name):
            return getattr(real, name)

        def step(self, *args):
            raise RuntimeError("The Future of Potions reward pool is too small")

    env.rc = Boom()
    out = env.step(0, res.next_obs, 1.0)
    assert out.outcome == Outcome.FAILURE and "reward pool is too small" in out.failure_reason


def test_future_of_potions_accepts_event_and_token_potions():
    """Ruleset v8: Foul/Glowwater (native Event) and Potion Shaped Rock (Token) no longer throw."""
    from spire_rl.sim import sim
    event = next(e for e in range(sim.event_count()) if sim.event_info(e)[0] == "THE_FUTURE_OF_POTIONS")
    for name in ("FoulPotion", "GlowwaterPotion", "PotionShapedRock"):
        for seed in range(1, 31):
            rc = sim.RunContext()
            rc.init(seed, 0)
            rc.add_potion(int(getattr(sim.PotionId, name)))
            rc.add_potion(int(getattr(sim.PotionId, name)))
            assert rc.begin_event(event)
            assert rc.step(int(sim.RunActionType.EVENT_CHOICE), 0)
            assert rc.step(int(sim.RunActionType.OPEN_CARD_REWARD), 0) and len(rc.offered) == 3


def _cli_args(**kw):
    import argparse
    base = dict(preset="main", init_checkpoint=None, episodes=None, seed=None, train_seed_base=None, num_envs=None,
                microbatch=None, lr=None, gate_policy=None, alpha=None, entropy_coef=0.01, fork_rest_prob=None,
                fork_map_prob=None, fork_card_prob=None, fork_seeds=None, fork_coef=None, critic_replay=None)
    return argparse.Namespace(**{**base, **kw})


def test_time_budget_stop_and_seed_continuation(tmp_path):
    from spire_rl.__main__ import _config
    from spire_rl.train import train
    cfg = make_config("tiny", total_episodes=8, eval_every=100, val_seeds=(9_000_000, 2), train_seed_base=3_000_000,
                      combat={"normal_simulations": 4, "boss_simulations": 8}, ppo={"min_transitions": 4})
    quiet = lambda *_: None
    s = train(cfg, tmp_path / "a", torch.device("cpu"), max_hours=0.0, log=quiet)
    assert s["stopped"] == "max_hours=0.0" and s["updates"] == 0 and (tmp_path / "a" / "last.pt").exists()
    s = train(cfg, tmp_path / "b", torch.device("cpu"), stop_after_updates=1, log=quiet)
    progress = ckpt.load(tmp_path / "b" / "last.pt")["progress"]
    assert progress["next_train_seed"] == 3_000_000 + s["episodes_started"] > 3_000_000
    nxt = _config(_cli_args(init_checkpoint=str(tmp_path / "b" / "last.pt")), log=quiet)
    assert nxt.train_seed_base == progress["next_train_seed"] and nxt.preset == "tiny"
    assert nxt.ppo.min_transitions == make_config("tiny").ppo.min_transitions      # per-preset defaults follow
    assert _config(_cli_args(init_checkpoint=str(tmp_path / "b" / "last.pt"), train_seed_base=5_000_000),
                   log=quiet).train_seed_base == 5_000_000
    with pytest.raises(ValueError, match="overlap the validation seeds"):
        train(dataclasses.replace(cfg, train_seed_base=9_000_000 - 3), tmp_path / "c", torch.device("cpu"), log=quiet)


def test_distill_produces_a_checkpoint_that_training_continues(tmp_path):
    from spire_rl.distill import distill
    from spire_rl.train import train
    quiet = lambda *_: None
    cfg = make_config("tiny", total_episodes=12, eval_every=100, val_seeds=(9_000_000, 2),
                      combat={"normal_simulations": 4, "boss_simulations": 8}, ppo={"min_transitions": 4})
    train(cfg, tmp_path / "a", torch.device("cpu"), stop_after_updates=4, log=quiet)
    rep = distill(make_config("tiny"), [tmp_path / "a" / "archive"], tmp_path / "d.pt", torch.device("cpu"),
                  files=4, holdout_files=1, epochs=2, files_per_chunk=2, microbatch=8, log=quiet)
    held = rep["heldout"]
    assert rep["best_epoch"] in (1, 2) and np.isfinite(held["nll"]) and 0 <= held["top1"] <= 1
    assert held["kl_estimate"] == pytest.approx(held["nll"] - held["teacher_nll"])
    payload = ckpt.load(tmp_path / "d.pt")
    assert payload["critic"] is not None and payload["progress"]["next_train_seed"] == 2_000_000
    cfg2 = dataclasses.replace(cfg, total_episodes=2, train_seed_base=payload["progress"]["next_train_seed"])
    s = train(cfg2, tmp_path / "b", torch.device("cpu"), stop_after_updates=1, log=quiet,
              init_checkpoint=tmp_path / "d.pt")
    assert s["updates"] == 1


def _card_reward_observation():
    """A real card-reward screen (three cards and skip), reached through an event."""
    from spire_rl.sim import sim
    rc = sim.RunContext()
    rc.init(7, 0)
    rc.add_potion(int(sim.PotionId.BlockPotion))
    rc.add_potion(int(sim.PotionId.BlockPotion))
    assert rc.begin_event(next(e for e in range(sim.event_count())
                               if sim.event_info(e)[0] == "THE_FUTURE_OF_POTIONS"))
    assert rc.step(int(sim.RunActionType.EVENT_CHOICE), 0) and rc.step(int(sim.RunActionType.OPEN_CARD_REWARD), 0)
    return Observation.capture(rc)


class _ScriptedEnv:
    """Stands in for MacroEnv: one floor per decision, the third decision enters the next act,
    the fifth ends the run. Lets the collector's branch horizon be checked without a strong policy."""

    def __init__(self, first, later):
        import types
        self.first, self.later = first, later
        self.rc = types.SimpleNamespace(act=0, floor=0)
        self.log, self.n = EpisodeLog(), 0

    def reset(self, game_seed, search_seed):
        self.rc.act = self.rc.floor = self.n = 0
        self.log = EpisodeLog()
        return type("R", (), dict(reward_raw=0.0, components=np.zeros(3, np.float32), outcome=Outcome.RUNNING,
                                  next_obs=self.first, final_obs=None, failure_reason=""))()

    def step(self, candidate, obs, alpha):
        self.n += 1
        self.rc.floor += 1
        comps = np.array([1, 1 if self.n == 3 else 0, 0], np.float32)
        if self.n == 3:
            self.rc.act = 1
        done = self.n >= 5
        return type("R", (), dict(reward_raw=raw_reward(comps, alpha, RewardConfig()), components=comps,
                                  outcome=Outcome.DEATH if done else Outcome.RUNNING,
                                  next_obs=None if done else self.later, final_obs=None, failure_reason=""))()

    def fork(self, search_seed):
        env = _ScriptedEnv(self.first, self.later)
        env.rc.act, env.rc.floor, env.n = self.rc.act, self.rc.floor, self.n
        return env


@pytest.mark.parametrize("card_bootstrap", [False, True])
def test_card_fork_branches_stop_at_the_act_end_with_real_events_only(episodes, card_bootstrap):
    from spire_rl.model import VALUE_SCALE
    from spire_rl.rollout import SCREEN_CARD_REWARD, Collector, Job
    from spire_rl.train import build_critic
    card = _card_reward_observation()
    assert card.phase == 2 * SCREEN_CARD_REWARD and card.num_candidates == 4
    later = next(o for ep in episodes for o in ep.obs if o.phase != card.phase)
    cfg = make_config("tiny", fork={"card_prob": 1.0, "seeds": 2, "card_bootstrap": card_bootstrap})
    torch.manual_seed(0)
    m, c = build_model(cfg, torch.device("cpu")).eval(), build_critic(cfg, torch.device("cpu")).eval()
    with torch.no_grad():
        c.value_head.bias.copy_(torch.tensor([0.1, 0.2, 0.3]))
    col = Collector(cfg, m, torch.device("cpu"), num_envs=1, critic=c)
    col.slots[0].env = _ScriptedEnv(card, later)
    try:
        res = col.collect(iter([Job(0, 1, 1)]), 0, 1.0, None, sample_seed=3, forks=True)
    finally:
        col.close()
    (fork,) = res.episodes[0].info["forks"]
    assert fork.t == 0 and len(fork.options) == 4 and len(fork.details) == 8
    w = np.asarray(value_weights(1.0, cfg.reward))
    for key, d in fork.details.items():
        # 3 decisions: three floors and the act entry; never the run's later floors or death
        assert d["stop_reason"] == "act_change" and d["decisions"] == 3 and d["events"] == [3.0, 1.0, 0.0]
        assert d["bootstrapped"] == card_bootstrap and d["bootstrap_comps"][2] == 0.0
        expected = np.asarray(d["events"]) @ w
        if card_bootstrap:
            assert all(abs(v) > 1e-4 for v in d["bootstrap_comps"][:2])     # floors and acts estimates are used
            expected += (np.asarray(d["bootstrap_comps"]) * VALUE_SCALE) @ w
        assert fork.returns[key] == pytest.approx(expected)
    assert len(res.episodes[0]) == 5 and res.transitions == 5       # the main line is untouched


def _sharpened(model, std=0.5):
    """A fresh policy is near-uniform whatever its inputs; give the heads a visible spread."""
    with torch.no_grad():
        torch.nn.init.normal_(model.policy_query.weight, std=std)
        torch.nn.init.normal_(model.policy_mlp[-1].weight, std=std)
        torch.nn.init.normal_(model.group_mlp[-1].weight, std=std)
    return model


def test_rollout_log_probabilities_recompute_exactly_with_forks():
    """What the update recomputes is what the rollout saved, also with branches in the batches (FP32)."""
    from spire_rl.ppo import prepare
    from spire_rl.train import build_critic
    cfg = _fork_cfg()
    torch.manual_seed(0)
    m = _sharpened(build_model(cfg, torch.device("cpu")), std=2.0).eval()
    c = build_critic(cfg, torch.device("cpu")).eval()
    res = _collect_with_forks(cfg, m, c)
    assert res.stats["forks_complete"] > 0
    targets = prepare(res.episodes, cfg.ppo, cfg.fork.seeds)
    assert np.std([ep.logp[t] for ep, t in targets]) > 0.1            # the policy is not uniform
    exact = recompute_check(m, targets, cfg.model.window, torch.device("cpu"), False, limit=len(targets))
    assert exact < 1e-3                                               # ~1e-5 here; BF16 gave 0.02-0.08
    ep = max((e for e in res.episodes if e.obs[0].num_candidates > 1), key=len)   # sanity: a wrong history shows
    wrong = copy.copy(ep)
    wrong.actions = [(ep.actions[0] + 1) % ep.obs[0].num_candidates] + ep.actions[1:]
    later = [(wrong, t) for t in range(1, min(len(ep), cfg.model.window))]
    wrong_history = recompute_check(m, later, cfg.model.window, torch.device("cpu"), False, limit=len(later))
    assert wrong_history > 100 * max(exact, 1e-6)


def test_heads_run_in_fp32_under_bf16_autocast(episodes):
    """BF16 keeps 8 significant bits; scores rounded to it made saved and recomputed log P differ."""
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(0)
    m = _sharpened(build_model(CFG, dev)).eval()
    seen = {}
    hooks = [layer.register_forward_hook(lambda _m, _i, out, name=name: seen.__setitem__(name, out.dtype))
             for name, layer in (("policy", m.policy_mlp[-1]), ("group", m.group_mlp[-1]),
                                 ("value", m.value_head), ("trunk", m.blocks[0].out))]
    b = collate(targets_of(episodes), WINDOW).to(dev)
    try:
        with torch.no_grad(), torch.autocast(dev.type, dtype=torch.bfloat16):
            out = m(b)
    except RuntimeError as exc:
        if dev.type == "cpu" and "does not support bf16" in str(exc):
            pytest.skip(f"CPU BF16 unsupported here: {exc}")
        raise
    finally:
        for h in hooks:
            h.remove()
    assert seen["trunk"] == torch.bfloat16                           # autocast was really on
    assert seen["policy"] == seen["group"] == seen["value"] == torch.float32
    assert out.logits.dtype == out.value.dtype == out.aux.dtype == out.group_logp.dtype == torch.float32
    with torch.no_grad():
        ref = m(b)
    legal = b.cand_mask
    assert torch.allclose(out.logits[legal], ref.logits[legal], atol=0.2)   # same function as FP32


def test_recompute_limit_depends_on_precision_and_bf16_flag():
    from spire_rl.__main__ import _config
    p = make_config("main").ppo
    assert p.recompute_tolerance == 0.05 and p.recompute_tolerance_bf16 > p.recompute_tolerance
    import argparse
    base = dict(preset="small", episodes=None, num_envs=None)
    assert _config(argparse.Namespace(**base)).ppo.bf16 is False
    assert _config(argparse.Namespace(**base, bf16=True)).ppo.bf16 is True
    assert _config(argparse.Namespace(**{**base, "preset": "main"}, bf16=False)).ppo.bf16 is False


@pytest.mark.parametrize("error", [RuntimeError("log-probability recompute mismatch"), KeyboardInterrupt()])
def test_an_error_or_ctrl_c_still_saves_the_weights(tmp_path, monkeypatch, error):
    """A run that stops on an error keeps what it learned (last.pt), and still reports the error."""
    import json
    from spire_rl import train as train_module
    cfg = make_config("tiny", total_episodes=1000, eval_every=1000, val_seeds=(9_000_000, 2), train_seed_base=3_000_000,
                      combat={"normal_simulations": 4, "boss_simulations": 8}, ppo={"min_transitions": 8})
    real, calls = train_module.recompute_check, []

    def failing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:                     # two updates are done, the third never starts
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(train_module, "recompute_check", failing)
    lines = []
    with pytest.raises(type(error)):
        train_module.train(cfg, tmp_path, torch.device("cpu"), log=lambda *a: lines.append(" ".join(map(str, a))))
    payload = ckpt.load(tmp_path / "last.pt")
    progress = payload["progress"]
    assert progress["updates"] == 2 and progress["final"] is False and type(error).__name__ in progress["stopped"]
    assert progress["next_train_seed"] == 3_000_000 + progress["episodes_started"]
    assert json.loads((tmp_path / "summary.json").read_text())["updates"] == 2
    assert any("saved to" in line for line in lines)
    torch.manual_seed(cfg.seed)                                          # same seed: the starting weights
    initial = build_model(cfg, torch.device("cpu")).state_dict()
    assert any(not torch.equal(payload["model"][k], v) for k, v in initial.items())   # the trained ones


def test_an_error_does_not_overwrite_last_pt_with_broken_weights(tmp_path, monkeypatch):
    from spire_rl import train as train_module
    cfg = make_config("tiny", total_episodes=1000, eval_every=1000, val_seeds=(9_000_000, 2),
                      combat={"normal_simulations": 4, "boss_simulations": 8}, ppo={"min_transitions": 8})
    real, calls = train_module.recompute_check, []

    def failing(model, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            with torch.no_grad():
                next(model.parameters()).fill_(float("nan"))
            raise RuntimeError("diverged")
        return real(model, *args, **kwargs)

    monkeypatch.setattr(train_module, "recompute_check", failing)
    lines = []
    with pytest.raises(RuntimeError, match="diverged"):
        train_module.train(cfg, tmp_path, torch.device("cpu"), log=lambda *a: lines.append(" ".join(map(str, a))))
    payload = ckpt.load(tmp_path / "last.pt")                          # still the one written at validation 0
    assert payload["progress"]["updates"] == 0
    assert all(bool(torch.isfinite(v).all()) for v in payload["model"].values())
    assert any("left as it was" in line for line in lines)


def test_greedy_evaluation_takes_the_most_probable_action(tmp_path, capsys, monkeypatch):
    import json
    from spire_rl.__main__ import main
    from spire_rl.rollout import Collector, Job
    from spire_rl.tools import paired_compare
    from spire_rl.train import evaluate
    cfg = make_config("tiny", val_seeds=(9_000_000, 4), combat={"normal_simulations": 4, "boss_simulations": 8})
    torch.manual_seed(0)
    m = _sharpened(build_model(cfg, torch.device("cpu")), std=2.0).eval()
    col = Collector(cfg, m, torch.device("cpu"), num_envs=2)
    try:
        res = col.collect((Job(i, 9_000_000 + i, 7 + i) for i in range(3)), -1, 0.0, None, sample_seed=1, greedy=True)
    finally:
        col.close()
    tg = [(ep, t) for ep in res.episodes for t in range(len(ep))]
    with torch.no_grad():
        logits = m(collate(tg, cfg.model.window)).logits
    taken = logits.gather(1, torch.tensor([[ep.actions[t]] for ep, t in tg]))[:, 0]
    assert len(tg) >= 3 and bool((taken >= logits.max(-1).values - 1e-4).all())    # ties between equal cards aside
    assert float(logits.exp().max(-1).values.mean()) < 0.99                         # there was something to choose
    # evaluate(): reproducible, labelled, and a different run from the sampled one
    passed, real = [], Collector.collect
    monkeypatch.setattr(Collector, "collect",
                        lambda self, *a, **kw: (passed.append(kw.get("greedy", False)), real(self, *a, **kw))[1])
    g1 = evaluate(m, cfg, torch.device("cpu"), "val", num_envs=3, greedy=True)
    g2 = evaluate(m, cfg, torch.device("cpu"), "val", num_envs=2, greedy=True)
    sampled = evaluate(m, cfg, torch.device("cpu"), "val")
    assert passed == [True, True, False]
    assert g1["per_seed"] == g2["per_seed"] and g1["greedy"] is True and sampled["greedy"] is False
    assert "greedy" in g1["conditions"]["sampling"] and "stochastic" in sampled["conditions"]["sampling"]
    # CLI: eval --greedy --out, then compare against the sampled result of the same seeds
    ckpt.save(tmp_path / "m.pt", cfg, m, {})
    assert main(["eval", "--checkpoint", str(tmp_path / "m.pt"), "--device", "cpu", "--greedy",
                 "--out", str(tmp_path / "greedy.json")]) == 0
    assert main(["eval", "--checkpoint", str(tmp_path / "m.pt"), "--device", "cpu",
                 "--out", str(tmp_path / "sampled.json")]) == 0
    saved = json.loads((tmp_path / "greedy.json").read_text())
    assert saved["greedy"] is True and saved["per_seed"] == g1["per_seed"] and passed[-2:] == [True, False]
    capsys.readouterr()
    assert main(["compare", str(tmp_path / "greedy.json"), str(tmp_path / "sampled.json")]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["a_greedy"] is True and shown["b_greedy"] is False and shown["seeds"] == 4
    assert shown["floor_diff_a_minus_b"] == pytest.approx(g1["floor_mean"] - sampled["floor_mean"])
    assert shown["a_higher_floor"] + shown["b_higher_floor"] + shown["same_floor"] == 4


def test_paired_compare_reports_floor_differences():
    from spire_rl.tools import paired_compare
    a = {"greedy": True, "per_seed": [{"seed": s, "won": False, "floor": f, "act": f // 17, "outcome": "DEATH"}
                                      for s, f in enumerate((10, 20, 30, 40))]}
    b = {"per_seed": [{"seed": s, "won": False, "floor": f, "act": f // 17, "outcome": o}
                      for s, (f, o) in enumerate(((10, "DEATH"), (16, "DEATH"), (34, "TRUNCATED"), (30, "DEATH")))]}
    r = paired_compare(a, b)
    assert r["floor_diff_a_minus_b"] == pytest.approx(2.5) and r["a_floor_mean"] == 25 and r["b_floor_mean"] == 22.5
    d = np.array([0, 4, -4, 10])
    assert r["floor_diff_standard_error"] == pytest.approx(d.std(ddof=1) / 2)
    assert (r["a_higher_floor"], r["b_higher_floor"], r["same_floor"]) == (2, 1, 1)
    assert (r["a_reach_act2"], r["b_reach_act2"], r["a_truncations"], r["b_truncations"]) == (0.75, 0.5, 0, 1)
    assert r["a_greedy"] is True and "b_greedy" not in r
