"""Validate target assembly identity and the controlled native outcomes."""
from pathlib import Path
import hashlib
import json
here = Path(__file__).resolve().parent
r = json.loads((here / 'results.json').read_text())
assert r['status'] == 'completed'
assert r['gameAssemblySha256'] == '9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
assert r['userDirectory'].endswith('SlayTheModelNativeRound3RelicAudit20261031')
assert len(r['results']) == 26
options=r['results'][0]['transformationOptions']
assert len(options)==80 and 'NOT_YET' in options and 'GRAPPLE' not in options
assert options.index('NOT_YET')==options.index('MOLTEN_FIST')+1
assert options.index('OFFERING')==options.index('NOT_YET')+1
for f in r['results']:
    t=f['test']
    if t == 'distinguished_cape':
        assert (f['hp'],f['maxHp'],f['nicheCounter']) == (80,80,2)
        assert [c['card'] for c in f['deck'][8:]] == (['NORMALITY','REGRET'] if f['seed']==0 else ['CLUMSY','GUILTY']) + ['APPARITION']*3
    elif t == 'sere_talon':
        assert (f['hp'],f['maxHp'],f['nicheCounter']) == (71,71,0)
        assert [c['card'] for c in f['deck'][8:]] == ['WISH']*3
    elif t == 'leafy_poultice':
        assert (f['hp'],f['maxHp'],f['nicheCounter'],f['transformationsCounter']) == (68,68,0,2)
        assert [c['originalIndex'] for c in f['deck']] == [0,3,4,5,6,7,-1,-1]
        assert [c['card'] for c in f['deck'][6:]] == (['SECOND_WIND','OFFERING'] if f['seed']==0 else ['FIGHT_ME','BLOOD_WALL'])
    elif t == 'leafy_hooks':
        assert (f['hp'],f['maxHp'],f['goldAfter'],f['bookCount'],len(f['deck'])) == (50,68,159,8,10)
        assert [c['upgraded'] for c in f['deck'][6:]] == [True,True,False,False]
    elif t == 'leafy_no_basic':
        assert (f['maxHp'],len(f['deck']),f['transformationsCounter']) == (68,2,0)
    elif t.startswith('sere_'):
        assert (f['hp'],f['maxHp'],len(f['deck'])) == (1,1,11)
    elif t == 'neows_torment':
        assert f['deck'][-1]['card'] == 'NEOWS_FURY' and f['nicheCounter'] == 0
    elif t == 'seal_of_gold':
        active=f['goldBefore']>=3
        assert f['goldAfter']==f['goldBefore']-(3 if active else 0)
        assert f['energyAfter']==f['energyBefore']+int(active)
    elif t == 'stone_cracker':
        assert f['counter']==(0 if f['empty'] else 7)
        assert [c['originalIndex'] for c in f['cards'] if c['upgraded']]==(list(range(8)) if f['empty'] else ([3,6] if f['seed']==0 else [4,6]))
    elif t == 'red_skull_heal_damage':
        assert (f['initialStrength'],f['healedStrength'],f['finalHp'],f['finalStrength'])==(3,0,39,3)
    elif t == 'red_skull_damage':
        assert (f['initialStrength'],f['finalHp'],f['finalStrength'])==(0,40,3)
    elif t == 'fake_strike_dummy':
        assert (f['strike'],f['bash'])==(10 if f['both'] else 7,8)
    else:
        raise AssertionError(t)
summary={'status':'passed','fixtures':len(r['results']),'game_assembly_sha256':r['gameAssemblySha256'],
         'harness_sha256':hashlib.sha256((here/'AuditWorker.cs').read_bytes()).hexdigest(),
         'results_sha256':hashlib.sha256((here/'results.json').read_bytes()).hexdigest(),
         'scope':'Controlled native relic fixtures only; not full-run or full-content parity.'}
(here/'validation.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
