"""Audit counts must distinguish terminal snapshots from actual decisions."""
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('g23f_audit',Path(__file__).resolve().parents[1]/'scripts/audit_az_transformer_g23f.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_full_natural_rule_witness_is_replayable_and_counts_decisions():
    from sts2_env.az.transformer_course import generate
    recipe=generate(42,0,92)
    def policy(info):
        native=audit.block_rule_action(info)
        return next(k for k,v in audit.action_candidates(info)[1].items() if v==native)
    row,witness=audit.trajectory(recipe,policy)
    assert sum(row['phase_decisions'].values())==row['decisions']
    assert sum(row['actions'].values())==row['decisions']
    assert witness['boundaries'][0]['step']==0
    assert witness['boundaries'][0]['public']['player_hp']==recipe.player_hp
    keys=iter(witness['actions'])
    again,_=audit.trajectory(recipe,lambda info:next(keys))
    assert row==again
    summary=audit.aggregate([row,row])
    assert summary['episodes']==2
    assert summary['utility']==row['outcome']['reward']
    assert sum(summary['phase_decisions'].values())==2*row['decisions']


def test_audit_rejects_invalid_action_instead_of_silently_skipping():
    from sts2_env.az.transformer_course import generate
    with pytest.raises(KeyError):
        audit.trajectory(generate(42,0,92),lambda info:'invalid-key')


def test_audit_rejects_corrupt_public_replay():
    from sts2_env.az.transformer_course import generate
    recipe=generate(42,0,92)
    env=audit.ObservableCombatAdapter(recipe,reward_version=audit.V7)
    public=audit.public_snapshot(env.information)
    public['player_hp']-=1
    episode={'rows':[{'public_information':public,'chosen_action':'end_turn'}]}
    with pytest.raises(ValueError,match='Native replay public mismatch'):
        audit.trajectory(recipe,episode=episode)
