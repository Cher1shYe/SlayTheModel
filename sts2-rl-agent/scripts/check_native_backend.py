"""Bounded native v2 integration audit; does not launch the training runner."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from sts2_env.az.native_backend import NativeBackend, training_recipes
    from sts2_env.az.native_pilot import NativeExpandedReplayBuffer
    from sts2_env.az.config import atomic_json
    from sts2_env.az.all_runner import load_transformer_checkpoint, TIER, ALL_CONTENT, V7
    from scripts.check_native_collection import sha, training_smoke
    import torch
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/az_native_xs_v2/config.json')
    p.add_argument('--protocol', default='configs/az_native_xs_v2/protocol.json')
    p.add_argument('--checkpoint', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--smoke-update', action='store_true')
    args = p.parse_args()
    torch.set_num_threads(1)
    config, protocol = [json.loads(Path(x).read_text()) for x in (args.config, args.protocol)]
    out = args.out
    if out.exists():
        if not args.resume or sha(out/'initial.pt') != sha(args.checkpoint):
            raise ValueError('Fresh output or identical model resume required')
    else:
        if args.resume:
            raise ValueError('Nothing to resume')
        out.mkdir(parents=True)
        shutil.copyfile(args.checkpoint, out/'initial.pt')
    backend = NativeBackend(config['backend'], protocol, out)
    episodes = backend.collect(out/'initial.pt', training_recipes(0, 4), out/'collection-cache'/'000')
    replay = NativeExpandedReplayBuffer(out/'replay')
    for episode in episodes:
        replay.commit(episode)
    model, _ = load_transformer_checkpoint(out/'initial.pt', TIER, ALL_CONTENT, V7)
    summary, rows = backend.evaluate(model, backend.validation, version='audit-baseline', error_dir=out/'errors')
    steps = [s for e in episodes for s in e['native_audit']['steps']]
    played = sorted({a['CardId'] for s in steps for a in s['observation']['actions']
                     if a['Key'] == s['action'] and a['CardId']})
    report = dict(formal_training_started=False, validation=summary, validation_rows=rows,
        validation_manifest=protocol['manifest_sha256'], training_fights=len(episodes), replay_rows=replay.size,
        played_cards=played, training_state_action_checks=len(steps), provenance=backend.provenance)
    if args.smoke_update:
        report['training_smoke'] = training_smoke(out, replay, rows)
    atomic_json(out/'report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
