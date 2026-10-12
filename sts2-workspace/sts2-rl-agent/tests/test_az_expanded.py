from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.content import EXPANDED_CONTENT, DECK_CONTENT
from sts2_env.az.generation import EXPANDED_STRATA, generate_recipe, frozen_manifest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.rewards import V3
from sts2_env.az.information import BeliefSampler, observe
from sts2_env.az.encoder import encode_information, schema_for
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.self_play import initialize_worker, CollectionJob, collect_episode, Collector, file_digest
from sts2_env.az.replay_buffer import ReplayBuffer
from sts2_env.az.scenarios import balanced_selection, validate_manifest, save_manifest
from sts2_env.search.clone import clone_state
from sts2_env.cards import base as card_base


def recipe(slot, seed=42):
    return generate_recipe(seed, 0, slot, content_version=EXPANDED_CONTENT)


@pytest.mark.parametrize("slot", range(len(EXPANDED_STRATA)))
def test_expanded_complete_game_particle_parity(slot):
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    rng = np.random.default_rng(slot + 500)
    while not env.outcome().done:
        info = env.information
        encoded = encode_information(info)
        assert encoded.numeric.shape == (256,)
        saved = card_base._next_instance_id
        particle = BeliefSampler().sample(info, rng)
        assert particle.info == info and card_base._next_instance_id == saved
        assert particle.world.shuffle_rng is particle.world.monster_ai_rng is particle.world.rng
        for attr in ("draw_pile", "discard_pile"):
            available = list(getattr(particle.world, attr))
            ordered = []
            for c in getattr(env.world, attr):
                twin = next(t for t in available if (t.card_id, t.upgraded) == (c.card_id, c.upgraded))
                available.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert env.information == predicted
    assert env.outcome().reward == env.information.terminal_value()


def test_elite_strength_and_multihit_cycles():
    effigy = ObservableCombatAdapter(recipe(11), reward_version=V3)
    assert effigy.information.enemy_hp == 127
    effigy.step(0)
    assert effigy.information.player_hp == 80
    effigy.step(0)
    assert effigy.information.enemy_strength == 10
    effigy.step(0)
    assert effigy.information.player_hp == 55
    bird = ObservableCombatAdapter(recipe(14), reward_version=V3)
    bird.step(0)
    assert bird.information.player_hp == 64 and bird.information.enemy_strength == 1
    assert bird.information.intent == ("MULTI_ATTACK", 3, 3)
    bird.step(0)
    assert bird.information.player_hp == 52 and bird.information.enemy_strength == 2
    bird.step(0)
    assert bird.information.player_hp == 34 and bird.information.enemy_strength == 3


def test_slow_counter_reconstruction_and_turn_reset():
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.information import PublicHistory
    from sts2_env.core.enums import PowerId
    r = replace(recipe(11), deck=(DeckEntry("DEFEND_IRONCLAD", False, 4), DeckEntry("STRIKE_IRONCLAD", True, 2)))
    env = ObservableCombatAdapter(r, reward_version=V3)
    pool = env.world.hand + env.world.draw_pile
    hand = []
    for name in ("DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"):
        card = next(c for c in pool if c.card_id.name == name)
        pool.remove(card)
        hand.append(card)
    env.world.hand, env.world.draw_pile = hand, pool
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, EXPANDED_CONTENT, *env.public_initial)
    env.step(1)
    env.step(1)
    particle = BeliefSampler().sample(env.information, np.random.default_rng(1))
    assert particle.world.enemies[0].powers[PowerId.SLOW]._slow_amount == 2
    env.step(11)
    assert env.information.enemy_hp == 117  # floor(9 * 1.2)
    env.step(0)
    assert env.world.enemies[0].powers[PowerId.SLOW]._slow_amount == 0
    assert BeliefSampler().sample(env.information, np.random.default_rng(2)).info == env.information


@pytest.mark.parametrize("slot", (17, 20, 104, 125))
def test_expanded_hidden_information_and_search_isolation(slot):
    initialize_worker()
    env = ObservableCombatAdapter(recipe(slot), reward_version=V3)
    model = PolicyValueNetwork("observable", V3, EXPANDED_CONTENT)
    info = env.information
    changed = clone_state(env.world)
    changed.draw_pile.reverse()
    changed.rng.next_int(0, 1000)
    changed.enemy_ais[changed.enemies[0].combat_id].state_log = None
    other = observe(changed, info.history, info.limits, info.initial_hp, V3, EXPANDED_CONTENT, *env.public_initial)
    saved = card_base._next_instance_id
    a = plan_observable(info, model, model_version="hard", budget=12, search_seed=9)
    b = plan_observable(other, model, model_version="hard", budget=12, search_seed=9)
    assert np.array_equal(a.root_visits, b.root_visits) and a.action == b.action
    assert card_base._next_instance_id == saved and env.information == info


def test_expanded_manifests_versions_replay_parallel_and_ten_rounds(tmp_path):
    from sts2_env.az.config import EpisodeLimits
    from sts2_env.az.coordinator import Coordinator, TrainingConfig
    from sts2_env.az.learner import Learner
    records = frozen_manifest(EXPANDED_CONTENT)
    validate_manifest(records)
    old = {r.environment_seed for r in frozen_manifest()}
    assert not old & {r.environment_seed for r in records}
    validation = [r for r in records if r.split == "validation"]
    assert len(balanced_selection(validation, 256)) == 256
    assert len({(r.family_id, r.encounter_id, r.player_hp) for r in validation}) == 126
    test = [r for r in records if r.split == "test"]
    assert len(test) == 150 and len({(r.family_id, r.encounter_id, r.player_hp) for r in test}) == 126
    manifest = tmp_path / "manifest.json"
    save_manifest(manifest, records)
    for seed in (42, 43):
        c = Coordinator(tmp_path / str(seed), manifest, TrainingConfig(seed=seed, iterations=10,
                                                                     reward_version=V3, content_version=EXPANDED_CONTENT))
        assert c.config.iterations == 10
        c.close()
    initialize_worker()
    path = tmp_path / "model.pt"
    model = PolicyValueNetwork("observable", V3, EXPANDED_CONTENT)
    save_checkpoint(path, model, "hard", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, DECK_CONTENT)
    jobs = [CollectionJob(str(slot), 0, 42, recipe(slot).to_dict(), str(path), file_digest(path), "hard",
                          str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for slot in (17, 20, 104, 125)]
    serial = [collect_episode(j) for j in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=EXPANDED_CONTENT)
    for a, b in zip(serial, parallel):
        for x, y in zip(a["rows"], b["rows"]):
            assert {k:v for k,v in x.items() if k != "search_seconds"} == {k:v for k,v in y.items() if k != "search_seconds"}
        replay.commit(a)
    learner = Learner(model)
    samples, _ = replay.sample(8, np.random.default_rng(1))
    assert np.isfinite(learner.update(samples)["loss"])


def arranged(family, names, hand, encounter="setup_mawler_normal", upgraded=False):
    from sts2_env.az.scenarios import DeckEntry
    from sts2_env.az.information import PublicHistory
    r = replace(recipe(20), family_id=family, encounter_id=encounter,
                deck=tuple(DeckEntry(name, upgraded, count) for name, count in names.items()))
    env = ObservableCombatAdapter(r, reward_version=V3)
    pool = env.world.hand + env.world.draw_pile
    env.world.hand = []
    for name in hand:
        card = next(c for c in pool if c.card_id.name == name)
        pool.remove(card)
        env.world.hand.append(card)
    env.world.draw_pile = pool
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, EXPANDED_CONTENT, *env.public_initial)
    return env


def play(env, name):
    from sts2_env.gym_env.action_space import action_to_card_and_target
    action = next(int(a) for a in np.flatnonzero(env.information.legal_mask) if a
                  and env.information.hand[action_to_card_and_target(int(a))[0]].removesuffix("+") == name)
    env.step(action)


@pytest.mark.parametrize("upgraded", (False, True))
def test_block_exhaust_and_strength_synergies(upgraded):
    env = arranged("ironclad-block", dict(BODY_SLAM=1, IRON_WAVE=1, IMPERVIOUS=1, DEFEND_IRONCLAD=3),
                   ["IMPERVIOUS", "BODY_SLAM"], upgraded=upgraded)
    play(env, "IMPERVIOUS")
    play(env, "BODY_SLAM")
    block = 40 if upgraded else 30
    assert env.information.player_block == block and env.information.enemy_hp == 72 - block
    assert len(env.information.exhaust) == 1
    env = arranged("ironclad-exhaust", dict(ASHEN_STRIKE=1, OFFERING=1, IMPERVIOUS=1, DEFEND_IRONCLAD=3),
                   ["IMPERVIOUS", "ASHEN_STRIKE"], upgraded=upgraded)
    play(env, "IMPERVIOUS")
    play(env, "ASHEN_STRIKE")
    assert env.information.enemy_hp == 72 - (10 if upgraded else 9)
    env = arranged("ironclad-strength", dict(INFLAME=1, POMMEL_STRIKE=1, TWIN_STRIKE=1, DEFEND_IRONCLAD=3),
                   ["INFLAME", "TWIN_STRIKE"], upgraded=upgraded)
    play(env, "INFLAME")
    play(env, "TWIN_STRIKE")
    assert env.information.enemy_hp == 72 - (20 if upgraded else 14)


def test_cubex_native_artifact_blocks_debuff_and_strength_cycle():
    env = arranged("ironclad-starter", dict(BASH=2, DEFEND_IRONCLAD=4), ["BASH", "BASH"],
                   encounter="setup_cubex_construct_normal")
    assert env.information.enemy_block == 13 and env.information.enemy_artifact == 1
    play(env, "BASH")
    assert env.information.vulnerable == 0 and env.information.enemy_artifact == 0
    assert BeliefSampler().sample(env.information, np.random.default_rng(6)).info == env.information
    env.step(0)
    assert env.information.enemy_strength == 2 and env.information.player_hp == 80
    env.step(0)
    assert env.information.enemy_strength == 4 and env.information.player_hp == 71
    env.step(0)
    assert env.information.enemy_strength == 6 and env.information.player_hp == 60
    env.step(0)
    assert env.information.player_hp == 38  # (5 + 6) x 2


def test_mawler_future_branching_and_roar_once():
    from sts2_env.az.content import mawler_move
    env = ObservableCombatAdapter(recipe(20), reward_version=V3)
    outcomes = set()
    for seed in range(40):
        particle = BeliefSampler().sample(env.information, np.random.default_rng(seed))
        outcomes.add(mawler_move(particle.step(0).intent))
        while particle.info.terminal_value() is None:
            particle.step(0)
            assert particle.info.history.enemy_moves.count("ROAR_MOVE") <= 1
    assert outcomes == {"ROAR_MOVE", "RIP_AND_TEAR_MOVE"}


def test_new_pool_rejected_by_old_versions_and_seed_spaces_are_distinct():
    from sts2_env.az.content import HARD_CONTENT
    from sts2_env.az.decks import EXPANDED_FACTORIES
    records = frozen_manifest(EXPANDED_CONTENT)
    prior = {r.environment_seed for version in (DECK_CONTENT, HARD_CONTENT) for r in frozen_manifest(version)}
    assert not prior & {r.environment_seed for r in records}
    assert {c.card_id for r in records for c in r.deck} == set(EXPANDED_FACTORIES)
    with pytest.raises(ValueError):
        replace(recipe(104), content_manifest_version=HARD_CONTENT)
    for version, size in ((DECK_CONTENT, 133), (HARD_CONTENT, 145)):
        schema = schema_for("observable", V3, version)
        assert len(schema["card_vocabulary"]) == 17 and schema["shapes"]["numeric"] == [size]
