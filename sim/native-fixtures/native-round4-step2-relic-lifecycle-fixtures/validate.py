"""Check target-DLL reward/melting evidence without rewriting raw results."""
from pathlib import Path
import hashlib
import json

here=Path(__file__).resolve().parent
data=json.loads((here/'results.json').read_text())
assert data['status']=='completed'
assert data['gameAssemblySha256']=='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
assert len(data['results'])==24
counts={}
for row in data['results']:
    kind=row['test'];counts[kind]=counts.get(kind,0)+1
    if kind=='toy_box':
        assert len(row['offered'])==5 and all(r['wax'] for r in row['offered'])
        assert [r['id'] for r in row['inventoryAtOffer']]==['BURNING_BLOOD','TOY_BOX']
        chosen=[row['offered'][i]['id'] for i in row['selected']]
        assert [r['id'] for r in row['afterObtain']]==['BURNING_BLOOD','TOY_BOX']+chosen
        for turn in row['turns']:
            combat=turn['combat'];assert turn['combatsSeen']==min(15,combat)
            assert turn['isUsedUp']==(combat>=15)
            expected_melted=min(len(chosen),combat//3,5)
            assert [r['id'] for r in turn['relics']]==[r['id'] for r in row['beforeCombats']]
            assert [r['counter'] for r in turn['relics']]==[r['counter'] for r in row['beforeCombats']]
            assert [r['melted'] for r in turn['relics']]==[False,False]+[i<expected_melted for i in range(len(chosen))]
            assert turn['activeHookRelics']==[r['id'] for r in turn['relics'] if not r['melted']]
        assert row['rewardCounter']==5 and row['nicheCounter']==0
    elif kind=='small_capsule':
        assert len(row['offered'])==1 and not row['offered'][0]['wax']
        assert [r['id'] for r in row['inventoryAtOffer']]==['BURNING_BLOOD','SMALL_CAPSULE']
        assert [r['id'] for r in row['after']]==['BURNING_BLOOD','SMALL_CAPSULE']+([row['offered'][0]['id']] if row['claim'] else [])
        assert row['rewardCounter']==1 and row['nicheCounter']==0
    elif kind=='large_capsule':
        assert len(row['after'])==len(row['before'])+3
        assert len(row['deckAfter'])==len(row['deckBefore'])+(4 if row['hooks'] else 2)
        assert [event['rewardCounter'] for event in row['events']]==[0,1,2]
        assert all(event['deckCount']==len(row['deckBefore']) for event in row['events'])
        assert row['rewardCounter']==2 and row['nicheCounter']==0
    elif kind=='empty_bag':
        n=5 if row['kind']=='toy' else 2
        assert row['rewardCounter']==n
        assert [r['id'] for r in row['after'][2:]]==['CIRCLET']*n
        assert all(r['wax']==(row['kind']=='toy') for r in row['after'][2:])
    elif kind=='large_waits_for_child_reward':
        assert row['wasPaused'] and row['paused']['rewardCounter']==2 and row['paused']['deckCount']==3
        assert [r['id'] for r in row['paused']['relics']]==['BURNING_BLOOD','LARGE_CAPSULE','SMALL_CAPSULE']
        assert row['rewardCounter']==3 and len(row['deckAfter'])==5
    else:raise AssertionError(kind)
report={
    'status':'passed','fixture_count':len(data['results']),'groups':counts,
    'toy_box_combat_end_transitions':162,'gameAssemblySha256':data['gameAssemblySha256'],
    'results_sha256':hashlib.sha256((here/'results.json').read_bytes()).hexdigest(),
    'harness_sha256':hashlib.sha256((here/'AuditWorker.cs').read_bytes()).hexdigest(),
    'scope':'Controlled target-DLL ordered bags, reward timing/skip, wax state/18-combat histories, Large Capsule await ordering. Not complete normal bag initialization or full-run parity.'
}
(here/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
