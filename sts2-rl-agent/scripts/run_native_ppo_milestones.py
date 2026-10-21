"""Run bounded PPO with strict greedy evaluation at each permanent milestone."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_native_collection import sha
from sts2_env.az.config import atomic_json
from sts2_env.az.native_platform import lock_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    base = args.experiment.resolve()
    held = lock_run(base/'pipeline.lock')
    config = json.loads((base/'config.json').read_text())
    protocol = json.loads((base/'protocol.json').read_text())
    view = dict(status='running', stage='starting', pid=os.getpid(), target=2048,
                learning_rate=config['learning_rate'], kl_scope=config['kl_scope'])
    evaluation = None

    def publish():
        training = base/'progress.json'
        view['training'] = json.loads(training.read_text()) if training.exists() else None
        milestones = {}
        for count in (512, 1024, 1536, 2048):
            directory = base/'evaluations'/str(count)
            p = directory/'progress.json'
            milestones[str(count)] = json.loads(p.read_text()) if p.exists() else dict(status='waiting', completed=0, total=296)
        view['evaluations'] = milestones
        view['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(base/'pipeline-detail.json', view)
        training = view.get('training') or {}
        compact = dict(status=view['status'], stage=view['stage'],
            collected=training.get('battles_completed', 0), trained=training.get('battles_trained', 0),
            target=2048, updates=training.get('updates', 0), evaluations={})
        for count, item in milestones.items():
            entry = dict(completed=item.get('completed', 0), total=296, status=item['status'])
            if item.get('results'):
                entry.update(win_rate=item['results']['win_rate'], v7=item['results']['mean_utility'])
            compact['evaluations'][count] = entry
        compact['updated_at'] = view['updated_at']
        if view.get('error'):
            compact['error'] = 'See pipeline-detail.json and stderr logs'
        atomic_json(base/'milestone-progress.json', compact)

    def run(command, directory, label):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        with (directory/f'{label}-{stamp}.stdout.log').open('w', encoding='utf8') as out, (directory/f'{label}-{stamp}.stderr.log').open('w', encoding='utf8') as err:
            child = subprocess.Popen(command, stdout=out, stderr=err,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            view['child_pid'] = child.pid
            while child.poll() is None:
                publish()
                time.sleep(5)
            if child.returncode:
                raise RuntimeError(f'{label} exited {child.returncode}; see {directory}/{label}-{stamp}.stderr.log')

    try:
        for count in (512, 1024, 1536, 2048):
            if (base/'STOP').exists():
                view.update(status='paused')
                return
            checkpoint = base/'checkpoints'/f'battles-{count:09d}.pt'
            view.update(milestone=count)
            if not checkpoint.exists():
                view.update(stage='training')
                command = [sys.executable, '-u', str(base/'python/scripts/run_native_ppo.py'),
                           '--experiment', str(base), '--max-cycles', str(count//config['rollout_battles'])]
                if (base/'latest.pt').exists():
                    command.append('--resume')
                run(command, base, f'training-{count}')
                progress = json.loads((base/'progress.json').read_text())
                if progress['status'] == 'paused':
                    view.update(status='paused')
                    return
                if progress['status'] != 'completed' or progress['battles_trained'] != count or not checkpoint.exists():
                    raise ValueError('Training milestone/checkpoint mismatch')
            evaluation = base/'evaluations'/str(count)
            frozen = evaluation/'model.pt'
            if frozen.exists():
                if sha(frozen) != sha(checkpoint):
                    raise ValueError('Evaluation checkpoint changed')
            else:
                shutil.copy2(checkpoint, frozen)
            metadata = dict(source=str(checkpoint), sha256=sha(checkpoint), tier='S', trained_battles=count)
            if (evaluation/'model.json').exists() and json.loads((evaluation/'model.json').read_text()) != metadata:
                raise ValueError('Evaluation metadata changed')
            atomic_json(evaluation/'model.json', metadata)
            if not (evaluation/'report.json').exists():
                view.update(stage='evaluation')
                run([sys.executable, '-u', str(evaluation/'run.py')], evaluation, 'evaluation')
            report = json.loads((evaluation/'report.json').read_text())
            if report['model'] != metadata or report['protocol_sha256'] != protocol['manifest_sha256'] or report['results']['episodes'] != 296:
                raise ValueError('Evaluation report identity/count mismatch')
        view.update(status='completed', stage='completed')
    except BaseException:
        view.update(status='failed', error=traceback.format_exc())
        raise
    finally:
        publish()
        held.close()


if __name__ == '__main__':
    main()
