"""New utility-only criterion is explicit; historical win-priority remains versioned."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from sts2_env.az import evaluation
from sts2_env.az.rewards import V2
from tests.test_az_hp_reward import row


def pair():
    old=[dict(row(i,True,hp=1,enemy=0),encounter_id='fixture') for i in range(256)]
    new=[dict(row(i,i!=0,hp=20 if i else 0,enemy=0 if i else 40),encounter_id='fixture') for i in range(256)]
    return old,new


def gate(a,b):
    return evaluation.promotion_gate(a,b,reward_version=V2,criterion='utility-only-v1')


def test_utility_gain_can_promote_despite_lower_win_rate():
    old,new=pair()
    report=gate(old,new)
    assert report['mean_win_difference']<0 and report['confidence_interval'][0]>0
    assert report['promote'] and not report['win_priority_satisfied']
    assert not evaluation.promotion_gate(old,new,reward_version=V2)['promote']


def test_more_wins_cannot_override_utility_loss_or_tie():
    old,new=pair()
    assert not gate(new,old)['promote']
    assert not gate(old,deepcopy(old))['promote']


def test_integrity_and_count_remain_required():
    old,new=pair()
    assert not gate(old[:-1],new[:-1])['promote']
    new[0]['illegal_actions']=1
    assert not gate(old,new)['promote']
    new[0]['reward']=.999
    with pytest.raises(ValueError,match='utility'): gate(old,new)
    with pytest.raises(ValueError,match='criterion'):
        evaluation.promotion_gate(old,new,criterion='typo')


@pytest.mark.parametrize('network_improves',[True,False])
def test_search_does_not_control_acceptance(monkeypatch,network_improves):
    old,new=pair()
    monkeypatch.setattr(evaluation,'summarize',lambda rows:{})
    def runner(role,budget):
        improves=network_improves if budget==0 else not network_improves
        return (old if role=='champion' else new) if improves else (new if role=='champion' else old)
    report=evaluation.compare(None,None,'a','b',[SimpleNamespace(split='validation')],simulations=8,
        evaluation_runner=runner,reward_version=V2,promotion_policy='network-utility-v1')
    assert report['promote']==network_improves
    assert report['promotion_policy']=='network-utility-v1'
