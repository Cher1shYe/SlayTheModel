"""Re-run the exact round-5 seed list in isolated subprocesses to find the
state that aborted the teacher training worker (stack smashing)."""
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path('/home/doulingfeng/idea/sts')
BASE = [int(x) for x in (ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt')
        .read_text(encoding='utf-8').splitlines() if x.strip() and not x.startswith('#')]
EVAL = set(BASE[:30])
rng = random.Random(20261026)
seeds = []
while len(seeds) < 400:
    s = rng.randint(1, 10 ** 9)
    if s not in EVAL:
        seeds.append(s)
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 200
workers = int(sys.argv[2]) if len(sys.argv) > 2 else 48


def run(seed):
    try:
        p = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'deployment/teacher_one.py'),
                            str(seed)], capture_output=True, text=True, timeout=300)
        return seed, p.returncode, (p.stdout + p.stderr)[-3000:]
    except subprocess.TimeoutExpired:
        return seed, 124, 'timeout'


fails = []
with ThreadPoolExecutor(max_workers=workers) as ex:
    for seed, rc, out in ex.map(run, seeds[:limit]):
        if rc != 0:
            fails.append(dict(seed=seed, rc=rc, out=out))
            print('FAIL seed=%d rc=%d\n%s\n' % (seed, rc, out), flush=True)
print(json.dumps(dict(tested=limit, fails=[(f['seed'], f['rc']) for f in fails],
                      seeds=seeds[:limit]), indent=1), flush=True)
Path(ROOT / 'deployment/runs_v2/soft_diag/crash_probe.json').write_text(
    json.dumps(dict(tested=limit, fails=fails, seeds=seeds[:limit]), indent=1), encoding='utf-8')
