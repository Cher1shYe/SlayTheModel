"""Static monster/encounter inventory. Never loads a model or a mission."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sts2_env.az.config import atomic_json
from sts2_env.az.monster_registry import audit


def main():
    result = audit()
    monsters = result['monsters']
    encounters = result['encounters']
    payload = {
        'version': 'monster-coverage-v1',
        'scope': 'act1-act4 combat encounters from the native encounter tables',
        'criteria': [
            'the current move is readable from the visible intent: no two eligible '
            'successors (or sampled initial moves) share an intent signature',
            'the particle can recreate the same AI state from the public move history',
        ],
        'total_encounters': result['total_encounters'],
        'admitted_encounters': len(result['admitted_encounters']),
        'total_monsters': result['total_monsters'],
        'admitted_monsters': len(result['admitted_monsters']),
        'monsters': {name: {
            'creator': info.creator,
            'moves': list(info.moves),
            'initial_moves': list(info.initial_moves),
            'successors': {k: list(v) for k, v in info.successors},
            'ambiguous_pairs': list(info.ambiguous_pairs),
            'multi_intent_moves': list(info.multi_intent_moves),
            'branch_states': list(info.branch_states),
            'admitted': info.admitted,
        } for name, info in monsters.items()},
        'encounters': encounters,
    }
    atomic_json(ROOT / 'docs/monster_coverage.json', payload)

    lines = ['# 怪物与遭遇覆盖清单', '',
             f"范围：act1–act4 原生战斗遭遇 {result['total_encounters']} 个；"
             f"当前通用公开状态可接入 **{len(result['admitted_encounters'])}**，"
             f"待处理 **{result['total_encounters'] - len(result['admitted_encounters'])}**。", '',
             '接入判据（静态、可复算）：', '',
             '1. 当前招式可由“可见意图”唯一确定：没有两个可及后继（含初始招式的采样）显示相同意图签名；',
             '2. 粒子能用公开招式历史重建同一个 AI 状态（不读取隐藏状态机字段、RNG 或未来分支）。', '',
             '`TEST_SUBJECT` 的三形态由既有 `boss_phases` 专用契约处理，因此不进入通用判据。', '',
             '| 幕 | 遭遇 | 原生阵容 | 通用接入 | 阻塞原因 |', '|---|---|---|---|---|']
    for name in sorted(encounters):
        entry = encounters[name]
        rosters = ' / '.join('+'.join(r) for r in entry['rosters']) or '—'
        blockers = []
        if entry['error']:
            blockers.append('setup_error:' + ':'.join(entry['error']))
        for monster in entry['monsters']:
            info = monsters.get(monster)
            if info is None:
                blockers.append(f'{monster}:no-factory')
            elif not info.admitted:
                blockers.append(f'{monster}:ambiguous-intent')
        lines.append(f"| {entry['act'] or '—'} | {name} | {rosters} | "
                     f"{'是' if entry['admitted'] else '否'} | {'; '.join(blockers) or '—'} |")
    lines += ['', '## 怪物逐项', '',
              '| 怪物 | 招式数 | 初始候选 | 歧义对 | 多意图招式 | 通用接入 |',
              '|---|---:|---|---|---:|---|']
    for name in sorted(monsters):
        info = monsters[name]
        pairs = '; '.join(f'{a}->{b}/{c}' for a, b, c in info.ambiguous_pairs[:4]) or '—'
        lines.append(f"| {name} | {len(info.moves)} | {len(info.initial_moves)} | {pairs} | "
                     f"{len(info.multi_intent_moves)} | {'是' if info.admitted else '否'} |")
    (ROOT / 'docs/MONSTER_COVERAGE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in payload.items() if k not in ('monsters', 'encounters')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
