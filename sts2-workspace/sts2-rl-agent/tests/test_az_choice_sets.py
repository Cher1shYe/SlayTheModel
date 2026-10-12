"""Final-set semantics, historical cycle reproduction, and v2 end-to-end parity."""
from dataclasses import replace
from math import comb
import json
from pathlib import Path

import numpy as np
import pytest
import tests.test_az_selection as previous

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.choice_sets import set_mask, resolve_choice
from sts2_env.az.content import SEL_CONTENT, SET_CONTENT
from sts2_env.az.encoder import schema_for, encode_information
from sts2_env.az.generation import generate_recipe, frozen_manifest, generator_config
from sts2_env.az.information import observe
from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.rewards import V3
from sts2_env.search.clone import clone_state


@pytest.fixture
def v2(monkeypatch):
    monkeypatch.setattr(previous, "SEL_CONTENT", SET_CONTENT)


@pytest.mark.parametrize("n", range(1, 10))
@pytest.mark.parametrize("cap", [3, 5])
def test_all_sets_bijective_and_bounded(n, cap):
    mask = set_mask(n, 0, cap, True)
    legal = np.flatnonzero(mask)
    assert len(mask) == 512
    assert len(legal) == sum(comb(n, k) for k in range(min(n, cap) + 1))
    assert len({tuple(i for i in range(n) if a & (1 << i)) for a in legal}) == len(legal)
    assert not any(mask[1 << n:])
    with pytest.raises(ValueError):
        set_mask(10, 0, cap, True)


@pytest.mark.parametrize("upgraded", [False, True])
def test_every_full_hand_subset_matches_native_and_particle(v2, upgraded):
    hand = ["PURITY+" if upgraded else "PURITY", *["STRIKE_IRONCLAD"] * 5, *["DEFEND_IRONCLAD"] * 4]
    env = previous.arranged(hand=hand, discard=[], draw=[])
    previous.play(env, hand[0])
    info = env.information
    assert len(info.choice.options) == 9 and len(info.legal_mask) == 512
    from sts2_env.az.information import BeliefSampler
    from sts2_env.az.decks import card_token
    for action in np.flatnonzero(info.legal_mask):
        action = int(action)
        particle = BeliefSampler().sample(info, np.random.default_rng(0))
        native = clone_state(env.world)
        selected = [i for i in range(9) if action & (1 << i)]
        for i in selected:
            assert native.resolve_pending_choice(i)
        assert native.resolve_pending_choice(None)
        after = particle.step(action)
        assert after.choice is None and not particle.world.play_pile
        assert after.history.decisions == info.history.decisions + 1
        for pile in ("hand", "discard_pile", "exhaust_pile"):
            assert list(map(card_token, getattr(native, pile))) == list(map(card_token, getattr(particle.world, pile)))
        assert after.energy == info.energy and after.history.payments == info.history.payments


def test_preselected_snapshot_reconciles_remove_before_add(v2):
    env = previous.arranged(hand=["PURITY", "BASH", "ANGER", "STOMP", "DEFEND_IRONCLAD"], discard=[], draw=[])
    previous.play(env, "PURITY")
    for i in (0, 1, 2):
        assert env.world.resolve_pending_choice(i)
    env._information = observe(env.world, env.information.history, env.limits, 80, V3, SET_CONTENT, *env.public_initial)
    previous.matched_step(env, 0b1110)
    assert env.information.choice is None and env.information.hand == ("BASH",)


def test_existing_validation_cycle_now_finishes_in_one_decision():
    diagnostic = json.loads(Path("docs/az_selection_timeout_diagnostic.json").read_text())
    old = generate_recipe(181, 0, 102, "validation", SEL_CONTENT)
    env = ObservableCombatAdapter(replace(old, content_manifest_version=SET_CONTENT), reward_version=V3)
    for entry in diagnostic["trace"]:
        if entry["phase"] != "normal":
            break
        env.step(entry["action"])
    assert env.information.pending_card.token.removesuffix("+") == "PURITY"
    step = env.information.history.decisions
    # The old repeated action 1 now means the completed singleton {candidate 0}.
    previous.matched_step(env, 1)
    assert env.information.choice is None and env.information.history.decisions == step + 1
    assert not env.outcome().done


def test_search_can_only_return_completed_sets_and_hidden_state_invariant(v2):
    previous.initialize_worker()
    env = previous.arranged(hand=["PURITY+", "BASH", "ANGER", "STOMP", "DEFEND_IRONCLAD"], discard=[], draw=[])
    previous.play(env, "PURITY+")
    model = PolicyValueNetwork("observable", V3, SET_CONTENT)
    first = plan_observable(env.information, model, model_version="test", budget=8, search_seed=13)
    env.world.draw_pile.reverse()
    assert env.world.pending_choice is not None
    env.world.pending_choice.resolver = lambda _: (_ for _ in ()).throw(RuntimeError("private callback"))
    second = plan_observable(env.information, model, model_version="test", budget=8, search_seed=13)
    np.testing.assert_array_equal(first.root_visits, second.root_visits)
    from sts2_env.az.information import BeliefSampler
    for action in np.flatnonzero(first.root_visits):
        p = BeliefSampler().sample(env.information, np.random.default_rng(7))
        assert p.step(int(action)).choice is None


def test_schema_checkpoint_and_seed_isolation(tmp_path):
    old, new = schema_for("observable", V3, SEL_CONTENT), schema_for("observable", V3, SET_CONTENT)
    assert old["action_size"] == 421 and new["action_size"] == 512
    assert new["action_schema_version"] == "combat-set512-v2"
    assert new["information_version"] == "selection-information-v2"
    assert new["numeric_features"] == old["numeric_features"]
    model = PolicyValueNetwork("observable", V3, SET_CONTENT)
    path = tmp_path / "new.pt"
    save_checkpoint(path, model, "test", {}, {})
    with pytest.raises(ValueError):
        load_checkpoint(path, "observable", V3, SEL_CONTENT)
    assert not {r.environment_seed for r in frozen_manifest(SET_CONTENT)} & {r.environment_seed for r in frozen_manifest(SEL_CONTENT)}
    assert generator_config(SET_CONTENT)["heldout_master_seeds"] == {"validation": 182, "test": 280}
    assert generate_recipe(127, 1023, 1023, content_version=SET_CONTENT).environment_seed == 10 * 2**27 - 1


@pytest.mark.parametrize("slot", range(126))
def test_v2_full_game_particle_parity(v2, slot):
    previous.test_selection_complete_game_particle_parity(slot)


def test_v2_parallel_replay_and_learning(v2, tmp_path):
    previous.test_selection_parallel_replay_and_update(tmp_path)

