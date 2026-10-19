import copy
import gzip
import json
from pathlib import Path
import pytest

from sts2_env.az.native_generic_backend import single_player_card_tokens, make_recipe, frozen_protocol, validate_protocol
from sts2_env.az.native_generic import validate_recipe
from scripts.check_native_scope_repair import repair_plan


def catalog():
    return {'cards':[
        dict(id='STRIKE_IRONCLAD',pool='IroncladCardPool',multiplayerOnly=False,maxUpgradeLevel=1),
        dict(id='PURITY',pool='ColorlessCardPool',multiplayerOnly=False,maxUpgradeLevel=1),
        dict(id='BELIEVE_IN_YOU',pool='ColorlessCardPool',multiplayerOnly=True,maxUpgradeLevel=1),
        dict(id='UNUPGRADABLE',pool='ColorlessCardPool',multiplayerOnly=False,maxUpgradeLevel=0)]}


def test_native_multiplayer_metadata_controls_both_upgrade_forms():
    tokens=single_player_card_tokens(catalog())
    assert tokens==['STRIKE_IRONCLAD','STRIKE_IRONCLAD+','PURITY','PURITY+','UNUPGRADABLE']
    recipes=[make_recipe(120+i,'SLIMES_WEAK',tokens,'train') for i in range(20)]
    assert any(c.endswith('+') for r in recipes for c in r['deck'])
    assert all(c.removesuffix('+')!='BELIEVE_IN_YOU' for r in recipes for c in r['deck'])
    frozen=frozen_protocol(tokens,['SLIMES_WEAK'],2)
    assert len(validate_protocol(frozen))==2


@pytest.mark.parametrize('field,value',[('multiplayerOnly',1),('maxUpgradeLevel',True),('maxUpgradeLevel',-1),('pool','SilentCardPool')])
def test_bad_eligibility_metadata_rejected(field,value):
    c=catalog(); c['cards'][0][field]=value
    with pytest.raises(ValueError): single_player_card_tokens(c)


def test_fixed_reproduction_changes_only_explicit_multiplayer_cards():
    c=catalog()
    recipe=make_recipe(19070030,'LIVING_FOG_NORMAL',['STRIKE_IRONCLAD','BELIEVE_IN_YOU','PURITY'],'train')
    original=copy.deepcopy(recipe)
    previous=dict(collection=[dict(ok=False,recipe=recipe)],preflight=[dict(ok=True,recipe=recipe)])
    plan=repair_plan(previous,c,fresh_count=1)
    fixed,upgraded,fresh=plan
    assert recipe==original
    assert fixed['original']==original
    assert fixed['recipe']['deck']==[x for x in recipe['deck'] if x!='BELIEVE_IN_YOU']
    assert fixed['recipe']['seed']==upgraded['recipe']['seed']==recipe['seed']
    assert upgraded['recipe']['deck']==[x+'+' for x in fixed['recipe']['deck']]
    assert fresh['recipe']['seed']!=recipe['seed']
    assert len({x['recipe']['scenario_id'] for x in plan})==3
    for case in plan: validate_recipe(case['recipe'])


def test_recorded_upgrade_and_choice_boundaries_reject_corruption(tmp_path):
    from sts2_env.az.native_generic import validate_raw, to_episode, GenericReplay
    with gzip.open(Path(__file__).parent/'fixtures/native_scope_upgraded_v1.json.gz','rt',encoding='utf-8') as f:
        raws=json.load(f)
    replay=GenericReplay(tmp_path,leaf_mode='mixed',value_mix=.5)
    assert any(s['successorParityScope']=='selector_boundary' for r in raws for s in r['steps'])
    for raw in raws:
        assert any(c.endswith('+') for c in raw['recipe']['deck'])
        validate_raw(raw)
        replay.commit(to_episode(raw))
        broken=copy.deepcopy(raw)
        upgraded=next(c for c in broken['steps'][0]['observation']['cards'] if c['data']['upgrade'])
        upgraded['data']['upgrade']=0
        with pytest.raises(ValueError,match='deck/upgrade'): validate_raw(broken)
        broken=copy.deepcopy(raw)
        step=next(s for s in broken['steps'] if s['successorParityScope']=='selector_boundary')
        step['successorParityScope']='complete_continuation'
        with pytest.raises(ValueError,match='boundary'): validate_raw(broken)
    assert replay.size==sum(len(r['steps']) for r in raws)
