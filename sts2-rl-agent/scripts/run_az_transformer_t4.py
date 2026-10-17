"""Prepare/audit is read-only with respect to experiments. Running needs explicit opt-in."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from sts2_env.az.t4_run_plan import plan
from sts2_env.az.t4_runner import read,binding,Backend,drive,audit,check_disk,finalize_holdouts,audit_holdouts
from sts2_env.az.natural_course import validate_course
from sts2_env.az.config import atomic_json,content_hash
from sts2_env.az.self_play import file_digest
from sts2_env.az.run_lock import RunLock

PREPARATION=Path('configs/az_transformer_t4_v1')


def documents():
    protocol=read(PREPARATION/'protocol.json');course=read(PREPARATION/'natural_course.json')
    for path,digest in course['source_sha256'].items():
        if file_digest(path)!=digest:raise ValueError('Natural source changed')
    validate_course(course,[read(path) for path in sorted(course['source_sha256'])])
    plans={str(seed):plan(protocol,course,mode,seed) for mode,seeds in [('smoke',(41,)),('formal',(42,43))] for seed in seeds}
    document=dict(version='t4-execution-freeze-v1',plans=plans,bindings={s:binding(p) for s,p in plans.items()},
                  entrypoint_source_hash=content_hash(Path(__file__).read_text(encoding='utf-8')),training_started=False)
    return document,protocol,course


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','verify-plan','smoke','formal','audit','audit-formal'))
    parser.add_argument('--root',type=Path)
    parser.add_argument('--smoke-root',type=Path)
    parser.add_argument('--seed',type=int,choices=(41,42,43),default=41)
    parser.add_argument('--allow-experiment',action='store_true')
    args=parser.parse_args(argv)
    # Reject before loading a model, allocating a run directory, or touching Replay.
    if args.mode in ('smoke','formal') and not args.allow_experiment:
        parser.error('Explicit --allow-experiment required; no experiment started')
    doc,protocol,course=documents();path=PREPARATION/'execution.json'
    if args.mode=='prepare':
        if path.exists() and read(path)!=doc:raise ValueError('Execution freeze changed; version explicitly before replacing')
        atomic_json(path,doc);print(json.dumps(dict(frozen=True,sha256=content_hash(doc),training_started=False)));return
    if not path.exists() or read(path)!=doc:raise ValueError('Missing/stale execution freeze')
    if args.mode=='verify-plan':print(json.dumps(dict(passed=True,sha256=content_hash(doc),training_started=False)));return
    if args.root is None:parser.error('--root required')
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    if args.mode=='audit':
        print(json.dumps(audit(args.root,doc['plans'][str(args.seed)],protocol,course),indent=2));return
    if args.mode=='audit-formal':
        print(json.dumps(audit_holdouts(args.root,doc['plans'],protocol,course),indent=2));return
    if args.mode=='formal':
        if args.smoke_root is None:parser.error('--smoke-root required for formal')
        smoke=audit(args.smoke_root,doc['plans']['41'],protocol,course)
        if not smoke['all_network_gates_passed'] or not smoke['network_utility_accepted']:
            raise ValueError('Formal blocked: both rounds and final smoke network utility gates must pass')
    check_disk(args.root,doc['plans']['41']['startup_free_bytes'])
    with RunLock(args.root):
        for seed in ((41,) if args.mode=='smoke' else (42,43)):
            root=args.root if seed==41 else args.root/f'seed-{seed}'
            p=doc['plans'][str(seed)]
            backend=Backend(root,p,protocol,course)
            drive(root,p,backend)
            atomic_json(root/'evidence.json',audit(root,p,protocol,course))
        if args.mode=='formal':
            finalize_holdouts(args.root,doc['plans'],protocol,course)
            atomic_json(args.root/'formal_evidence.json',audit_holdouts(args.root,doc['plans'],protocol,course))


if __name__=='__main__':main()
