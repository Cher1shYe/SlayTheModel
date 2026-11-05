import hashlib
import json

import numpy as np
import pytest
import torch
from types import SimpleNamespace

from agent.armg import ARMG_ACTION_DIM, ARMG_OBS_DIM, _CARD_OFF, ArmGScorer
from agent.common import RACT
from agent.armg_train import _save
from deployment import finetune_armg_prior as ft


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_source(tmp_path):
    source = tmp_path / 'source'
    snap, shards = source / 'data_snapshot', source / 'dataset'
    snap.mkdir(parents=True)
    shards.mkdir()
    snapshots = {}
    for name in ('cards', 'relics', 'potions', 'community'):
        p = snap / (name+'.json')
        if name == 'community':
            content={'reward_skip_rate':37.1,'rest_sites':[]}
        else:
            content={'bracket':'solo:wr50:standard','character':'IRONCLAD',
                     'rows': ([{'id':'AGGRESSION','elo':1700,'offered':100,'picked':60},
                               {'id':'ANGER','elo':1450,'offered':50,'picked':20}]
                              if name == 'cards' else [])}
        p.write_text(json.dumps(content), encoding='utf-8')
        snapshots[name] = {'sha256': sha(p)}
    (snap/'manifest.json').write_text(json.dumps({'snapshots': snapshots}),encoding='utf-8')
    ext = tmp_path/'ext.pyd'
    ext.write_bytes(b'not loaded, test identity only')
    config = {'games': 5, 'simulator_sha256': sha(ext), 'data_manifest_sha256': sha(snap/'manifest.json'),
              'information': 'oracle', 'ascension': 0, 'simulations_per_decision': 2000,
              'boss_simulations_per_decision': 10000, 'path_cache': 'none', 'combat': 'pure mcts'}
    (source/'config.json').write_text(json.dumps(config),encoding='utf-8')
    (source/'progress.json').write_text(json.dumps({'state':'completed','stage':'completed','games_completed':5}),encoding='utf-8')
    rows=[]
    for i in range(5):
        p=shards/f'episode-{30100000+i}.npz'
        s=np.zeros((1,ARMG_OBS_DIM),dtype=np.float32)
        a=np.zeros((2,ARMG_ACTION_DIM),dtype=np.float32)
        a[0,int(RACT.TAKE_CARD)]=a[1,int(RACT.TAKE_CARD)]=1
        a[0,_CARD_OFF+1]=1; a[1,_CARD_OFF+2]=1
        np.savez_compressed(p,states=s,features=a,targets=np.asarray([.8,.2],dtype=np.float32),
                            offsets=np.asarray([0,2]),screens=np.asarray(['CARD_REWARD']))
        rows.append({'seed':30100000+i,'status':'terminated','shard':str(p.resolve()),'records':1,
                     'screens':{'CARD_REWARD':1}})
    (source/'episodes.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    return source, ext


def test_finetune_is_separate_and_preserves_original(tmp_path, monkeypatch):
    source, ext = make_source(tmp_path)
    monkeypatch.setattr(ft.isolated, '_extension', str(ext))
    torch.set_num_threads(1)
    model=ArmGScorer()
    original=tmp_path/'original.pt'
    _save(original,model,torch.optim.Adam(model.parameters()),{}, {})
    before=sha(original)
    result=ft.run(checkpoint=original,sources=[source],out_dir=tmp_path/'output',epochs=1)
    assert result['state']=='completed'
    assert (tmp_path/'output/finetuned.pt').is_file()
    assert sha(original)==before
    manifest=json.loads((tmp_path/'output/dataset_manifest.json').read_text(encoding='utf-8'))
    assert sum(row['split']=='train' for row in manifest['episodes'])==4
    assert sum(row['split']=='validation' for row in manifest['episodes'])==1


def test_rejects_duplicate_seeds_and_snapshot_corruption(tmp_path):
    source, ext=make_source(tmp_path)
    with pytest.raises(ValueError, match='duplicate game seed'):
        ft.load_records([source,source], sha(ext))
    (source/'data_snapshot/cards.json').write_text('{"changed": true}',encoding='utf-8')
    with pytest.raises(ValueError, match='snapshot mismatch'):
        ft.load_records([source],sha(ext))


def test_rejects_different_battle_settings(tmp_path):
    source, ext=make_source(tmp_path)
    path=source/'config.json'
    config=json.loads(path.read_text(encoding='utf-8'))
    config['information']='hidden'
    path.write_text(json.dumps(config),encoding='utf-8')
    with pytest.raises(ValueError, match='information mismatch'):
        ft.load_records([source],sha(ext))


def test_rest_target_aggregates_upgrade_candidates_and_excludes_other_actions():
    prior=SimpleNamespace(rests={'HEAL':{'count':100,'pct_low_hp':60,'pct_high_hp':13},
                                  'SMITH':{'count':100,'pct_low_hp':39,'pct_high_hp':82}})
    state=np.zeros(ARMG_OBS_DIM,dtype=np.float32); state[0]=.25
    feats=np.zeros((3,ARMG_ACTION_DIM),dtype=np.float32)
    feats[0,int(RACT.REST_HEAL)]=1
    feats[1:,int(RACT.REST_UPGRADE)]=1
    groups,prob,source=ft.website_targets(state,feats,'REST',prior)
    assert source == 'rest'
    assert sorted(map(len,groups)) == [1,2]
    heal_group=next(i for i,g in enumerate(groups) if g==[0])
    assert prob[heal_group] > .5 and sum(prob)==pytest.approx(1)
    feats[0,:]=0; feats[0,int(RACT.USE_POTION)]=1
    assert ft.website_targets(state,feats,'REST',prior)[2] is None


def test_card_target_ignores_skip_and_unknown_cards(tmp_path):
    from agent.armg_prior import LocalPrior
    source,_=make_source(tmp_path)
    prior=LocalPrior(source/'data_snapshot')
    state=np.zeros(ARMG_OBS_DIM,dtype=np.float32)
    feats=np.zeros((4,ARMG_ACTION_DIM),dtype=np.float32)
    feats[:3,int(RACT.TAKE_CARD)]=1
    feats[0,_CARD_OFF+1]=feats[1,_CARD_OFF+2]=feats[2,_CARD_OFF+3]=1
    feats[3,int(RACT.SKIP_CARD)]=1
    groups,prob,source_name=ft.website_targets(state,feats,'CARD_REWARD',prior)
    assert source_name=='cards' and groups==[[0],[1]]
    assert prob[0] > prob[1] and sum(prob)==pytest.approx(1)
