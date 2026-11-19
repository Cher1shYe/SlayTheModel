"""Evaluate sh02v17 on v14 A9 with only the final boss combat played."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing as mp
from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'train'))
from a9.adapter import RULESET, WEIGHT_SHA256, choose, load_model, observe, step_policy_action
from a9.loop_penalty import visit

FIRST_SEED = 7540000
MAX_STEPS = 3000


def setup(weight):
    global sim, model
    from spire_rl.sim import sim
    torch.set_num_threads(1)
    model = load_model(weight, sim)
    if not hasattr(sim.RunContext, 'init_final_boss_evaluation'):
        raise RuntimeError('rebuild the SF2 v14 simulator to enable final-boss evaluation')


def evaluate(seed):
    rc = sim.RunContext()
    rc.init_final_boss_evaluation(seed, 9)
    visited = {}
    result = dict(seed=seed, won=False, reason='decision_limit', decisions=0,
                  boss=None, combat_decisions=0)
    for step in range(MAX_STEPS):
        combat = rc.screen == sim.RunScreen.COMBAT
        if combat:
            if rc.act != 2 or not rc.combat_is_boss:
                raise AssertionError(f'non-final combat on seed {seed}')
            result['boss'] = int(rc.boss_encounter)
        obs, actions = observe(rc, sim)
        state = dict(act=int(rc.act), floor=int(rc.floor), fight=int(rc.combats_fought), combat=combat)
        if step and visit(visited, obs, state, .25, 16, 64)[1]:
            result.update(reason='loop', pending_op=rc.battle.pending_info[0] if combat else 0,
                          grid_kind=rc.card_grid_kind)
            break
        action = actions[choose(model, obs, seed * 3001 + step)]
        # Preserve unsupported simulator outcomes separately from game losses.
        try:
            accepted = step_policy_action(rc, sim, action)
        except (RuntimeError, OverflowError) as exc:
            result.update(reason='simulator_error', error=str(exc), action=action)
            break
        if not accepted:
            raise AssertionError(f'v14 rejected its legal action {action} on seed {seed}')
        result['decisions'] += 1
        result['combat_decisions'] += int(combat)
        if rc.is_terminal:
            result.update(won=bool(rc.won), reason='simulator_truncation' if rc.truncated else 'terminal')
            break
    result['screen'] = rc.screen.name
    result['floor'] = int(rc.floor)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--init', required=True)
    p.add_argument('--out', required=True, type=Path, help='new per-seed JSONL file')
    p.add_argument('--count', type=int, default=500)
    p.add_argument('--workers', type=int, default=8)
    cfg = p.parse_args()
    if not 1 <= cfg.count <= 500 or cfg.workers < 1:
        p.error('expected count 1..500 and positive workers')
    setup(cfg.init)
    reasons = Counter()
    wins = entered = 0
    with cfg.out.open('x', encoding='utf-8') as out, ProcessPoolExecutor(
            cfg.workers, mp_context=mp.get_context('spawn'),
            initializer=setup, initargs=(cfg.init,)) as pool:
        for i, row in enumerate(pool.map(evaluate, range(FIRST_SEED, FIRST_SEED + cfg.count)), 1):
            out.write(json.dumps(row) + '\n')
            out.flush()
            wins += row['won']
            entered += bool(row['combat_decisions'])
            reasons[row['reason']] += 1
            if i % 50 == 0:
                print(f'{i}/{cfg.count}, wins={wins}', flush=True)
    print(json.dumps(dict(ruleset=RULESET, weight_sha256=WEIGHT_SHA256,
                          seeds=cfg.count, wins=wins, entered=entered, reasons=reasons)))


if __name__ == '__main__':
    main()

