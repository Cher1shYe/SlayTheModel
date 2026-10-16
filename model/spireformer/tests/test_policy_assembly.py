"""Policy labels require explicit admission without relaxing trajectory audit."""

from copy import deepcopy
from pathlib import Path

import pytest
import torch

from spireformer.assemble import (
    ACT_RTG_SCHEME, _episode_trajectories, _policy_exclusion_reason,
    _training_decisions, assemble_raw_dataset,
)
from spireformer.cli import build_parser
from spireformer.data import TensorShardDataset
from spireformer.raw_features import RawFeatureEncoder, RawFeatureSpec
from spireformer.raw_journal import load_episode
from test_act_reward_journal import _ActJournal
from test_assemble import _outside_step


class PolicyJournal(_ActJournal):
    mode = "no_sl"
    policy_id = "native-mcts"
    teacher = "native_checkpoint_privileged"

    def add(self, kind, payload, **kwargs):
        if kind == "action_submitted" and self.domain == "combat":
            payload = {**payload, "policy": {
                "actor": "policy", "policy_id": self.policy_id,
                "teacher_information": self.teacher,
            }}
        if kind == "decision":
            payload = {**payload, "information_regime": self.mode}
        return super().add(kind, payload, **kwargs)


def _mixed_run(path: Path, *, mode="no_sl", teacher="native_checkpoint_privileged"):
    journal = PolicyJournal(path)
    journal.mode, journal.teacher = mode, teacher
    journal.step(transition=lambda: journal.boundary(
        "combat_start", "fight-1", hp=40, max_hp=80,
    ))
    journal.step("combat", transition=lambda: journal.boundary(
        "combat_end", "fight-1", hp=0, max_hp=80, won=False,
    ))
    return load_episode(journal.finish_run("defeat"))


def test_mixed_mcts_act_returns_and_truthful_source_report(tmp_path: Path):
    audit = _mixed_run(tmp_path / "run.jsonl")
    result = assemble_raw_dataset(
        [audit.path], tmp_path / "cache", reward_scheme=ACT_RTG_SCHEME,
        allowed_policy_ids=["native-mcts"],
    )
    report = result.report["splits"]["train"]["episodes"][0]
    assert report["included_sources"] == {"human": 1, "native-mcts": 1}
    assert report["teacher_information"] == {"native_checkpoint_privileged": 1}
    assert result.report["allowed_policy_ids"] == ["native-mcts"]
    dataset = TensorShardDataset(tmp_path / "cache" / "train", verify_hashes=True)
    trajectory = next(iter(dataset))
    assert len(trajectory.steps) == 2
    assert [step.return_to_go for step in trajectory.steps] == [-10.5, -10.5]


def test_default_keeps_human_only_and_policy_labels_never_enter_features(tmp_path: Path):
    audit = _mixed_run(tmp_path / "run.jsonl")
    spec = RawFeatureSpec.fit(_training_decisions([audit], ["native-mcts"]), max_vocabulary_size=32)
    encoder = RawFeatureEncoder(spec)
    strict, report = _episode_trajectories(audit, encoder, 64)
    assert sum(len(t.steps) for t in strict) == 1
    assert report["exclusion_reasons"] == {"actor_not_human": 1}
    admitted, _ = _episode_trajectories(audit, encoder, 64, allowed_policy_ids=["native-mcts"])
    human = deepcopy(audit)
    human.steps[1].submission.payload["policy"] = {"actor": "human"}
    human_encoded, _ = _episode_trajectories(human, encoder, 64)
    for actual, expected in zip(admitted[0].steps, human_encoded[0].steps, strict=True):
        assert torch.equal(actual.entity_features, expected.entity_features)
        assert torch.equal(actual.legal_action_features, expected.legal_action_features)
    assert audit.steps[1].actor == "policy"


@pytest.mark.parametrize("policy_id,teacher,reason", [
    ("observed-automation", "native_checkpoint_privileged", "policy_not_allowed"),
    ("native-mcts", None, "policy_teacher_information_unverified"),
    ("native-mcts", "public_observation", "policy_teacher_information_unverified"),
    ("native-mcts", "native_checkpoint_privileged", None),
])
def test_provenance_is_not_inferred_from_configuration(policy_id, teacher, reason):
    step = _outside_step(1, 0)
    step.submission.payload["policy"] = {
        "actor": "policy", "policy_id": policy_id, "teacher_information": teacher,
    }
    assert _policy_exclusion_reason(step, ["native-mcts"]) == reason


def test_first_legal_needs_its_own_explicit_permission():
    step = _outside_step(1, 0)
    step.submission.payload["policy"] = {
        "actor": "policy", "policy_id": "first-legal", "teacher_information": "public_observation",
    }
    assert _policy_exclusion_reason(step, ["native-mcts"]) == "policy_not_allowed"
    assert _policy_exclusion_reason(step, ["first-legal"]) is None


def test_unknown_regime_stays_ineligible_even_with_policy_opt_in(tmp_path: Path):
    audit = _mixed_run(tmp_path / "run.jsonl", mode="unknown")
    assert not audit.value_target_valid
    with pytest.raises(ValueError, match="is not no-SL"):
        assemble_raw_dataset(
            [audit.path], tmp_path / "cache", reward_scheme=ACT_RTG_SCHEME,
            allowed_policy_ids=["native-mcts"],
        )
    assert not (tmp_path / "cache").exists()


def test_cli_policy_opt_in_is_explicit_and_bounded():
    parser = build_parser()
    base = ["assemble", "--input", "raw", "--output", "cache"]
    assert parser.parse_args(base).allow_policy == []
    assert parser.parse_args(base + ["--allow-policy", "native-mcts"]).allow_policy == ["native-mcts"]
    with pytest.raises(SystemExit):
        parser.parse_args(base + ["--allow-policy", "observed-automation"])
