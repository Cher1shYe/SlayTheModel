"""Checkpoint/feature contracts only: no rollouts and no optimizer updates."""
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from agent import armg, armg_train, engine_identity
from agent.common import RACT, SCREEN, sim
from agent.nets import checkpoint_config, load_checkpoint, read_checkpoint, save_checkpoint
from deployment import migrate_armg_weights as migration
from deployment.evaluate_armg import load_armg_checkpoint


def _config(model):
    return checkpoint_config(model) | {"armg_feature_version": armg.ARMG_FEATURE_VERSION,
                                      "armg_obs_dim": armg.ARMG_OBS_DIM,
                                      "armg_action_dim": armg.ARMG_ACTION_DIM}


def test_identity_checks_loaded_binding_and_source_counts(monkeypatch):
    contract = engine_identity.current_engine_contract()
    assert contract["native_parity_complete"] is False
    assert contract["simulator_sha256"] == engine_identity.sha256_file(sim.__file__)
    monkeypatch.setattr(sim, "CARD_COUNT", int(sim.CARD_COUNT) + 1)
    with pytest.raises(ValueError, match="binding/source schema mismatch: CARD_COUNT"):
        engine_identity.current_engine_contract()


def test_identity_rejects_old_binding_even_when_dimensions_match(monkeypatch):
    monkeypatch.setattr(sim, "ENGINE_RULESET_ID", "legacy")
    with pytest.raises(ValueError, match="rebuild"):
        engine_identity.current_engine_contract()


def test_identity_rejects_binary_replaced_after_import(monkeypatch):
    original = engine_identity.sha256_file
    monkeypatch.setattr(engine_identity, "sha256_file",
                        lambda path: "b" * 64 if str(path) == str(sim.__file__) else original(path))
    with pytest.raises(ValueError, match="binary changed after import"):
        engine_identity.current_engine_contract()


def test_identity_rejects_source_changed_in_a_running_process(monkeypatch):
    engine_identity.current_engine_contract()
    monkeypatch.setattr(engine_identity, "source_content_digest", lambda root: "b" * 64)
    with pytest.raises(ValueError, match="source/features changed"):
        engine_identity.current_engine_contract()


def test_same_shape_old_environment_is_rejected_by_all_normal_loaders(tmp_path):
    model = armg.ArmGScorer(hidden=(4,))
    path = tmp_path / "old.pt"
    config = _config(model)
    config["engine_contract"]["simulator_sha256"] = "a" * 64
    torch.save({"state_dict": model.state_dict(), "config": config}, path)
    target = armg.ArmGScorer(hidden=(4,))
    before = {k: v.clone() for k, v in target.state_dict().items()}
    optimizer = torch.optim.Adam(target.parameters())
    for operation in (lambda: load_checkpoint(path, target),
                      lambda: load_armg_checkpoint(path, target),
                      lambda: armg_train._warm_start(path, target),
                      lambda: armg_train._restore(path, target, optimizer, {})):
        with pytest.raises(ValueError, match="identity|schema"):
            operation()
        assert all(torch.equal(before[k], v) for k, v in target.state_dict().items())


def test_current_checkpoint_round_trip_keeps_rng_and_progress(tmp_path):
    model = armg.ArmGScorer(hidden=(4,))
    optimizer = torch.optim.Adam(model.parameters())
    settings = {"train_seed_offset": 0, "need_rules": False, "relic_rules": False}
    progress = {"games": 12, "baseline": 0.25}
    path = tmp_path / "current.pt"
    armg_train._save(path, model, optimizer, progress, settings)
    payload = read_checkpoint(path)
    assert payload["settings"]["simulator_sha256"] == engine_identity.sha256_file(sim.__file__)
    torch.rand(3)
    restored = armg_train._restore(path, model, optimizer, settings)
    assert restored == progress
    assert torch.equal(torch.get_rng_state(), payload["torch_rng_state"])
    assert np.array_equal(np.random.get_state()[1], payload["numpy_rng_state"][1])


@pytest.fixture
def legacy_fixture(tmp_path, monkeypatch):
    # Copy the immutable reviewed v10 source, synthesize weights of its shape.
    # No user's checkpoint is loaded or modified in these tests.
    old_tree = tmp_path / "legacy-tree"
    shutil.copytree(engine_identity.ROOT / "validation/round2/source-before", old_tree)
    old_layout = engine_identity.source_layout(old_tree)
    old_obs = old_layout["dimensions"]["PUBLIC_OBS_DIM"] - old_layout["dimensions"]["PUBLIC_COMBAT_OBS_DIM"]
    model = armg.ArmGScorer(hidden=(4,))
    source = tmp_path / "source.pt"
    config = _config(model)
    config.update(armg_feature_version=2, armg_obs_dim=old_obs,
                  obs_version=10, action_schema_version=9,
                  in_features=old_obs + armg.ARMG_ACTION_DIM)
    config["param_shapes"][0][1] = old_obs + armg.ARMG_ACTION_DIM
    config["engine_contract"] = {
        "simulator_sha256": "a" * 64,
        "source_content_sha256": engine_identity.source_content_digest(old_tree)}
    weights = model.state_dict()
    weights["net.0.weight"] = torch.randn(4, old_obs + armg.ARMG_ACTION_DIM)
    torch.save({"state_dict": weights, "config": config,
                "settings": {"simulator_sha256": "a" * 64}, "progress": {"games": 800},
                "optimizer_state_dict": {"state": {"old": "not reused"}},
                "torch_rng_state": torch.get_rng_state(), "numpy_rng_state": np.random.get_state()}, source)
    return {"source": source, "output": tmp_path / "migrated.pt",
            "source_sha256": engine_identity.sha256_file(source), "old_engine_sha256": "a" * 64,
            "new_engine_sha256": engine_identity.sha256_file(sim.__file__),
            "source_tree": old_tree, "hidden": (4,)}


def test_explicit_migration_is_new_initialization_not_resume(legacy_fixture):
    options = legacy_fixture
    original_bytes = options["source"].read_bytes()
    rng_before = torch.get_rng_state().clone()
    result = migration.migrate_weights(**options)
    assert options["source"].read_bytes() == original_bytes
    assert torch.equal(torch.get_rng_state(), rng_before)
    output = read_checkpoint(options["output"])
    assert output["checkpoint_kind"] == "weights_only_migration"
    assert output["migration"]["training_games_in_target_environment"] == 0
    assert output["migration"]["source_progress"] == {"games": 800}
    assert output["migration"]["feature_changes"]
    for key in output["migration"]["reset_fields"]:
        assert key not in output
    model = armg.ArmGScorer(hidden=(4,))
    load_armg_checkpoint(options["output"], model)
    source_payload = read_checkpoint(options["source"])
    mapping, _ = migration._feature_mapping(options["source_tree"],
        engine_identity.source_content_digest(options["source_tree"]), 2,
        engine_identity.source_layout(options["source_tree"]), engine_identity.source_layout(engine_identity.ROOT))
    old_obs = source_payload["config"]["armg_obs_dim"]
    first = model.state_dict()["net.0.weight"]
    assert torch.equal(first[:, mapping], source_payload["state_dict"]["net.0.weight"][:, :old_obs])
    assert torch.equal(first[:, armg.ARMG_OBS_DIM:], source_payload["state_dict"]["net.0.weight"][:, old_obs:])
    new_columns = sorted(set(range(armg.ARMG_OBS_DIM)) - set(mapping))
    assert torch.count_nonzero(first[:, new_columns]) == 0
    # Exact logits on corresponding old features, including action block.
    old_state, actions = torch.randn(1, old_obs), torch.randn(1, 3, armg.ARMG_ACTION_DIM)
    new_state = torch.zeros(1, armg.ARMG_OBS_DIM)
    new_state[:, mapping] = old_state
    old_net = torch.nn.Sequential(torch.nn.Linear(old_obs + armg.ARMG_ACTION_DIM, 4), torch.nn.ReLU(), torch.nn.Linear(4, 1))
    old_net.load_state_dict({k.removeprefix("net."): v for k,v in source_payload["state_dict"].items()})
    expected_logits = old_net(torch.cat((old_state[:, None].expand(-1, 3, -1), actions), -1)).squeeze(-1)
    torch.testing.assert_close(model(new_state, actions), expected_logits, atol=1e-4, rtol=1e-5)
    initialization = armg_train._warm_start(options["output"], model)
    assert initialization["source_migration"]["source_checkpoint_sha256"] == options["source_sha256"]
    with pytest.raises(ValueError, match="cannot resume"):
        armg_train._restore(options["output"], model, torch.optim.Adam(model.parameters()), {})
    with pytest.raises(FileExistsError):
        migration.migrate_weights(**options)
    assert result["sha256"] == engine_identity.sha256_file(options["output"])


@pytest.mark.parametrize("field", ["source_sha256", "old_engine_sha256", "new_engine_sha256"])
def test_migration_requires_both_hashes_and_untampered_source(legacy_fixture, field):
    legacy_fixture[field] = "b" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        migration.migrate_weights(**legacy_fixture)
    assert not legacy_fixture["output"].exists()


def test_equal_dimension_reordered_action_ids_cannot_migrate(legacy_fixture, monkeypatch):
    common = legacy_fixture["source_tree"] / "simulator/include/sts2/common.h"
    common.write_text(common.read_text().replace("{ PLAY_CARD, END_TURN, CHOOSE", "{ END_TURN, PLAY_CARD, CHOOSE"))
    digest = engine_identity.source_content_digest(legacy_fixture["source_tree"])
    monkeypatch.setattr(migration, "NATIVE_PORT_V1_SOURCE_SHA256", digest)
    payload = read_checkpoint(legacy_fixture["source"])
    payload["config"]["engine_contract"]["source_content_sha256"] = digest
    torch.save(payload, legacy_fixture["source"])
    legacy_fixture["source_sha256"] = engine_identity.sha256_file(legacy_fixture["source"])
    with pytest.raises(ValueError, match="identical IDs"):
        migration.migrate_weights(**legacy_fixture)
    assert not legacy_fixture["output"].exists()


@pytest.mark.parametrize("grid_kind", [6, 7, 8, 9, 10, 11, 12])
def test_new_deck_grids_preserve_action_order_card_and_enchantment(grid_kind):
    actions = [(int(RACT.SELECT_GRID_CARD), 1), (int(RACT.SELECT_GRID_CARD), 0)]
    context = SimpleNamespace(
        screen=SCREEN.EVENT, observe_public=lambda: [0.0] * int(sim.PUBLIC_OBS_DIM),
        legal_actions=lambda: actions, deck=[(6, False, 1, 2), (7, True, 2, 1)],
        deck_enchantments=[(0, 0, False), (3, 2, False)], potions=[],
        card_grid_kind=grid_kind, card_grid_selected=[False, True], event_relics=[])
    _, actual, rows = armg.build_candidates(context)
    assert actual == actions
    assert rows[0, armg._CARD_OFF + 7] == 1
    assert rows[1, armg._CARD_OFF + 6] == 1
    assert rows[0, armg._META_OFF + 1] == pytest.approx(grid_kind / 5)
    assert rows[0, armg._META_OFF + 5] == 1
    end = armg._CARD_OFF + int(sim.CARD_FEAT_DIM)
    np.testing.assert_allclose(rows[0, end - 3:end], [3 / 5, 2 / 10, 0])
