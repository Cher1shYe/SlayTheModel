from pathlib import Path
import sys,json,concurrent.futures
B=Path(__file__).resolve().parent
sys.path.insert(0,str(B/'python'))
from sts2_env.az.native_generic_backend import NativeBackend
from sts2_env.az.config import atomic_json
old=B.parent/'epoch1024_e3_500ms_20261020_005445'
c=json.loads((B/'config.json').read_text())
n=NativeBackend(c['backend'],json.loads((B/'protocol.json').read_text()),B)
n.configure_search('learned',1.)
d=B/'verification/fatal';d.mkdir(parents=True,exist_ok=True)
atomic_json(d/'job.json',dict(verifyFatalBoundary=True))
n._execute(d/'job.json',d/'worker.log')
assert 'FATAL_BOUNDARY_PASS' in (d/'worker.log').read_text(encoding='utf-8')
jobs=list((old/'debug/hog-regression').glob('*/job.json'))
jobs += [old/'debug'/name/'job.json' for name in ('ironwave-repro','handofgreed-repro','volley-repro')]
def check(p):
    j=json.loads(p.read_text());label=p.parent.name
    directory=B/'verification'/label;directory.mkdir(parents=True,exist_ok=True)
    j.update(source=str(B/'python'),checkpoint=str(B/'models/champion.pt'),leafMode='learned',valueMix=1.,budgetMs=500)
    expected_path=Path(j['cases'][0]['output'])
    expected=json.loads(expected_path.read_text())
    j['cases'][0]['output']=str(directory/'replay.json')
    atomic_json(directory/'job.json',j)
    n._execute_parallel(directory/'job.json',directory/'worker.log')
    actual=json.loads((directory/'replay.json').read_text())
    assert len(actual['steps'])==len(expected['steps'])
    assert actual['terminal']==expected['terminal'] and actual['hp']==expected['hp']
    assert actual['continuation']==expected['continuation']
    assert all(s['featureParity'] and s['successorParity'] for s in actual['steps'])
    return dict(label=label,steps=len(actual['steps']),terminal=actual['terminal'],hp=actual['hp'],complete_continuation_equal=True,strict_parity=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(check,jobs))
atomic_json(B/'verification/report.json',dict(fatal_boundary='passed',replays=results))
print(json.dumps(results),flush=True)
