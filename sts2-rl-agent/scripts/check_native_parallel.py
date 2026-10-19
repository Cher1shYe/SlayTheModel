"""Four real concurrent collection workers and cache-only restart; no training."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sts2_env.az.config import atomic_json
from sts2_env.az.native_generic_backend import NativeBackend


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    previous=Path('output/native_collection_speed_20261019')
    config=json.loads((previous/'config.json').read_text())['backend']
    config['fights_per_worker']=1
    protocol=json.loads((previous/'protocol.json').read_text())
    recipes=json.loads((previous/'recipes.json').read_text())
    checkpoint=out/'model.pt'; shutil.copyfile(previous/'initial.pt',checkpoint)
    backend=NativeBackend(config,protocol,out); backend.configure_workers(4); backend.configure_search('mixed',.5)
    start=perf_counter()
    raws=backend.fights(checkpoint,recipes,out/'cache','puct')
    elapsed=perf_counter()-start
    saved={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in (out/'cache').glob('*.json')
           if p.stem in {r['scenario_id'] for r in recipes}}
    restarted=NativeBackend(config,protocol,out); restarted.configure_workers(4); restarted.configure_search('mixed',.5)
    def forbidden(*args): raise AssertionError('Cache-only restart launched a process')
    restarted._prepare_parallel=forbidden
    assert restarted.fights(checkpoint,recipes,out/'cache','puct')==raws
    assert all((p.read_bytes(),p.stat().st_mtime_ns)==v for p,v in saved.items())
    report=dict(formal_training_started=False,workers=4,fights=len(raws),
                decisions=sum(len(r['steps']) for r in raws),seconds_including_build=elapsed,
                cache_restart_unchanged=True)
    atomic_json(out/'report.json',report); print(json.dumps(report))


if __name__=='__main__': main()
