"""Bounded native collection/quality check; optional two-update integration smoke only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def provenance(repo):
    from sts2_env.az.config import content_hash
    from sts2_env.az.network import code_digest
    files = list((repo/'tools/Sts2.NativeWorker').glob('*.cs'))
    files += list((repo/'src/SlayTheModel.Search').glob('*.cs'))
    files += list((repo/'combat/src').rglob('*.cs'))
    files += [repo/'scripts/native-worker.ps1', repo/'contracts/sts2-v0.111.0-windows.json']
    files += list(repo.rglob('*.csproj')) + list(repo.glob('Directory.Build.*'))
    return dict(python=code_digest(), native=content_hash({str(p.relative_to(repo)): sha(p) for p in sorted(files)}),
                service=sha(ROOT/'scripts/native_pilot_service.py'), driver=sha(__file__))


def check_case(raw, identity, model_sha, spec, budget):
    from sts2_env.az.native_pilot import validate_raw
    if (raw['identity'] != identity or raw['modelSha256'] != model_sha or raw['budgetMs'] != budget
            or any(raw[k] != spec[k] for k in ('seed', 'arm', 'split')) or raw['initialHp'] != spec['hp']):
        raise ValueError('Cached native fight provenance mismatch')
    validate_raw(raw)


def summarize(raws):
    import numpy as np
    from sts2_env.az.all_runner import paired_gain
    result = {}
    paired = {}
    for arm in ('policy', 'uct', 'puct'):
        rows = [r for r in raws if r['arm'] == arm]
        steps = [s for r in rows for s in r['steps']]
        seconds = sum(s['seconds'] for s in steps)
        simulations = sum(s['simulations'] for s in steps)
        result[arm] = dict(episodes=len(rows), wins=sum(r['outcome']['won'] for r in rows),
            mean_utility=float(np.mean([r['outcome']['reward'] for r in rows])),
            mean_final_hp=float(np.mean([r['outcome']['finalHp'] for r in rows])),
            decisions=len(steps), simulations=simulations, search_seconds=seconds,
            simulations_per_second=simulations/seconds if seconds else 0.,
            decision_seconds_p50=float(np.median([s['seconds'] for s in steps])),
            fight_seconds=sum(r['wallSeconds'] for r in rows))
        paired[arm] = [dict(scenario_id=f"native-{r['seed']}-{r['initialHp']}", reward=r['outcome']['reward']) for r in rows]
    return result, {arm: paired_gain(paired['policy'], paired[arm]) for arm in ('uct', 'puct')}, paired['policy']


def training_smoke(out, replay, baseline_rows, content=None):
    import torch
    from sts2_env.az import all_runner as runner
    content = content or runner.ALL_CONTENT
    from sts2_env.az.model_factory import save_transformer_checkpoint
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    champion, _ = runner.load_transformer_checkpoint(out/'initial.pt', runner.TIER, content, runner.V7)
    before = {k: v.clone() for k, v in champion.state_dict().items()}
    kwargs = dict(learning_rate=3e-4, batch_size=8, updates=2, seed=123, value_weight=.1)
    def save(model, state):
        index = len(state['history'])
        save_transformer_checkpoint(out/f'smoke-update-{index:03}.pt', model, f'native-pilot-smoke-{index}',
            config={'native_collection_pilot': replay.compatibility, 'formal_training': False}, training_state=state)
    learner, history = runner.update(champion, replay, on_update=save, **kwargs)
    boundary, payload = runner.load_transformer_checkpoint(out/'smoke-update-001.pt', runner.TIER, content, runner.V7)
    resumed, resumed_history = runner.update(boundary, replay, resume_state=payload['training_state'], **kwargs)
    if (history != resumed_history or any(not torch.equal(v, resumed.state_dict()[k]) for k, v in learner.state_dict().items())
            or any(not torch.equal(v, champion.state_dict()[k]) for k, v in before.items())):
        raise AssertionError('Learner recovery or champion isolation changed')
    if runner.promotion(baseline_rows, baseline_rows, len(baseline_rows))[0]:
        raise AssertionError('Unchanged baseline incorrectly promoted')
    return dict(updates=2, metrics=history, exact_update_resume=True, champion_unchanged=True,
                champion_checkpoint='initial.pt', learner_checkpoint='smoke-update-002.pt',
                candidate_evaluation='not_run_engineering_smoke', formal_training=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-repo', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[1, 2, 3])
    parser.add_argument('--hp', type=int, nargs='+', default=[40, 80])
    parser.add_argument('--budget-ms', type=int, default=100)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--smoke-update', action='store_true')
    args = parser.parse_args()
    from sts2_env.az.config import content_hash, atomic_json
    from sts2_env.az.native_pilot import NativeReplayBuffer, to_episode
    repo, out = args.native_repo.resolve(), args.out.resolve()
    if (not 1 <= len(args.seeds)*len(args.hp) <= 8 or len(set(args.seeds)) != len(args.seeds)
            or len(set(args.hp)) != len(args.hp) or any(h < 1 or h > 80 for h in args.hp)
            or not 50 <= args.budget_ms <= 1000):
        raise ValueError('Unique bounded pilot cases required')
    model_sha = sha(args.checkpoint)
    settings = dict(seeds=args.seeds, hp=args.hp, budget_ms=args.budget_ms,
                    model_sha256=model_sha, provenance=provenance(repo), native_scope='BYRDONIS_ELITE/starter')
    identity = content_hash(settings)
    if out.exists():
        if not args.resume or json.loads((out/'config.json').read_text()) != settings:
            raise ValueError('Use a fresh output or resume with identical model/source/settings')
    else:
        if args.resume:
            raise ValueError('Nothing to resume')
        out.mkdir(parents=True)
        atomic_json(out/'config.json', settings)
        shutil.copyfile(args.checkpoint, out/'initial.pt')
    if sha(out/'initial.pt') != model_sha:
        raise ValueError('Frozen collection checkpoint changed')
    cases = []
    for seed in args.seeds:
        for hp in args.hp:
            for arm in (('policy', 'uct', 'puct') if seed % 2 else ('puct', 'uct', 'policy')):
                cases.append(dict(seed=seed, hp=hp, arm=arm, split='train', output=str(out/f'{arm}-{seed}-{hp}.json')))
    missing = []
    for spec in cases:
        path = Path(spec['output'])
        if path.exists():
            check_case(json.loads(path.read_text()), identity, model_sha, spec, args.budget_ms)
        else:
            missing.append(spec)
    atomic_json(out/'progress.json', dict(status='collecting', total=len(cases), cached=len(cases)-len(missing)))
    started = perf_counter()
    if missing:
        atomic_json(out/'job.json', dict(source=str(ROOT), checkpoint=str(out/'initial.pt'),
            modelSha256=model_sha, identity=identity, budgetMs=args.budget_ms, cases=missing))
        env = dict(os.environ, STS2_COLLECTION_PILOT_JOB=str(out/'job.json'))
        shell = shutil.which('pwsh') or shutil.which('powershell.exe')
        if shell is None:
            raise RuntimeError('PowerShell is required for the Windows native worker')
        command = [shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(repo/'scripts/native-worker.ps1'),
                   '-GameDir', str(args.game.resolve()), '-Mode', 'collection-pilot', '-TimeoutSeconds', '240']
        if not args.build:
            command.append('-SkipBuild')
        with (out/'worker.log').open('a', encoding='utf-8') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            atomic_json(out/'progress.json', dict(status='failed', error='See worker.log; completed fights retained'))
            raise RuntimeError('Native pilot failed; see worker.log')
    raws = []
    for spec in cases:
        raw = json.loads(Path(spec['output']).read_text())
        check_case(raw, identity, model_sha, spec, args.budget_ms)
        raws.append(raw)
    replay = NativeReplayBuffer(out/'replay')
    for raw in raws:
        if raw['arm'] == 'puct':
            replay.commit(to_episode(raw))
    summaries, comparisons, baseline = summarize(raws)
    report = dict(identity=identity, settings=settings, arms=summaries, paired_vs_policy=comparisons,
        replay_rows=replay.size, replay_episodes=len(replay.episodes), native_worker_wall_seconds=perf_counter()-started,
        state_action_checks=sum(len(r['steps']) for r in raws), teacher_information='native_checkpoint_privileged',
        formal_training_started=False, held_out_test_opened=False,
        limitations=['Single encounter/starter cards', 'Privileged teacher; public model inputs',
                    'Time-budget search is not seed-only deterministic', 'Not a paired Python/native environment comparison'])
    if args.smoke_update:
        report['training_smoke'] = training_smoke(out, replay, baseline)
    atomic_json(out/'report.json', report)
    atomic_json(out/'progress.json', dict(status='completed', complete=len(cases), total=len(cases)))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
