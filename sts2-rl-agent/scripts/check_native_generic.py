"""Bounded generic data-contract check, never a formal training launch."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import torch
    from sts2_env.az.native_generic import CONTENT, GenericReplay
    from sts2_env.az.native_generic_backend import NativeBackend
    from sts2_env.az import all_runner as runner
    from sts2_env.az.config import atomic_json
    from scripts.check_native_collection import training_smoke
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='configs/az_native_generic_v1/config.json')
    p.add_argument('--protocol',default='configs/az_native_generic_v1/protocol.json')
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--smoke-update',action='store_true')
    p.add_argument('--leaf-mode',choices=['heuristic','learned','mixed'],default=None)
    p.add_argument('--value-mix',type=float,default=None)
    p.add_argument('--episodes',type=int,choices=range(1,5),default=4)
    p.add_argument('--skip-validation',action='store_true')
    args=p.parse_args(); torch.set_num_threads(1)
    config=json.loads(Path(args.config).read_text()); protocol=json.loads(Path(args.protocol).read_text())
    if args.out.exists():
        if not args.resume: raise ValueError('Fresh output required')
        model,_=runner.load_transformer_checkpoint(args.out/'initial.pt',runner.TIER,CONTENT,runner.V7)
    else:
        if args.resume: raise ValueError('Nothing to resume')
        args.out.mkdir(parents=True)
        model=runner.fresh_model(config,17)
        runner.save_transformer_checkpoint(args.out/'initial.pt',model,config=config)
    backend=NativeBackend(config['backend'],protocol,args.out)
    mode=args.leaf_mode or config['search'].get('leaf_mode','heuristic')
    mix=config['search'].get('value_mix',.5) if args.value_mix is None else args.value_mix
    backend.configure_search(mode,mix)
    episodes=backend.collect(args.out/'initial.pt',backend.training_recipes(0,args.episodes),args.out/'collection-cache/000')
    replay=GenericReplay(args.out/'replay',leaf_mode=mode,value_mix=mix)
    for e in episodes: replay.commit(e)
    summary,rows=(None,[]) if args.skip_validation else backend.evaluate(model,backend.validation,version='generic-audit',error_dir=args.out/'errors')
    report=dict(formal_training_started=False,protocol=protocol['manifest_sha256'],provenance=backend.provenance,
                training_fights=len(episodes),replay_rows=replay.size,validation=summary,validation_rows=rows)
    if args.smoke_update: report['training_smoke']=training_smoke(args.out,replay,rows,CONTENT)
    atomic_json(args.out/'report.json',report); print(json.dumps(report,indent=2))


if __name__=='__main__': main()
