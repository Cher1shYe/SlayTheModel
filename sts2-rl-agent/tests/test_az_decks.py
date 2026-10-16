from collections import Counter
from dataclasses import replace
import numpy as np
import pytest

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.decks import FACTORIES, deck_tokens
from sts2_env.az.generation import STRATA, generate_recipe, frozen_manifest
from sts2_env.az.scenarios import DeckEntry, make_scenario, validate_manifest
from sts2_env.az.information import BeliefSampler, observe
from sts2_env.az.encoder import encode_information
from sts2_env.az.rewards import V3, terminal_reward
from sts2_env.cards import base as card_base
from sts2_env.search.clone import clone_state


def test_real_decks_and_split_spaces():
    manifest = frozen_manifest()
    validate_manifest(manifest)
    for recipe in manifest:
        world = make_scenario(recipe)
        assert Counter(deck_tokens(recipe.deck)) == Counter(
            c.card_id.name + ("+" if c.upgraded else "") for c in world.hand + world.draw_pile)
    assert len({tuple((e.card_id, e.upgraded, e.count) for e in r.deck) for r in manifest}) > 100
    assert {len(deck_tokens(r.deck)) for r in manifest} >= {8, 10, 12}


@pytest.mark.parametrize("entry", [DeckEntry("ANGER", False, 1), DeckEntry("OFFERING", 1, 1),
                                   DeckEntry("OFFERING", False, 0), DeckEntry("OFFERING", False, True)])
def test_unsupported_decks(entry):
    r = generate_recipe(42, 0, 27)
    with pytest.raises(ValueError):
        replace(r, deck=r.deck + (entry,))


@pytest.mark.parametrize("slot", range(len(STRATA)))
def test_complete_games_particle_reconstruction(slot):
    env = ObservableCombatAdapter(generate_recipe(42, 0, slot), reward_version=V3)
    rng = np.random.default_rng(slot)
    while not env.outcome().done:
        info = env.information
        encoded = encode_information(info)
        assert encoded.numeric.shape == (133,)
        saved = card_base._next_instance_id
        particle = BeliefSampler().sample(info, rng)
        assert card_base._next_instance_id == saved
        assert particle.info == info
        # Couple hypothetical hidden order to reality only in this parity test.
        for attr in ("draw_pile", "discard_pile"):
            pool = list(getattr(particle.world, attr))
            ordered = []
            for card in getattr(env.world, attr):
                match = next(c for c in pool if (c.card_id, c.upgraded) == (card.card_id, card.upgraded))
                ordered.append(match)
                pool.remove(match)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = int(rng.choice(np.flatnonzero(info.legal_mask)))
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
    assert env.outcome().reward == env.information.terminal_value()


def test_reward_v3_boundaries():
    for hp, expected in ((40, -0.2), (20, 0), (0, 0.2)):
        assert terminal_reward("time_limit", 10, 40, hp, 60, V3, enemy_initial_hp=40) == pytest.approx(expected)
    assert terminal_reward("win", 0, 40, 0, 60, V3, enemy_initial_hp=40) == 0.8
    assert terminal_reward("death", 0, 40, 0, 60, V3, enemy_initial_hp=40) == -0.8
    with pytest.raises(ValueError):
        terminal_reward("death", float("nan"), 40, 10, 60, V3, enemy_initial_hp=40)


@pytest.mark.parametrize("name", FACTORIES)
@pytest.mark.parametrize("upgraded", (False, True))
def test_each_card_actual_effect_and_roundtrip(name, upgraded):
    from sts2_env.az.decks import card_token
    from sts2_env.az.information import PublicHistory
    family = "ironclad-burst" if name in ("OFFERING", "BLOODLETTING") else "ironclad-strength"
    slot = 27 if family == "ironclad-burst" else 18
    r = generate_recipe(42, 0, slot)
    counts = Counter({"STRIKE_IRONCLAD": 2, "DEFEND_IRONCLAD": 2, "POMMEL_STRIKE": 1,
                      **({"BLOODLETTING": 1, "OFFERING": 1} if slot == 27 else {"INFLAME": 1})})
    counts[name] = max(1, counts[name])
    r = replace(r, player_hp=80, deck=tuple(DeckEntry(n, upgraded, count) for n, count in sorted(counts.items())))
    env = ObservableCombatAdapter(r, reward_version=V3)
    all_cards = env.world.hand + env.world.draw_pile
    card = next(c for c in all_cards if c.card_id.name == name)
    all_cards.remove(card)
    env.world.hand = [card]
    env.world.draw_pile = all_cards
    env._information = observe(env.world, PublicHistory(), env.limits, 80, V3, r.content_manifest_version,
                               *env.public_initial)
    info = env.information
    particle = BeliefSampler().sample(info, np.random.default_rng(10))
    actions = np.flatnonzero(info.legal_mask)
    action = int(actions[actions != 0][0])
    initial_enemy = env.world.enemies[0].current_hp
    env.step(action)
    after = env.information
    effects = card.effect_vars
    assert after.player_hp == 80 - effects.get("hp_loss", 0)
    assert after.energy == 3 - card.cost + effects.get("energy", 0)
    assert after.enemy_hp == initial_enemy - (card.base_damage or 0)
    assert after.player_block == (card.base_block or 0)
    assert len(after.hand) == effects.get("cards", 0)
    assert after.player_strength == effects.get("strength", 0)
    assert after.vulnerable == effects.get("vulnerable", 0)
    if name == "OFFERING":
        assert after.exhaust == (card_token(card),)
    if name == "INFLAME":
        assert after.history.removed_powers == (card_token(card),)
    assert BeliefSampler().sample(after, np.random.default_rng(11)).info == after
    assert particle.info == info  # advancing reality never changes an existing particle


def test_hidden_information_search_and_branch_isolation():
    from sts2_env.az.network import PolicyValueNetwork
    from sts2_env.az.observable_puct import plan_observable
    from sts2_env.az.self_play import initialize_worker
    initialize_worker()
    env = ObservableCombatAdapter(generate_recipe(42, 0, 29), reward_version=V3)
    info = env.information
    model = PolicyValueNetwork("observable", V3, env.recipe.content_manifest_version)
    altered = clone_state(env.world)
    altered.draw_pile.reverse()
    altered.rng.next_int(0, 10000)
    altered.enemy_ais[altered.enemies[0].combat_id].state_log = None
    other = observe(altered, info.history, info.limits, info.initial_hp, V3, info.content_version,
                    info.known_deck, info.enemy_initial_hp)
    assert other == info
    saved = card_base._next_instance_id
    a = plan_observable(info, model, model_version="new", budget=12, search_seed=8)
    b = plan_observable(other, model, model_version="new", budget=12, search_seed=8)
    assert np.array_equal(a.root_visits, b.root_visits) and a.action == b.action
    assert card_base._next_instance_id == saved and env.information == info
    sibling = BeliefSampler().sample(info, np.random.default_rng(9))
    branch = BeliefSampler().sample(info, np.random.default_rng(9))
    branch.step(a.action)
    assert sibling.info == info


def test_new_replay_parallel_labels_and_learner_resume(tmp_path):
    from sts2_env.az.content import DECK_CONTENT
    from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
    from sts2_env.az.self_play import CollectionJob, Collector, collect_episode, initialize_worker, file_digest
    from sts2_env.az.replay_buffer import ReplayBuffer, episode_digest
    from sts2_env.az.learner import Learner
    from sts2_env.az.coordinator import save_training, restore_training
    initialize_worker()
    model = PolicyValueNetwork("observable", V3, DECK_CONTENT)
    path = tmp_path / "initial.pt"
    save_checkpoint(path, model, "initial", {}, {})
    jobs = [CollectionJob(str(j), 0, 42, generate_recipe(42, 0, j).to_dict(), str(path), file_digest(path),
                          "initial", str(tmp_path / "errors"), 3, EpisodeLimits(8, 100), V3) for j in (9, 18, 27)]
    serial = [collect_episode(job) for job in jobs]
    with Collector(2) as pool:
        parallel = pool.collect(jobs)
    replay = ReplayBuffer(tmp_path / "replay", reward_version=V3, content_version=DECK_CONTENT)
    for a, b in zip(serial, parallel):
        assert a["rows"] and len(a["rows"]) == len(b["rows"])
        for x, y in zip(a["rows"], b["rows"]):
            assert {k: v for k, v in x.items() if k != "search_seconds"} == {k: v for k, v in y.items() if k != "search_seconds"}
        replay.commit(a)
    learner = Learner(model)
    rng = np.random.default_rng(7)
    rows, _ = replay.sample(8, rng)
    history = [learner.update(rows)]
    save_training(tmp_path / "training.pt", learner, rng, replay, "candidate", {}, history, 0)
    restored, restored_rng, _ = restore_training(tmp_path / "training.pt", replay)
    rows, _ = replay.sample(8, rng)
    twin, _ = replay.sample(8, restored_rng)
    assert rows == twin
    assert learner.update(rows) == restored.update(twin)
    with pytest.raises(ValueError):
        ReplayBuffer(tmp_path / "replay")


def test_generator_resume_identity_and_no_split_overlap():
    train = [generate_recipe(seed, it, job) for seed in (42, 43) for it in (0, 1, 49) for job in range(256)]
    heldout = [r for r in frozen_manifest() if r.split != "train"]
    validate_manifest(train + heldout)
    assert generate_recipe(42, 1, 27) == generate_recipe(42, 1, 27)
    assert generate_recipe(42, 0, 27).deck != generate_recipe(42, 1, 27).deck


def test_full_validation_quota_and_default_coordinator_start(tmp_path):
    from sts2_env.az.scenarios import balanced_selection, save_manifest
    from sts2_env.az.coordinator import Coordinator, TrainingConfig
    from sts2_env.az.content import DECK_CONTENT
    recipes = frozen_manifest()
    validation = [r for r in recipes if r.split == "validation"]
    selected = balanced_selection(validation, 256)
    assert len(selected) == 256 and set(r.scenario_id for r in selected) == set(r.scenario_id for r in validation)
    assert len({(r.family_id, r.encounter_id, r.player_hp) for r in selected[:36]}) == 36
    with pytest.raises(ValueError):
        balanced_selection(validation, 257)
    manifest = tmp_path / "manifest.json"
    save_manifest(manifest, recipes)
    for seed in (42, 43):
        c = Coordinator(tmp_path / str(seed), manifest, TrainingConfig(seed=seed, workers=8,
                                                                     reward_version=V3, content_version=DECK_CONTENT))
        try:
            assert len(c.validation) == 256 and c.state["phase"] == "collect"
        finally:
            c.close()


def test_choice_and_unknown_power_are_rejected():
    from sts2_env.core.enums import PowerId
    env = ObservableCombatAdapter(generate_recipe(42, 0, 29), reward_version=V3)
    env.world.request_card_choice(prompt="unsupported", cards=env.world.hand[:2], source_pile="hand", resolver=lambda c: None)
    with pytest.raises(ValueError, match="scope"):
        observe(env.world, env.information.history, env.limits, env.recipe.player_hp, V3,
                env.recipe.content_manifest_version, *env.public_initial)
    env.world.pending_choice = None
    env.world.player.apply_power(PowerId.DEXTERITY, 1)
    with pytest.raises(ValueError, match="powers"):
        observe(env.world, env.information.history, env.limits, env.recipe.player_hp, V3,
                env.recipe.content_manifest_version, *env.public_initial)


def test_coordinator_writer_lock_and_round_manifest_resume(tmp_path):
    from sts2_env.az.content import DECK_CONTENT
    from sts2_env.az.coordinator import Coordinator, TrainingConfig
    from sts2_env.az.scenarios import save_manifest, load_manifest
    from sts2_env.az.self_play import collect_episode
    path = tmp_path / "manifest.json"
    save_manifest(path, frozen_manifest())
    config = TrainingConfig(content_version=DECK_CONTENT, reward_version=V3, workers=1,
                            episodes_per_iteration=2, validation_count=2, iterations=2, updates=1,
                            batch_size=2, simulations=2, eval_simulations=2, max_decisions=2)
    root = tmp_path / "run"
    first = Coordinator(root, path, config)
    try:
        with pytest.raises(RuntimeError, match="coordinator"):
            Coordinator(root)
        class Serial:
            def collect(self, jobs):
                return [collect_episode(job) for job in jobs]
        first.step(Serial())
        saved = load_manifest(root / "manifests" / "train-0.json")
        first.close()
        with pytest.raises(RuntimeError, match="lock"):
            first.step()
        second = Coordinator(root)
        try:
            assert second.state["phase"] == "train"
            assert len(second.replay.committed) == 2
            second.step()
            assert second.state["phase"] == "evaluate"
            assert saved == [generate_recipe(42, 0, j) for j in range(2)]
        finally:
            second.close()
    finally:
        first.close()


def test_v3_terminal_priority_and_search_depth_is_not_timeout():
    from sts2_env.az.observable_puct import plan_observable
    env = ObservableCombatAdapter(generate_recipe(42, 0, 0), limits=EpisodeLimits(max_decisions=1), reward_version=V3)
    env.world.enemies[0].current_hp = 1
    action = int(next(a for a in np.flatnonzero(env.legal_mask()) if 11 <= a < 61))
    assert env.step(action).termination_reason == "win"
    env = ObservableCombatAdapter(generate_recipe(42, 0, 29), reward_version=V3)
    class ConstantValue:
        information_mode = "observable"
        reward_version = V3
        content_version = env.recipe.content_manifest_version
        def predict(self, encoded):
            mask = encoded.legal_mask
            return mask / mask.sum(), 0.37
    result = plan_observable(env.information, ConstantValue(), model_version="constant", budget=4, max_depth=1)
    assert all(edge.q == pytest.approx(0.37) for edge in result.root.edges.values() if edge.visits)
    assert env.information.terminal_value() is None


@pytest.mark.parametrize("network_pass,search_pass", [(True, False), (False, True), (True, True), (False, False)])
def test_v3_promotion_requires_network_only(monkeypatch, network_pass, search_pass):
    from sts2_env.az import evaluation
    monkeypatch.setattr(evaluation, "summarize", lambda rows: {})
    monkeypatch.setattr(evaluation, "stratified_pairs", lambda a, b: {})
    monkeypatch.setattr(evaluation, "promotion_gate", lambda old, new, **kwargs: {"promote": new[0]["pass"]})
    def runner(role, budget):
        return [{"pass": network_pass if budget == 0 else search_pass, "encounter_id": "one"}]
    recipes = [generate_recipe(173, 0, 0, "validation")]
    result = evaluation.compare(None, None, "old", "new", recipes, evaluation_runner=runner, reward_version=V3)
    assert result["promote"] == network_pass
    assert result["modes"]["search"]["gate"]["promote"] == search_pass
    assert result["promotion_policy"] == "network-only-v1"
