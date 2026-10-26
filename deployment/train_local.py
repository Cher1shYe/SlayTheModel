"""Isolated Windows launch of upstream trainers; no existing run is overwritten."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = {
    'armg': 'armG_train_parallel.py', 'arms': 'armS_train_parallel.py',
    'bc': 'armB_train_parallel.py', 'attn': 'armB_attn_train.py',
    'value': 'armB_value_train.py', 'dagger': 'armB_dagger.py',
    'rl': 'armB_rl.py', 'selfplay': 'armB_selfplay.py',
}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pipeline', choices=ENTRIES)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--games', type=int, default=300)
    p.add_argument('--epochs', type=int, default=8)
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--batch', type=int, default=32)
    p.add_argument('--simulations', type=int, default=2000)
    p.add_argument('--search-sims', type=int, default=100)
    p.add_argument('--eval-every', type=int, default=400)
    p.add_argument('--smoke', action='store_true', help='2 training games, 2 eval seeds, 1 epoch/round, 2 workers, cheap search')
    a = p.parse_args()
    if a.smoke:
        a.games, a.epochs, a.rounds, a.workers, a.batch = 2, 1, 1, 2, 2
        a.simulations, a.search_sims, a.eval_every = 10, 4, 2
    for k in ('games','epochs','rounds','workers','batch','simulations','search_sims','eval_every'):
        if getattr(a,k) < 1: p.error(k + ' must be positive')
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = ROOT / 'sts-rl-agent'
    for folder in ('agent', 'combat_experiments'):
        for source in (repo / folder).glob('*.py'):
            code = source.read_text(encoding='utf-8')
            # Fail loudly instead of silently accepting incomplete trajectories.
            code = re.sub(r'except Exception:\s*pass[^\n]*', 'except Exception:\n        raise', code)
            # BARRICADE is a flag in the native simulator, not an integer statusMap entry.
            code = code.replace('p.get_status(s)', '(int(p.has_status(s)) if s == sts.PlayerStatus.BARRICADE else p.get_status(s))')
            code = re.sub(r'(?m)^(\s*)bc.exit_battle\(gc\)', r'\1if bc.outcome == sts.Outcome.UNDECIDED: raise RuntimeError("Battle truncated before terminal")\n\1bc.exit_battle(gc)', code)
            code = re.sub(r'(?m)^(    )return \{"seed":', r'\1if gc.outcome == sts.GameOutcome.UNDECIDED: raise RuntimeError("Run truncated before terminal")\n\1return {"seed":', code)
            if source.name == 'armS_train.py':
                # The parallel trainer never uses the optional dashboard logger.
                code = code.replace('import obs\n', '')
                code = code.replace('def log_run(tag, seed, rep, oc):', 'def log_run(tag, seed, rep, oc):\n    import obs  # optional legacy dashboard only')
            (out / source.name).write_text(code, encoding='utf-8')
    shutil.copy2(repo / 'agent/armS_card_vocab.json', out)
    seeds = (repo / 'eval/eval_seeds_50.txt').read_text(encoding='utf-8').splitlines()
    seeds = [s for s in seeds if s.strip() and not s.startswith('#')]
    (out / 'eval_seeds_50.txt').write_text('\n'.join(seeds[:2] if a.smoke else seeds) + '\n')
    for w in (repo / 'weights').glob('*.pt'): shutil.copy2(w, out)
    temp = out / 'tmp'; temp.mkdir()
    env = os.environ.copy()
    env.update(STS_BOT_DIR=str(out), PYTHONPATH=os.pathsep.join([str(ROOT/'simulator/build312/Release'),str(out)]),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
               TEMP=str(temp), TMP=str(temp), PROG_TAG='local', STS_SIM_COUNT=str(a.simulations),
               N_SIMS=str(a.search_sims), EVAL_EVERY=str(a.eval_every), ASC='0',
               ARM_G_ARCH='128,128', ARM_S_ARCH='128,128', ARM_B_ARCH='256,256', VAL_ARCH='256,256',
               INIT='armB_model_B256x256.pt')
    if a.pipeline in ('armg','arms','rl'): args = [a.games,a.workers,a.batch]
    elif a.pipeline in ('dagger','selfplay'): args = [a.rounds,a.games,a.epochs,a.workers]
    else: args = [a.games,a.epochs,a.workers]
    command = [sys.executable, '-u', str(out/ENTRIES[a.pipeline]), *map(str,args)]
    config = {**vars(a), 'out':str(out), 'command':command,
              'local_changes':['strict exceptions','BARRICADE flag encoding','reject incomplete battles/runs','lazy legacy dashboard import'], 'eval_seed_count':2 if a.smoke else len(seeds)}
    (out/'config.json').write_text(json.dumps(config, indent=2),encoding='utf-8')
    start = time.perf_counter()
    with (out/'train.log').open('w',encoding='utf-8') as log:
        result = subprocess.run(command, env=env, cwd=out, stdout=log, stderr=subprocess.STDOUT)
    (out/'status.json').write_text(json.dumps({'exit_code':result.returncode,'seconds':time.perf_counter()-start},indent=2))
    print((out/'train.log').read_text(encoding='utf-8'))
    raise SystemExit(result.returncode)

if __name__ == '__main__':
    main()
