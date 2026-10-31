from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest
import torch

from agent.card_train import collect_episode
from agent.common import (
    ACTION_FEAT_DIM,
    CARD_FEAT_DIM,
    COMBAT_OBS_DIM,
    PUBLIC_COMBAT_OBS_DIM,
    PUBLIC_OBS_DIM,
    RACT,
    RUN_OBS_DIM,
    SCREEN,
    card_grid_action,
    combat_action_arrays,
    combat_observation,
    new_run,
    run_observation,
    sim,
)
from agent.heuristics import combat_policy, run_policy
from agent.nets import CardScorer, CombatNet
from agent.run_env import RunEnv, play_and_log, play_run
from agent.selfplay import play_episode, train_batch

MAP_POINT = sim.MapPointType


def _move_to_first_node(rc):
    nodes = rc.available_map_nodes()
    assert nodes
    assert rc.step(int(RACT.MOVE), int(nodes[0]))


def test_observation_dims():
    env = RunEnv(1)
    rc = env.rc
    assert rc.screen == SCREEN.EVENT and rc.event_name == "NEOW"
    assert run_observation(rc).shape == (RUN_OBS_DIM,)
    assert env.observe_public().shape == (PUBLIC_OBS_DIM,)
    assert np.isfinite(env.observe_public()).all()
    assert int(sim.PUBLIC_OBS_VERSION) >= 2 and int(sim.ACTION_SCHEMA_VERSION) >= 2
    assert rc.step(int(RACT.EVENT_CHOICE), 0)
    for _ in range(100):
        if rc.screen == SCREEN.MAP:
            break
        assert rc.step(*run_policy(rc))
    assert rc.screen == SCREEN.MAP
    _move_to_first_node(rc)
    assert rc.screen == SCREEN.COMBAT
    bc = rc.battle
    assert combat_observation(bc).shape == (COMBAT_OBS_DIM,)
    assert env.observe_public_combat().shape == (PUBLIC_COMBAT_OBS_DIM,)
    # The in-combat public observation must change when a card is played.
    before = env.observe_public()
    play = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.PLAY_CARD)]
    if play:
        assert rc.step_combat(*play[0])
        assert not np.array_equal(before, env.observe_public())
    actions, feats = combat_action_arrays(bc)
    assert actions and feats.shape == (len(actions), ACTION_FEAT_DIM)
    cand = np.asarray([sim.card_features(1, False, -1)], dtype=np.float32)
    assert cand.shape == (1, CARD_FEAT_DIM)


def test_run_start_state():
    rc = new_run(5)
    assert rc.act == 0 and rc.floor == 1
    assert rc.hp == 80 and rc.max_hp == 80 and rc.gold == 99
    assert rc.deck_count == 10
    assert rc.relics == [int(sim.RelicId.BURNING_BLOOD)]
    assert rc.map_rooms == 15 and rc.map_length == 16
    assert rc.event_name == "NEOW"
    assert len(rc.event_relics) == 3
    choice = rc.event_relics[0]
    assert rc.step(int(RACT.EVENT_CHOICE), 0)
    assert choice in rc.relics
    assert rc.screen == SCREEN.MAP
    # Path pruning may drop redundant starting paths, so 1..7 remain.
    assert 1 <= len(rc.available_map_nodes()) <= 7


def test_action_mask_consistency():
    env = RunEnv(7)
    legal = env.legal_actions()
    mask = env.action_mask()
    assert legal and len(mask) == len(legal)
    assert all(mask)
    before = env.state_hash()
    unavailable = [n for n in range(sim.MAP_MAX_POINTS)
                   if n not in env.rc.available_map_nodes()]
    assert unavailable
    assert not env.step((int(RACT.MOVE), unavailable[0]))
    assert not env.step((int(RACT.TAKE_CARD), 0))
    assert env.state_hash() == before


def test_map_generation_properties():
    expected_rooms = {0: 15, 1: 14, 2: 13}
    for act, rooms in expected_rooms.items():
        for seed in range(1, 31):
            n_rooms, length, nodes = sim.generate_map(seed, act)
            assert n_rooms == rooms and length == rooms + 1
            types = {idx: t for idx, t, _c, _r, _k, _p in nodes}
            rows = {idx: r for idx, _t, _c, r, _k, _p in nodes}
            cols = {idx: c for idx, _t, c, _r, _k, _p in nodes}
            kids = {idx: list(k) for idx, _t, _c, _r, k, _p in nodes}
            pars = {idx: list(p) for idx, _t, _c, _r, _k, p in nodes}
            boss = [i for i, t in types.items() if t == int(MAP_POINT.BOSS)]
            ancient = [i for i, t in types.items() if t == int(MAP_POINT.ANCIENT)]
            assert len(boss) == 1 and len(ancient) == 1
            assert rows[boss[0]] == length and cols[boss[0]] == 3
            assert rows[ancient[0]] == 0 and cols[ancient[0]] == 3
            # Path pruning may remove redundant starting paths.
            first = [i for i, r in rows.items() if r == 1]
            assert 1 <= len(first) <= 7
            assert set(kids[ancient[0]]) == set(first)
            assert all(types[i] == int(MAP_POINT.MONSTER) for i in first)
            # Last row before the boss is always a rest site.
            last = [i for i, r in rows.items() if r == length - 1]
            assert last and all(types[i] == int(MAP_POINT.REST) for i in last)
            # DAG: edges always move down, everyone except start/boss connects.
            for idx, row in rows.items():
                for kid in kids[idx]:
                    assert rows[kid] > row
                    assert idx in pars[kid]
                if idx not in ancient:
                    assert pars[idx]
                if idx not in boss:
                    assert kids[idx]
            # Room type counts.
            count = {}
            for t in types.values():
                count[t] = count.get(t, 0) + 1
            assert 2 <= count[int(MAP_POINT.SHOP)] <= 3
            assert 3 <= count[int(MAP_POINT.ELITE)] <= 5
            assert count[int(MAP_POINT.TREASURE)] >= 1
            assert all(idx in rows for idx in kids[ancient[0]])


def test_map_golden_hashes():
    expected = {
        (1, 0): "562244a8187e789d",
        (1, 1): "a0a6b93497eb8f3f",
        (1, 2): "65267800087951dc",
        (2, 0): "2eacc09fbd60a898",
        (2, 1): "63958bbeb925366c",
        (2, 2): "eceb0b301a8ee82f",
        (3, 0): "569efc5a390b3af3",
        (3, 1): "530c9fc30b431f43",
        (3, 2): "e699f2f93236f858",
    }
    for (seed, act), digest in expected.items():
        rooms, length, nodes = sim.generate_map(seed, act)
        canon = (rooms, length, [(i, t, c, r, tuple(k), tuple(p))
                                 for i, t, c, r, k, p in nodes])
        got = hashlib.sha256(repr(canon).encode()).hexdigest()[:16]
        assert got == digest, (seed, act)
    # Same seed is stable, adjacent seeds differ.
    assert sim.generate_map(9, 0) == sim.generate_map(9, 0)
    assert sim.generate_map(9, 0) != sim.generate_map(10, 0)


def _node_type_map(rc):
    return {idx: int(t) for idx, t, _c, _r, _k, _p in rc.map_nodes()}


def _open_treasure(env):
    rc = env.rc
    gold, relics = rc.gold, len(rc.relics)
    assert rc.screen == SCREEN.TREASURE
    assert env.step((int(RACT.COLLECT), 0))
    assert rc.screen == SCREEN.REWARDS
    if int(sim.RelicId.ECTOPLASM) not in rc.relics:
        assert rc.gold >= gold + 42
    assert len(rc.relics) == relics
    choices = [a for a in env.legal_actions() if a[0] == int(RACT.TAKE_RELIC_REWARD)]
    if choices:
        assert env.step(choices[0])
        assert len(rc.relics) == relics + 1
    assert env.step((int(RACT.LEAVE_REWARDS), 0))
    assert rc.screen == SCREEN.MAP


def test_room_transitions_and_economy():
    seen = set()
    treasure_rewarded = False
    for seed in range(1, 41):
        env = RunEnv(seed)
        steps = 0
        while not env.is_terminal() and steps < 20000:
            steps += 1
            rc = env.rc
            screen = rc.screen
            seen.add(int(screen))
            if screen == SCREEN.MAP:
                node_types = _node_type_map(rc)
                treasures = [n for n in rc.available_map_nodes()
                             if node_types.get(n) == int(MAP_POINT.TREASURE)]
                if treasures:
                    gold = rc.gold
                    assert env.step((int(RACT.MOVE), treasures[0]))
                    if rc.screen == SCREEN.TREASURE:
                        assert rc.gold == gold
                        seen.add(int(SCREEN.TREASURE))
                        seen.add(int(SCREEN.REWARDS))
                        _open_treasure(env)
                        treasure_rewarded = True
                    continue
            if screen == SCREEN.SHOP:
                assert 1 <= len(rc.shop) <= 7
                assert len(rc.shop_relics) <= 3
                assert len(rc.shop_potions) <= 3
                assert all(p > 0 for _c, p, _sold in rc.shop)
                assert all(p > 0 for _r, p, _sold in rc.shop_relics)
                assert all(p > 0 for _p, p, _sold in rc.shop_potions)
            elif screen == SCREEN.REST:
                heal = [a for a in env.legal_actions() if a[0] == int(RACT.REST_HEAL)]
                assert heal
            elif screen == SCREEN.TREASURE:
                _open_treasure(env)
                treasure_rewarded = True
                continue
            elif screen == SCREEN.CARD_REWARD:
                assert 0 <= len(rc.offered) <= 3
            elif screen == SCREEN.EVENT:
                assert rc.event_name
                assert 1 <= rc.event_choices <= 4
            action = (combat_policy(env) if screen == SCREEN.COMBAT
                      else run_policy(env))
            assert env.step(action)
        assert env.is_terminal()
    assert {int(SCREEN.MAP), int(SCREEN.COMBAT), int(SCREEN.CARD_REWARD),
            int(SCREEN.REST), int(SCREEN.SHOP), int(SCREEN.EVENT),
            int(SCREEN.TREASURE), int(SCREEN.REWARDS)} <= seen
    assert treasure_rewarded


def test_rest_upgrade_and_shop_purchase():
    upgraded = False
    bought = False
    for seed in range(1, 41):
        env = RunEnv(seed)
        steps = 0
        while not env.is_terminal() and steps < 20000:
            steps += 1
            rc = env.rc
            screen = rc.screen
            if screen == SCREEN.REST:
                ups = [a for a in env.legal_actions() if a[0] == int(RACT.REST_UPGRADE)]
                if ups:
                    idx = ups[0][1]
                    before = rc.deck[idx][1]
                    assert not before
                    assert env.step(ups[0])
                    assert rc.deck[idx][1]
                    upgraded = True
                    continue
            if screen == SCREEN.SHOP:
                buys = [a for a in env.legal_actions() if a[0] == int(RACT.BUY_CARD)]
                if buys and rc.gold >= rc.shop[buys[0][1]][1]:
                    gold = rc.gold
                    deck = rc.deck_count
                    assert env.step(buys[0])
                    assert rc.gold < gold and rc.deck_count == deck + 1
                    bought = True
                    continue
            action = (combat_policy(env) if screen == SCREEN.COMBAT
                      else run_policy(env))
            if not env.step(action):
                break
        if upgraded and bought:
            return
    raise AssertionError(f"rest upgrade={upgraded} shop purchase={bought}")


def test_full_runs_terminate_with_consistent_outcomes():
    for seed in (273, 443):
        result = play_run(RunEnv(seed), run_policy, combat_policy)
        assert result["status"] == "terminated", result
        assert result["steps"] > 0
        if result["won"]:
            assert result["act"] == 2 and result["bosses"] >= 3
            assert result["floor"] >= 46
        else:
            assert result["hp"] == 0


def test_deterministic_replay():
    env = RunEnv(26)
    actions, hashes = [], []
    for _ in range(400):
        if env.is_terminal():
            break
        action = (combat_policy(env) if env.screen == SCREEN.COMBAT
                  else run_policy(env))
        actions.append(tuple(int(x) for x in action))
        assert env.step(action)
        hashes.append(env.state_hash())
    assert len(actions) == len(hashes) and len(actions) > 50
    replay = RunEnv(26)
    for action, expected in zip(actions, hashes):
        assert replay.step(action)
        assert replay.state_hash() == expected


def test_snapshot_restore_replays_identically():
    env = RunEnv(32)
    for _ in range(250):
        if env.is_terminal():
            break
        action = (combat_policy(env) if env.screen == SCREEN.COMBAT
                  else run_policy(env))
        assert env.step(action)
    if env.is_terminal():
        pytest.skip("seed finished before the snapshot point")
    blob = env.snapshot()
    first_hash = env.state_hash()
    hashes = []
    for _ in range(250):
        if env.is_terminal():
            break
        action = (combat_policy(env) if env.screen == SCREEN.COMBAT
                  else run_policy(env))
        assert env.step(action)
        hashes.append(env.state_hash())
    env.restore(blob)
    assert env.state_hash() == first_hash
    for expected in hashes:
        action = (combat_policy(env) if env.screen == SCREEN.COMBAT
                  else run_policy(env))
        assert env.step(action)
        assert env.state_hash() == expected


def test_snapshot_blob_is_deterministic():
    a, b = RunEnv(3), RunEnv(3)
    assert a.snapshot() == b.snapshot()
    assert a.state_hash() == b.state_hash()
    assert a.snapshot() != RunEnv(4).snapshot()


def test_event_manifest_gating():
    pools = {}
    for act in range(3):
        pools[act] = set(sim.event_pool(act))
        for event_id in pools[act]:
            _name, status, event_act = sim.event_info(event_id)
            assert status != 2, (event_id, _name)
            assert event_act in (-1, act)
    assert sim.event_ancient(0) >= 0
    assert sim.event_info(sim.event_ancient(0))[0] == "NEOW"
    implemented = set()
    for event_id in range(sim.event_count()):
        name, status, event_act = sim.event_info(event_id)
        assert name and status in (0, 1, 2)
        if status == 2:
            assert all(event_id not in pool for pool in pools.values())
        elif event_act != 3:
            assert any(event_id in pool for pool in pools.values()), name
            implemented.add(event_id)
    assert implemented


def test_greedy_runs_finish():
    for seed in range(10):
        rc = new_run(seed + 1)
        guard = 0
        while rc.screen != SCREEN.RUN_OVER and guard < 20000:
            guard += 1
            if rc.screen == SCREEN.COMBAT:
                assert rc.step_combat(*rc.battle.greedy_action(0.05, seed + 1))
            else:
                legal = rc.legal_actions()
                assert legal
                action = card_grid_action(rc) if rc.card_grid_kind else legal[0]
                assert rc.step(*action)
        assert rc.screen == SCREEN.RUN_OVER


def test_every_card_is_playable():
    count = sim.card_count()
    for cid in range(1, count):
        bc = sim.BattleContext()
        bc.init(sim.Encounter.SETUP_SHRINKER_BEETLE_WEAK, 1234, [cid] * 5, [False] * 5, 0)
        for _ in range(80):
            if bc.outcome != sim.Outcome.UNDECIDED:
                break
            assert bc.step(*bc.greedy_action(0.1, 7))


def test_every_potion_is_usable():
    for name in sim.PotionId.__members__:
        if name == "INVALID":
            continue
        pid = int(getattr(sim.PotionId, name))
        bc = sim.BattleContext()
        bc.init(sim.Encounter.SETUP_SHRINKER_BEETLE_WEAK, 1234, [73] * 7, [False] * 7, 0)
        bc.add_potion(pid)
        actions = [a for a in bc.legal_actions() if a[0] == int(sim.ActionType.USE_POTION)]
        if not actions:
            assert sim.potion_def(pid)[3] == 2  # AUTOMATIC potions have no action
            continue
        assert bc.step(*actions[0])
        guard = 0
        while bc.pending_options and guard < 20:
            guard += 1
            bc.step(*bc.legal_actions()[0])
        if name != "EntropicBrew":
            assert bc.potions == [], name


def test_every_implemented_relic_survives_a_combat():
    deck = [73, 73, 73, 73, 25, 25, 25, 25, 6, 2]
    for name in sim.RelicId.__members__:
        if name == "INVALID":
            continue
        rid = int(getattr(sim.RelicId, name))
        if not sim.relic_implemented(rid):
            continue
        bc = sim.BattleContext()
        bc.init(sim.Encounter.SETUP_SHRINKER_BEETLE_WEAK, 1234, deck, [False] * len(deck), 0,
                80, 80, [rid], [])
        guard = 0
        while bc.outcome == sim.Outcome.UNDECIDED and guard < 300:
            guard += 1
            assert bc.step(*bc.greedy_action(0.1, guard))
        assert guard < 300, name


def test_every_event_relic_is_obtainable():
    checked = 0
    for name in sim.RelicId.__members__:
        if name == "INVALID":
            continue
        rid = int(getattr(sim.RelicId, name))
        key, _display, _rarity, pool = sim.relic_info(rid)
        if pool != 2:  # RelicPool::EVENT
            continue
        checked += 1
        assert sim.relic_implemented(rid), name
        rc = new_run(7)
        assert rc.add_relic(rid), name
        assert rid in rc.relics, name
        assert 1 <= rc.hp <= rc.max_hp, name
    assert checked == 132


def test_run_starting_relic_and_rewards():
    rc = new_run(3)
    assert sim.relic_implemented(int(sim.RelicId.BURNING_BLOOD))
    assert rc.relics == [int(sim.RelicId.BURNING_BLOOD)]
    assert rc.potion_slots == 3
    rc.add_relic(int(sim.RelicId.STRAWBERRY))
    assert rc.max_hp == 87
    rc.add_potion(int(sim.PotionId.FruitJuice))
    use = [a for a in rc.legal_actions() if a[0] == int(RACT.USE_POTION)]
    assert len(use) == 1 and rc.step(*use[0])
    assert rc.max_hp == 92 and rc.potions == []


def test_jsonl_trajectory_and_batch(tmp_path):
    path = tmp_path / "traj.jsonl"
    result = play_and_log(273, run_policy, combat_policy, path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert result["status"] == "terminated"
    assert rows[-1]["result"] == result
    assert len(rows) == result["steps"] + 1
    for i, row in enumerate(rows[:-1], 1):
        assert row["step"] == i and row["seed"] == 273
        assert row["obs_version"] == int(sim.PUBLIC_OBS_VERSION)
        assert len(row["obs"]) == PUBLIC_OBS_DIM
        assert len(row["action"]) == (4 if row["screen"] == "COMBAT" else 2)
    env_a, env_b = RunEnv(26), RunEnv(27)
    assert env_a.state_hash() != env_b.state_hash()


def test_card_model_trains_one_episode():
    torch.set_num_threads(1)
    model = CardScorer()
    episode = collect_episode(123, model)
    assert isinstance(episode["return"], float)
    if episode["records"]:
        rec = episode["records"][0]
        logits = model(torch.from_numpy(rec["obs"])[None], torch.from_numpy(rec["cand"])[None])
        assert logits.shape[0] == 1
        loss = -torch.log_softmax(logits, dim=-1)[0, rec["choice"]]
        loss.backward()
        assert any(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


def test_selfplay_episode_and_update():
    torch.set_num_threads(1)
    model = CombatNet()
    episode = play_episode(7, model, simulations=4, sample=False)
    assert episode["records"] or episode["won"] is not None
    if episode["records"]:
        stats = train_batch(model, torch.optim.SGD(model.parameters(), lr=1e-1),
                            episode["records"], epochs=1)
        assert np.isfinite(stats["loss"])
