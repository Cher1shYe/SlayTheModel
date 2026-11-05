"""Run final-boss replay in isolated old/new simulator processes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True); p.add_argument('--out-dir', required=True)
    p.add_argument('--old-simulator', required=True); p.add_argument('--new-simulator', required=True)
    p.add_argument('--workers', type=int, default=8)
    a = p.parse_args()
    src = Path(a.source).resolve(strict=True)
    old = Path(a.old_simulator).resolve(strict=True); new = Path(a.new_simulator).resolve(strict=True)
    config = json.loads((src / 'config.json').read_text(encoding='utf-8'))
    if sha(old) != config['simulator_sha256']:
        raise RuntimeError('old simulator does not match original evaluation')
    if sha(src / 'combat_policy.pt') != config['combat_sha256']:
        raise RuntimeError('combat policy does not match original evaluation')
    out = Path(a.out_dir).resolve(); out.mkdir(parents=True, exist_ok=False)
    metadata = {'original_evaluation':str(src), 'original_config_sha256':sha(src/'config.json'),
                'original_records_sha256':sha(src/'episodes.jsonl'), 'combat_policy_sha256':sha(src/'combat_policy.pt'),
                'armg_weights_sha256':{arm:sha(src/(arm+'_weights.pt')) for arm in ('start','r640','r960')},
                'old_simulator':str(old), 'old_simulator_sha256':sha(old), 'new_simulator':str(new),
                'new_simulator_sha256':sha(new), 'workers':a.workers, 'final_boss_potion_weight':0.0}
    (out/'config.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    for phase, module in (('capture',old),('retry',new)):
        env = os.environ.copy(); env['STS2_PRIOR_PYD'] = str(module)
        cmd=[sys.executable,'-u','-m','deployment.replay_final_boss','--phase',phase,'--source',str(src),
             '--out-dir',str(out),'--workers',str(a.workers)]
        print('Starting '+phase,flush=True)
        result=subprocess.run(cmd,env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
    print('Finished both phases',flush=True)


if __name__ == '__main__': main()
