"""Characterize low-budget ties and validate diagnostic-only interventions."""
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import numpy as np
import pytest

from sts2_env.az.observable_puct import search_belief

spec = importlib.util.spec_from_file_location("boss_diagnostic", Path(__file__).parents[1]/"scripts/diagnose_az_boss_search.py")
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


@dataclass(frozen=True)
class State:
    utility: float | None = None
    legal_mask: tuple = (True,)*8

    def key(self):
        return self.utility

    def terminal_value(self):
        return self.utility


class Particle:
    def __init__(self, info, rng):
        self.info = info

    def step(self, action):
        self.info = State(-0.9, (False,)*8)
        return self.info


def test_negative_return_spreads_eight_visits_and_exposes_index_tie():
    priors = np.array([.07]*7+[.51])
    result = search_belief(State(), Particle, lambda _: (priors, -.9),
                           model_version="test", budget=8)
    assert result.action == 0
    np.testing.assert_array_equal(result.root_visits, np.ones(8))
    assert diagnostic.prior_tie_action(result) == 7
    # The probe changes only the chosen action, never the training target.
    np.testing.assert_array_equal(result.policy_target, np.ones(8)/8)
    assert all(e.q == -.9 for e in result.root.edges.values())


def test_forced_action_has_no_synthetic_visit_tie():
    state = State(legal_mask=(False,)*7+(True,))
    result = search_belief(state, Particle, lambda _: (np.eye(8)[7], -.9),
                           model_version="test", budget=8)
    assert diagnostic.prior_tie_action(result) == 7
    assert result.root_visits.sum() == 0


def test_summary_does_not_count_nonsearch_rows_as_tie_changes():
    cases = [dict(seed=42,mode="network",seconds=0, outcome=dict(
        termination_reason="death",reward=-1),rows=[dict(phase=1,value=-.5,action=0,network_action=0)])]
    summary = diagnostic.summarize(cases)["42/network"]
    assert summary["prior_tie_changes"] == summary["tied_max"] == 0
    assert summary["rollout_value_mae"] == .5


def test_real_probe_is_serializable_and_rejects_heldout(tmp_path):
    import torch
    from sts2_env.az.network import PolicyValueNetwork, save_checkpoint
    from sts2_env.az.config import canonical_json
    from sts2_env.az.content import BOSS_CONTENT
    from sts2_env.az.rewards import V6
    diagnostic.initialize_worker()
    torch.manual_seed(7)
    checkpoint=tmp_path/"model.pt"
    save_checkpoint(checkpoint,PolicyValueNetwork("observable",V6,BOSS_CONTENT),"probe",{}, {})
    def job(recipe):
        return (42,"network",recipe.to_dict(),str(checkpoint),diagnostic.file_digest(checkpoint),str(tmp_path/"errors"))
    case=diagnostic.run_case(job(diagnostic.generate(48,0,90)))
    assert canonical_json(case)
    assert all(type(row["phase"]) is int for row in case["rows"])
    with pytest.raises(ValueError,match="training recipes only"):
        diagnostic.run_case(job(diagnostic.generate(187,0,180,"validation")))
