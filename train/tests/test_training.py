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
    _, parts = r(a, rewards.Progress(49, 60, 80, 0, 4, True, True))
    assert parts["win"] == 1.6 and parts["death"] == 0                                 # DEVLOG 53


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
    last = log[-1]
    assert {"value_ev", "value_ev_full_return", "return_std", "optimizer_steps", "kl_max",
            "value_ev_combat", "value_ev_macro", "macro_share"} <= set(last)                                 # every update
    assert all({"death_floors", "deaths_by_room", "fights"} <= set(x) for x in log if x["games"])          # when games ended
    assert {"collect_simulator", "collect_prepare", "collect_network", "learn_prepare", "learn_network"} <= set(last["timing_s"])
    # LR warm-up counts optimizer steps and carries over a resume (DEVLOG 49)
    first, second = log
    assert second["optimizer_steps_total"] == first["optimizer_steps_total"] + second["optimizer_steps"]
    assert abs(second["lr"] - 3e-5 * second["optimizer_steps_total"] / 100) < 1e-12
    import torch
    ck = torch.load(tmp_path / "run" / "latest.pt", weights_only=False)
    assert ck["optimizer_steps_total"] == second["optimizer_steps_total"]
    del ck["optimizer_steps_total"]                     # a run-2 style checkpoint
    torch.save(ck, tmp_path / "run" / "latest.pt")
    t = ppo.Trainer(ppo.parse(args))
    assert t.opt_steps == second["optimizer_steps_total"]       # recovered from AdamW's step count
    # value normalization (DEVLOG 51): stats logged, saved and restored on resume
    assert second["value_norm"]["on"] and second["value_norm"]["std"] > 0
    assert abs(t.vnorm.mean - second["value_norm"]["mean"]) < 1e-9 and abs(t.vnorm.std - second["value_norm"]["std"]) < 1e-9
    assert abs(t.lr_at(0) - 3e-7) < 1e-15 and t.lr_at(99) == 3e-5 and t.lr_at(10_000) == 3e-5


def _pre_combat(seed=9101, limit=600):
    """A state one action before a combat starts, with that action."""
    rng = random.Random(seed)
    rc = sim.RunContext(); rc.init(seed, 10)
    for _ in range(limit):
        s = p.from_simulator(rc)
        i = rng.randrange(len(s.actions))
        if s.facts["combat"] is None:
            trial = rc.clone()
            handle = tuple(p.candidate_handle(s, i))
            trial.step(*handle)
            if trial.screen == sim.RunScreen.COMBAT:
                return rc.snapshot(), handle, trial
        p.step_simulator(rc, s, i)
    raise AssertionError("no combat")


def test_practice_redeal_keeps_public_setup_and_changes_hidden_order():
    blob, handle, original = _pre_combat()
    hands, orders = set(), set()
    for k in range(12):
        rc = sim.RunContext(); assert rc.restore(blob)
        rc.reseed_combat_streams(1000 + k)
        assert rc.step(*handle) and rc.screen == sim.RunScreen.COMBAT
        assert rc.battle.encounter_id == original.battle.encounter_id and rc.hp == original.hp and rc.floor == original.floor
        assert sorted(rc.battle.draw + [c[0] for c in rc.battle.hand]) == sorted(original.battle.draw + [c[0] for c in original.battle.hand])
        hands.add(tuple(sorted(c[0] for c in rc.battle.hand))); orders.add(tuple(rc.battle.draw))
    assert len(orders) > 1
    again = [sim.RunContext() for _ in range(2)]
    for rc in again:
        rc.restore(blob); rc.reseed_combat_streams(5); rc.step(*handle)
    assert again[0].state_hash() == again[1].state_hash()


def test_practice_game_win_bootstraps_and_loss_scores_death():
    blob, handle, original = _pre_combat()
    pool = rollout.PracticePool(1)
    kind = "boss" if original.combat_is_boss else "elite" if original.combat_is_elite else "normal"
    pool.add(kind, original.battle.encounter_id, blob, handle)
    g = rollout.Game(3, 10, pool=pool, practice=True)
    assert g.mode == "practice"
    rng = random.Random(4); step = g.next_decision(); seen = 0
    for _ in range(4000):
        step = g.act(int(rng.choice(np.flatnonzero(step.allowed))))
        if step.info:
            seen += 1
            assert step.info["mode"] == "practice" and step.info["reason"] in ("practice_win", "died", "stall", "won")
            if step.info["reason"] == "practice_win":
                assert step.boot is not None
            else:
                assert step.boot is None and step.reward < 0
            if seen >= 5:
                break
    assert seen >= 1


def test_practice_pool_weights_and_capacity():
    pool = rollout.PracticePool(1)
    for i in range(300):
        pool.add("normal", 1, b"x", (0, 0))
    assert len(pool.entries["normal"]) == 240
    pool.add("boss", 2, b"x", (0, 0))
    pool.observe(2, True, 1.0); pool.observe(1, False, 0.0)
    assert pool.weight(pool.entries["boss"][0]) == 6.0 * 2.25
    assert pool.weight(pool.entries["normal"][0]) == 0.25


def test_hidden_value_input_never_changes_policy():
    import torch
    from spire_rl import net as N
    _, s = _first("combat")
    torch.manual_seed(0)
    model = N.UnifiedNet(N.UnifiedNetConfig(dim=32, ctx_layers=1, combat_layers=1, heads=2,
                                            observation_schema=p.SCHEMA_ID, value_hidden=True)).eval()
    a, b = N.collate([p.encode(s)]), N.collate([p.encode(s)])
    a.hidden = torch.ones(1, rollout.HIDDEN_CARDS, dtype=torch.long)
    b.hidden = torch.full((1, rollout.HIDDEN_CARDS), 77, dtype=torch.long)
    with torch.no_grad():
        x, y = model(a), model(b)
    assert torch.equal(x["logp"], y["logp"]) and not torch.equal(x["value"], y["value"])


def test_evaluation_is_fixed_and_counts_every_seed(tmp_path):
    import torch
    from spire_rl import evaluate as E, net as N
    torch.manual_seed(0)
    model = N.UnifiedNet(N.UnifiedNetConfig(dim=32, ctx_layers=1, combat_layers=1, heads=2, observation_schema=p.SCHEMA_ID)).eval()
    seeds = list(range(500, 506))
    one = E.play(model, torch.device("cpu"), seeds, 1, 2, 10, infer_batch=8)
    two = E.play(model, torch.device("cpu"), seeds, 2, 3, 10, infer_batch=8)
    assert [r["seed"] for r in one] == seeds
    assert [(r["seed"], r["floor"], r["reason"], r["decisions"]) for r in one] == [(r["seed"], r["floor"], r["reason"], r["decisions"]) for r in two]
    low, high = E.wilson(72, 100)
    assert low < 0.72 < high


def test_practice_start_failure_falls_back_to_full_game():
    pool = rollout.PracticePool(1)
    pool.add("normal", 1, b"not a snapshot", (0, 0))
    g = rollout.Game(3, 10, pool=pool, practice=True)
    assert g.mode == "full" and g.next_decision().obs is not None


def test_minibatches_have_no_tiny_leftover():
    from spire_rl import ppo
    order = np.random.permutation(65568)
    parts = ppo.minibatches(order, 4096)
    assert len(parts) == 16 and min(map(len, parts)) >= 4096
    assert sorted(np.concatenate(parts).tolist()) == list(range(65568))
    micro = ppo.microbatches(parts[0], 256)
    assert max(map(len, micro)) <= 256 and min(map(len, micro)) >= 200
    assert sum(map(len, micro)) == len(parts[0])
    assert [len(x) for x in ppo.minibatches(np.arange(10), 4096)] == [10]


def test_sorted_microbatches_keep_rows_and_gradient(tmp_path):
    """Grouping rows of similar size changes only padding: same rows, same summed gradient."""
    import torch
    from spire_rl import ppo
    lengths = np.array([[90, 0], [120, 30], [85, 12], [130, 40], [88, 5], [100, 20], [95, 0], [110, 25]])
    mb = np.random.permutation(8)
    chunks = ppo.microbatches(mb, 3, lengths)
    assert sorted(np.concatenate(chunks).tolist()) == list(range(8)) and max(map(len, chunks)) <= 3
    assert [lengths[c, 0].max() for c in chunks] == sorted(lengths[c, 0].max() for c in chunks)
    big = np.random.default_rng(3).integers(60, 200, size=(500, 2))
    capped = ppo.microbatches(np.arange(500), 64, big, tokens=3000)
    assert sorted(np.concatenate(capped).tolist()) == list(range(500))
    assert all(len(c) <= 64 and (len(c) == 1 or len(c) * (big[c, 0].max() + big[c, 1].max() + 1) <= 3000) for c in capped)

    games = [rollout.Game(seed, 10) for seed in (11, 12, 13, 14)]
    steps = [g.next_decision() for g in games]
    obs, allowed = [], []
    for _ in range(6):
        obs += [s.obs for s in steps]; allowed += [s.allowed for s in steps]
        steps = [g.act(int(np.flatnonzero(s.allowed)[0])) for g, s in zip(games, steps)]
    m = len(obs)
    rng = np.random.default_rng(0)
    batch = {"obs": obs, "allowed": allowed, "act": np.array([int(np.flatnonzero(a)[0]) for a in allowed]),
             "logp": np.full(m, -1.0, np.float32), "adv": rng.standard_normal(m).astype(np.float32),
             "ret": rng.standard_normal(m).astype(np.float32), "val": np.zeros(m, np.float32)}
    grads = []
    for sort in (False, True):
        args = ppo.parse(["--run", str(tmp_path / f"r{sort}"), "--dim", "32", "--ctx-layers", "1", "--combat-layers", "1",
                          "--heads", "2", "--minibatch", str(m), "--micro", "5", "--epochs", "1", "--device", "cpu"])
        args.sort_micro = sort
        torch.manual_seed(0)
        t = ppo.Trainer(args)
        t.opt.step = lambda: None           # keep the weights; compare the accumulated gradient
        np.random.seed(1)
        st = t.learn(batch)
        grads.append(torch.cat([q.grad.reshape(-1) for q in t.net.parameters() if q.grad is not None]))
        assert st["learn_tokens"]["padded_over_real"] >= 1.0
    assert torch.allclose(grads[0], grads[1], rtol=1e-4, atol=1e-6)


def test_small_layers_stay_fp32_inside_bf16_autocast():
    import torch
    from spire_rl import net as N
    _, s = _first("combat")
    model = N.UnifiedNet(N.UnifiedNetConfig(dim=32, ctx_layers=1, combat_layers=1, heads=2,
                                            observation_schema=p.SCHEMA_ID, value_hidden=True)).eval()
    seen = {}
    names = ("macro_proj", "combat_proj", "cnum_proj", "global_proj", "player_proj", "state_mlp", "cand_mlp",
             "value_head", "hidden_value", "q_head", "aux_head")
    for name in names:
        getattr(model, name).register_forward_hook(lambda m, a, out, name=name: seen.__setitem__(name, out.dtype))
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        out = model(N.collate([p.encode(s)]))
    assert set(seen) == set(names) and all(v == torch.float32 for v in seen.values()), seen
    assert out["value"].dtype == torch.float32 and out["logp"].dtype == torch.float32
    assert torch.isfinite(out["value"]).all()


def test_run_metrics_and_explained_variance():
    from spire_rl import ppo
    base = {"won": False, "elites": 1, "bosses": 0, "floor": 9, "encounter": 3, "death_room": "elite",
            "fought": {"normal": 4, "elite": 2, "boss": 0}}
    won = dict(base, won=True, bosses=3, floor=48, death_room=None, fought={"normal": 9, "elite": 3, "boss": 4})
    event = dict(base, floor=5, death_room="noncombat", encounter=None)
    m = ppo.run_metrics([base, base, won, event])
    assert m["death_floors"] == {"5": 1, "9": 2}
    assert m["deaths_by_room"] == {"elite": 2, "noncombat": 1}
    assert m["fights"]["elite"] == {"entered": 9, "won": 4} and m["fights"]["boss"] == {"entered": 4, "won": 3}
    assert sum(m["deaths_by_encounter"].values()) == 2
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert ppo.explained_variance(y, y) == 1.0 and abs(ppo.explained_variance(y, np.full(4, y.mean()))) < 1e-12


def test_relic_capacity_past_32_keeps_relic_options_open():
    """v28: native has no relic cap. At the old 32-relic cap every relic-granting event option was
    disabled (Hungry for Mushrooms at floor 45 had no legal action, DEVLOG 48)."""
    rc = sim.RunContext(); rc.init(4242, 10)
    rng = random.Random(4242)
    for _ in range(200):                                    # leave Neow
        if rc.screen == sim.RunScreen.MAP:
            break
        s = p.from_simulator(rc)
        p.step_simulator(rc, s, rng.randrange(len(s.actions)))
    plain = [int(v) for k, v in sim.RelicId.__members__.items()
             if k not in ("INVALID",) and sim.relic_info(int(v))[3] == 0 and sim.relic_implemented(int(v))
             and k not in ("HUNGRY_FOR_MUSHROOMS", "BIG_MUSHROOM", "FRAGRANT_MUSHROOM")]
    for rid in plain:
        if len(rc.relics) >= 40:
            break
        try:
            if rc.screen == sim.RunScreen.MAP:
                rc.add_relic(rid)
        except RuntimeError:
            pass
    assert len(rc.relics) >= 40 and rc.screen == sim.RunScreen.MAP
    events = {sim.event_info(i)[0]: i for i in range(sim.event_count())}
    assert rc.begin_event(events["HUNGRY_FOR_MUSHROOMS"])
    s = p.from_simulator(rc)
    options = [a for a in s.actions if a.key.kind == "event_option"]
    assert len(options) == 2, [a.key for a in s.actions]
    p.step_simulator(rc, s, s.actions.index(options[0]))
    assert len(rc.relics) >= 41
    snap = rc.snapshot()
    back = sim.RunContext(); assert back.restore(snap) and len(back.relics) == len(rc.relics)


def test_value_norm_tracks_targets_and_round_trips():
    from spire_rl import ppo
    vn = ppo.ValueNorm(beta=0.5)
    x = np.array([0.5, -0.2])
    assert np.allclose(vn.denormalize(x), x) and vn.mean == 0.0 and vn.std == 1.0    # identity before data
    rng = np.random.default_rng(0)
    for _ in range(40):
        vn.update(rng.normal(-0.12, 0.03, 4096))
    assert abs(vn.mean + 0.12) < 0.005 and abs(vn.std - 0.03) < 0.005
    assert np.allclose(vn.denormalize(vn.normalize(x)), x)
    vn2 = ppo.ValueNorm(); vn2.load_state_dict(vn.state_dict())
    assert vn2.mean == vn.mean and vn2.std == vn.std
    const = ppo.ValueNorm(); const.update(np.zeros(10))
    assert const.std == const.min_std                                           # no division by zero


def test_two_level_gae_matches_hand_computation():
    """DEVLOG 52: macro decision -> 2-decision fight on the next floor -> macro decision -> game over."""
    from spire_rl import ppo
    g, lc, lm = 0.9, 0.5, 0.8
    r = np.array([[0.01], [-0.01], [0.0], [0.02]], np.float32)
    V = np.array([[0.3], [0.2], [0.25], [0.1]], np.float32)
    done = np.array([[False], [False], [False], [True]])
    combat = np.array([[False], [True], [True], [False]])
    floor = np.array([[1], [2], [2], [2]]); fight = np.array([[0], [1], [1], [1]])
    adv, ret, mc = ppo.two_level_gae(r, done, V, combat, floor, fight, np.array([0.7]), np.array([False]),
                                     np.array([1]), np.array([0]), g, lc, lm)
    r0, r1, r2, r3 = r[:, 0]; V0, V1, V2, V3 = V[:, 0]
    A3 = r3 - V3                                     # terminal
    A2 = r2 + V3 - V2                                # last fight decision bootstraps on the post-fight state
    A1 = (r1 + V2 - V1) + lc * A2                    # same fight: lambda per decision, no discount
    A0 = r0 + g * (r1 + r2 + V3) + g * lm * A3 - V0  # the whole fight is one transition one floor later
    assert np.allclose(adv[:, 0], [A0, A1, A2, A3], atol=1e-6)
    assert np.allclose(ret, adv + V)
    assert np.allclose(mc[:, 0], [r0 + g * (r1 + r2 + r3), r1 + r2 + r3, r2 + r3, r3], atol=1e-6)


def test_two_level_gae_truncation_and_game_boundary():
    from spire_rl import ppo
    # slot 0: game ends after t0 (macro), new game's macro at t1, truncated after t1 (next is a fight)
    # slot 1: combat at t0 and t1 of the same fight, truncated mid-fight
    r = np.array([[-0.1, 0.0], [0.01, -0.02]], np.float32)
    V = np.array([[0.2, 0.4], [0.5, 0.3]], np.float32)
    done = np.array([[True, False], [False, False]])
    combat = np.array([[False, True], [False, True]])
    floor = np.array([[5, 3], [1, 3]]); fight = np.array([[2, 1], [0, 1]])
    last_val = np.array([0.6, 0.35]); last_combat = np.array([True, True])
    last_floor = np.array([2, 3]); last_fight = np.array([1, 1])
    adv, _, _ = ppo.two_level_gae(r, done, V, combat, floor, fight, last_val, last_combat, last_floor, last_fight,
                                  0.9, 0.5, 0.8)
    assert np.isclose(adv[0, 0], -0.1 - 0.2)                         # no bootstrap across games
    assert np.isclose(adv[1, 0], 0.01 + 0.9 * 0.6 - 0.5)            # truncation: bootstrap, one floor later
    a1 = -0.02 + 0.35 - 0.3                                          # truncated mid-fight: bootstrap only
    assert np.isclose(adv[1, 1], a1) and np.isclose(adv[0, 1], (0.0 + 0.3 - 0.4) + 0.5 * a1)


def test_advantages_normalized_per_level():
    from spire_rl import ppo
    adv = np.array([1.0, 2.0, 3.0, 100.0, 300.0], np.float32)
    groups = np.array([True, True, True, False, False])
    out = ppo.normalize_by_group(adv, groups)
    assert np.allclose(out[:3].mean(), 0, atol=1e-6) and np.allclose(out[3:].mean(), 0, atol=1e-6)
    assert np.isclose(out[:3].std(), 1, atol=1e-3) and np.isclose(out[3:].std(), 1, atol=1e-3)


def test_flat_credit_mode_still_runs(tmp_path):
    """--credit flat keeps the run-1/2 per-decision GAE for A/B comparisons (DEVLOG 52)."""
    from spire_rl import ppo
    ppo.main(["--run", str(tmp_path / "flat"), "--dim", "32", "--ctx-layers", "1", "--combat-layers", "1", "--heads", "2",
              "--workers", "1", "--games", "4", "--samples", "64", "--minibatch", "32", "--micro", "16",
              "--infer-batch", "16", "--device", "cpu", "--credit", "flat", "--max-updates", "1"])
    log = [json.loads(x) for x in (tmp_path / "flat" / "log.jsonl").read_text().splitlines()]
    assert len(log) == 1 and log[0]["policy_loss"] is not None


def test_size_and_machine_presets():
    """docs/runbook.md: --size fixes the network and LR; --machine only speed/memory; explicit flags win."""
    from spire_rl import ppo
    a = ppo.parse(["--run", "x", "--size", "small", "--machine", "5090"])
    assert (a.dim, a.ctx_layers, a.combat_layers, a.heads, a.lr) == (384, 6, 6, 6, 6e-5)
    assert (a.workers, a.games, a.micro, a.micro_tokens) == (6, 16, 128, 16000)
    b = ppo.parse(["--run", "x", "--size", "large", "--machine", "a100", "--micro", "64", "--lr", "1e-5"])
    assert (b.dim, b.micro, b.micro_tokens, b.lr) == (768, 64, 32000, 1e-5)
    c = ppo.parse(["--run", "x"])                    # no preset: the run 1-3 defaults
    assert (c.dim, c.ctx_layers, c.micro, c.micro_tokens, c.lr) == (768, 12, 256, 0, 3e-5)
    assert ppo.SIZES["large"] == {k: getattr(c, k) for k in ppo.SIZES["large"]}
