"""Isolated 1/2/4-worker collection benchmark; never trains or promotes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from scripts.benchmark_native_collection import summarize
from sts2_env.az.config import atomic_json
from sts2_env.az.native_generic_backend import NativeBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 2, 4])
    parser.add_argument('--batches', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.batches <= 16 or any(w not in (1, 2, 4, 8) or w > args.batches for w in args.workers):
        parser.error('Use 1/2/4/8 workers and at least as many batches (maximum 16)')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    previous = Path('output/native_collection_speed_20261019')
    config = json.loads((previous/'config.json').read_text())
    protocol = json.loads((previous/'protocol.json').read_text())
    recipes = json.loads((previous/'recipes.json').read_text())
    checkpoint = out/'initial.pt'
    shutil.copyfile(previous/'initial.pt', checkpoint)
    cfg = dict(config['backend'], fights_per_worker=2)
    backend = NativeBackend(cfg, protocol, out)
    backend.configure_search('mixed', .5)
    atomic_json(out/'config.json', config)
    atomic_json(out/'recipes.json', recipes)
    report = dict(formal_training_started=False, budget_ms=250, mode='mixed',
                  value_mix=.5, fights_per_process=2, arms={})
    atomic_json(out/'progress.json', dict(stage='build'))
    job = out/'build-job.json'
    atomic_json(job, dict(format=backend.format, catalogOutput=str(out/'catalog.json')))
    backend._execute(job, out/'build.log')

    def run_batch(arm, index):
        directory = out/arm/f'batch-{index}'
        directory.mkdir(parents=True)
        project = directory/'project'
        project.mkdir()
        source = backend.repo/'tools/Sts2.NativeWorker'
        for name in ('Worker.tscn', 'Worker.cs'):
            shutil.copyfile(source/name, project/name)
        settings = (source/'project.godot').read_text().replace(
            'config/custom_user_dir_name="SlayTheModelWorker"',
            f'config/custom_user_dir_name="SlayTheModelBench/{out.name}/{arm}/{index}"')
        (project/'project.godot').write_text(settings)
        (project/'.godot').mkdir()
        (project/'.godot/global_script_class_cache.cfg').write_text('list=Array[Dictionary]([])')
        instance = NativeBackend(cfg, protocol, directory)
        instance.configure_search('mixed', .5)
        def execute(job, log):
            env = dict(os.environ, STS2_COLLECTION_PILOT_JOB=str(job),
                       STS2_GAME_PACK=str(backend.game/'SlayTheSpire2.pck'),
                       STS2_WORKER_MODE='collection-pilot')
            command = [str(backend.repo/'artifacts/native-host/NativeWorker.exe'),
                       '--headless', '--path', str(project), '--log-file', str(directory/'godot.log')]
            with Path(log).open('w', encoding='utf-8') as stream:
                process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    code = process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                    raise RuntimeError(f'Worker timed out: {log}')
                if code:
                    raise RuntimeError(f'Worker exit {code}: {log}')
        instance._execute = execute
        return instance.fights(checkpoint, recipes[(index%2)*2:(index%2)*2+2], directory/'fights', 'puct')

    for workers in args.workers:
        arm = f'workers-{workers}'
        stop = threading.Event()
        samples = []
        def sample():
            parent = psutil.Process()
            while not stop.wait(.5):
                rss = 0
                for process in parent.children(recursive=True):
                    try: rss += process.memory_info().rss
                    except psutil.Error: pass
                samples.append((psutil.cpu_percent(), psutil.virtual_memory().available, rss))
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        start = perf_counter()
        raws = []
        try:
            atomic_json(out/'progress.json', dict(stage=arm, completed_fights=0, total_fights=args.batches*2))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(run_batch, arm, i) for i in range(args.batches)]
                for future in as_completed(futures):
                    raws.extend(future.result())
                    atomic_json(out/'progress.json', dict(stage=arm, completed_fights=len(raws), total_fights=args.batches*2))
        finally:
            stop.set()
            monitor.join()
        row = summarize(raws, perf_counter()-start, args.batches)
        row['resources'] = dict(cpu_percent_mean=sum(s[0] for s in samples)/len(samples),
                               available_gib_min=min(s[1] for s in samples)/2**30,
                               children_rss_gib_peak=max(s[2] for s in samples)/2**30)
        report['arms'][arm] = row
        atomic_json(out/'report.json', report)
        print(arm, json.dumps(row), flush=True)
    atomic_json(out/'progress.json', dict(stage='completed', report=report))


if __name__ == '__main__':
    main()
