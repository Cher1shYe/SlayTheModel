"""Replay the old trajectory, snapshot its final boss, then retry that battle.

Run capture under the original simulator; run retry in a fresh process with
the new simulator. All source snapshots and original episode records are read
only. Only cases with a verified complete old replay are retried.
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import multiprocessing as mp
import time

import numpy as np
import torch
from deployment import evaluate_battle_root_prior as root
from deployment import evaluate_armg_floor_root_puct as original
import agent.armg_train as base
from agent.armg import ArmGScorer
from agent.common import combat_action_arrays, public_combat_observation, sim
from agent.armg_floor_schedule import combat_budget, is_final_boss

ARMS = original.ARMS
_model = None
_version = None
_src = None


def _worker_init(source):
    global _src
    _src = Path(source)
    original._init_worker(str(_src / 'combat_policy.pt'))


def _load_model(arm):
    global _model, _version
    if _model is None:
        _model = ArmGScorer().eval()
    if _version != arm:
        _model.load_state_dict(torch.load(_src / (arm + '_weights.pt'), map_location='cpu', weights_only=True))
        _version = arm
    return _model


def _capture(record, out_dir):
    model = _load_model(record['arm'])
    controller = original.FloorRootPuctController(record['search_seed'])
    captured = []

    def before_combat(rc, steps):
        # This experiment was A0, where floor 48 is the single final boss.
        if is_final_boss(rc) and int(rc.floor) == 48 and not captured:
            captured.append((bytes(rc.snapshot()), controller.decisions, steps, int(rc.state_hash())))

    old_plan = base._mcts_plan
    base._mcts_plan = controller.plan
    try:
        replay = base.collect_episode(record['seed'], model, deterministic=True,
            combat='mcts-oracle', simulations=2000, epsilon=0.05, max_steps=5000,
            ascension=0, need_rules=False, relic_rules=False,
            combat_budget_by_context=controller.budget_for_context, before_combat=before_combat)
    finally:
        base._mcts_plan = old_plan
    keys = ('status', 'won', 'floor', 'hp', 'steps', 'cycle_recoveries', 'mcts_searches', 'mcts_simulations')
    diff = {k: {'original': record.get(k), 'replay': replay.get(k)}
            for k in keys if record.get(k) != replay.get(k)}
    for key in ('normal_decisions', 'elite_decisions', 'boss_decisions'):
        actual = getattr(controller, key)
        if record.get(key) != actual:
            diff[key] = {'original': record.get(key), 'replay': actual}
    if diff or len(captured) != 1:
        raise RuntimeError(f"old trajectory replay did not match record: {diff}, boss snapshots={len(captured)}")
    snapshot, decisions, steps, state_hash = captured[0]
    path = Path(out_dir) / 'snapshots' / f"{record['arm']}-{record['seed']}.bin"
    path.write_bytes(snapshot)
    return {'arm': record['arm'], 'seed': record['seed'], 'search_seed': record['search_seed'],
            'snapshot': str(path), 'snapshot_sha256': hashlib.sha256(snapshot).hexdigest(),
            'state_hash': state_hash, 'decisions_before_boss': decisions, 'step_at_boss': steps,
            'original': record}


def _retry(meta, potion_weight=0.0):
    model = _load_model(meta['arm'])
    blob = Path(meta['snapshot']).read_bytes()
    if hashlib.sha256(blob).hexdigest() != meta['snapshot_sha256']:
        raise RuntimeError('snapshot checksum mismatch')
    rc = sim.RunContext()
    if not rc.restore(blob):
        raise RuntimeError('snapshot restore failed')
    if int(rc.floor) != 48 or not is_final_boss(rc) or int(rc.state_hash()) != meta['state_hash']:
        raise RuntimeError('restored state does not match captured final boss')
    count = int(meta['decisions_before_boss'])
    final_decisions = 0
    steps = 0
    while rc.screen == sim.RunScreen.COMBAT:
        steps += 1
        if steps > 5000:
            raise RuntimeError('final combat exceeded step cap')
        battle = rc.battle
        legal = [tuple(int(x) for x in a) for a in battle.legal_actions()]
        if not legal:
            raise RuntimeError('no legal final boss action')
        if len(legal) == 1:
            action = legal[0]
        else:
            action_rows, feats = combat_action_arrays(battle)
            action_rows = [tuple(int(x) for x in a) for a in action_rows]
            if action_rows != legal:
                raise RuntimeError('legal action/feature mismatch')
            obs = public_combat_observation(battle)
            with torch.inference_mode():
                logits = root._policy(torch.from_numpy(obs)[None], torch.from_numpy(feats)[None])[0]
                if logits.shape != (len(legal),) or not torch.isfinite(logits).all():
                    raise RuntimeError('invalid policy logits')
                priors = torch.softmax(logits, 0).tolist()
            search_seed = (int(meta['search_seed']) + 7919 * count) & 0xFFFFFFFF
            count += 1; final_decisions += 1
            budget = combat_budget(int(rc.floor), boss=True)
            path, done, _ = battle.mcts_priors(budget, legal, priors, 3.0, search_seed,
                                                False, False, 0.05, potion_weight)
            if int(done) != budget or not path:
                raise RuntimeError('incomplete final-boss search')
            action = tuple(int(x) for x in path[0])
            if action not in legal:
                raise RuntimeError('illegal final-boss search action')
        if not rc.step_combat(*action):
            raise RuntimeError('final-boss action rejected')
    # A final-boss modifier can leave a reward screen before RUN_OVER.
    # Select post-battle options using the same greedy ArmG policy.
    seen = deque(maxlen=64)
    while rc.screen != sim.RunScreen.RUN_OVER:
        steps += 1
        if steps > 5000:
            raise RuntimeError('final-boss continuation exceeded step cap')
        obs, actions, features = base.build_candidates(rc)
        if not actions:
            raise RuntimeError('no legal post-boss action')
        with torch.inference_mode():
            logits = model(torch.from_numpy(obs)[None], torch.from_numpy(features)[None])[0]
        choice = int(torch.argmax(logits)) if len(actions) > 1 else 0
        fingerprint = hashlib.blake2b(digest_size=16)
        fingerprint.update(obs.tobytes()); fingerprint.update(features.tobytes()); fingerprint.update(repr(actions).encode())
        key = fingerprint.digest(); repeats = seen.count(key); seen.append(key)
        if repeats >= 3 and len(actions) > 1:
            order = sorted(range(len(actions)), key=lambda i: -float(logits[i]))
            order = [choice] + [i for i in order if i != choice]
            choice = order[1 + ((repeats - 3) % (len(order) - 1))]
        if not rc.step(*actions[choice]):
            raise RuntimeError('post-boss action rejected')
    return {'arm': meta['arm'], 'seed': meta['seed'], 'won': bool(rc.won), 'floor': int(rc.floor),
            'hp': int(rc.hp), 'final_decisions': final_decisions, 'final_steps': steps,
            'original_won': bool(meta['original']['won']), 'original_hp': meta['original']['hp']}


def _verify_and_retry(meta):
    control = _retry(meta, 4.0)
    expected = meta['original']
    mismatch = {k: {'original': expected[k], 'control': control[k]}
                for k in ('won', 'floor', 'hp') if expected[k] != control[k]}
    expected_steps = expected['steps'] - meta['step_at_boss'] + 1
    if control['final_steps'] != expected_steps:
        mismatch['final_steps'] = {'original': expected_steps, 'control': control['final_steps']}
    expected_decisions = expected['mcts_searches'] - meta['decisions_before_boss']
    if control['final_decisions'] != expected_decisions:
        mismatch['final_decisions'] = {'original': expected_decisions, 'control': control['final_decisions']}
    if mismatch:
        raise RuntimeError(f'new simulator with weight 4 differs from original boss: {mismatch}')
    result = _retry(meta, 0.0)
    result['verified_old_weight'] = True
    return result


def _atomic(path, data):
    path = Path(path); temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def _boss_cases(records):
    """A0 evaluation has its sole final boss on floor 48; keep all its results."""
    return [record for record in records if record['floor'] == 48]


def run_phase(phase, source, out_dir, workers):
    source, out = Path(source).resolve(strict=True), Path(out_dir).resolve(strict=True)
    original_records = [json.loads(x) for x in (source / 'episodes.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    if len(original_records) != 300 or any(x['status'] != 'terminated' for x in original_records):
        raise ValueError('source evaluation must have 300 completed episodes')
    selected = _boss_cases(original_records)
    if phase == 'capture':
        tasks = selected
        (out / 'snapshots').mkdir(exist_ok=True)
    else:
        tasks = [json.loads(x) for x in (out / 'capture.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        if len(tasks) != len(selected):
            raise ValueError('capture incomplete; retry refused')
    results = []; start = time.monotonic()
    def save(state, error=None):
        summary = {'phase': phase, 'state': state, 'done': len(results), 'total': len(tasks),
                   'elapsed_seconds': round(time.monotonic()-start, 1), 'updated_utc': datetime.now(timezone.utc).isoformat()}
        if error: summary['error'] = error
        _atomic(out / 'progress.json', summary)
        label = '重放原对局并保存 Boss 战前状态' if phase == 'capture' else '使用新评分重打 Boss'
        text = f"# 最终 Boss 药水评分重测\n\n- 状态：{state}\n- 阶段：{label}\n- 进度：{len(results)} / {len(tasks)}\n- worker：{workers}\n- 原始评测：每个模型 100 局；未到达最终 Boss 的局沿用原结果\n- 更新时间（UTC）：{summary['updated_utc']}\n"
        if error: text += f'- 错误：{error}\n'
        tmp = out / 'progress.md.tmp'; tmp.write_text(text, encoding='utf-8'); os.replace(tmp, out / 'progress.md')
    save('running')
    try:
        with (out / (phase+'.jsonl')).open('x', encoding='utf-8', buffering=1) as stream:
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                                     initializer=_worker_init, initargs=(str(source),)) as pool:
                pending = set()
                iterator = iter(tasks)
                def submit_next():
                    t = next(iterator, None)
                    if t is None:
                        return False
                    pending.add(pool.submit(_capture, t, str(out)) if phase == 'capture' else pool.submit(_verify_and_retry, t))
                    return True
                for _ in range(workers):
                    if not submit_next(): break
                while pending:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    for f in done:
                        item = f.result(); results.append(item)
                        stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False)+'\n'); stream.flush()
                        save('running')
                        submit_next()
        save('completed')
    except BaseException as exc:
        save('failed', f'{type(exc).__name__}: {exc}')
        raise
    if phase == 'retry':
        by_arm = {}
        for arm in ARMS:
            orig = [r for r in original_records if r['arm'] == arm]
            changed = [r for r in results if r['arm'] == arm]
            before = sum(bool(r['won']) for r in orig)
            gain = sum(not r['original_won'] and r['won'] for r in changed)
            loss = sum(r['original_won'] and not r['won'] for r in changed)
            by_arm[arm] = {'games': len(orig), 'boss_replayed':len(changed), 'wins_before':before,
                           'wins_after':before+gain-loss, 'gained_wins':gain, 'lost_wins':loss}
        old_config = json.loads((source / 'config.json').read_text(encoding='utf-8'))
        _atomic(out / 'summary.json', {'arms':by_arm, 'replayed':len(results), 'source':str(source),
                                      'old_simulator_sha256':old_config['simulator_sha256'],
                                      'new_simulator_sha256':original.sha(root._extension),
                                      'note':'original trajectory replays checked against recorded summaries; original boss snapshots were not recorded'})
        names = {'start':'原训练起点', 'r640':'本次训练 640 局', 'r960':'本次训练 960 局'}
        lines = ['# 最终 Boss 药水评分重测', '', '- 状态：已完成', f'- 成功重打：{len(results)} 场最终 Boss',
                 '- 未进入最终 Boss 的局沿用原结果。', '',
                 '| 模型 | 总局数 | 重打 Boss 局数 | 原通关数 | 新通关数 | 新增胜局 | 新增败局 |',
                 '|---|---:|---:|---:|---:|---:|---:|']
        for arm in ARMS:
            a = by_arm[arm]
            lines.append(f"| {names[arm]} | {a['games']} | {a['boss_replayed']} | {a['wins_before']} | {a['wins_after']} | {a['gained_wins']} | {a['lost_wins']} |")
        lines += ['', '原始战前状态未保存；旧模拟器重放已逐局核对终局摘要，新模拟器用旧评分重打 Boss 后再核对一次。']
        tmp=out/'progress.md.tmp'; tmp.write_text('\n'.join(lines)+'\n',encoding='utf-8'); os.replace(tmp,out/'progress.md')


def main():
    p=argparse.ArgumentParser(); p.add_argument('--phase', required=True, choices=('capture','retry'))
    p.add_argument('--source', required=True); p.add_argument('--out-dir', required=True); p.add_argument('--workers',type=int,default=8)
    a=p.parse_args(); run_phase(a.phase,a.source,a.out_dir,a.workers)


if __name__ == '__main__': main()
