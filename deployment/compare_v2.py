"""Print round-by-round tables for v2 self-play runs."""
import json
import sys
from pathlib import Path


def f(x, n=2):
    try:
        if x != x:
            return 'nan'
    except Exception:
        return str(x)
    return f'{x:.{n}f}'


def history_table(hist):
    print('| round | PUCT@512 | pure | PUCT win | PUCT HP | value R2 | value MSE | samples |')
    print('|---:|---:|---:|---:|---:|---:|---:|---:|')
    for r in hist:
        pu, pr = r['puct'], r['pure']
        tr = r.get('train') or {}
        print(f"| {r['round']} | {f(pu['mean_floor'])} | {f(pr['mean_floor'])} | "
              f"{f(pu['battle_win'], 4)} | {f(pu['battle_hp'], 4)} | "
              f"{f(pu.get('value_r2', float('nan')), 3)} | "
              f"{f(pu.get('value_mse', float('nan')), 4)} | {tr.get('samples', '')} |")


def eval_table(res):
    print('| round | PUCT | PUCT win | PUCT HP | pure | pure win | value R2 | '
          'pair Δ PUCT | t | pair Δ pure | t |')
    print('|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    for r in res['rounds']:
        pu, pr = r['puct'], r['pure']
        paired = r.get('paired') or {}
        dp = paired.get('puct', {})
        dr = paired.get('pure', {})
        print(f"| {r['round']} | {f(pu['mean_floor'])} | {f(pu['battle_win'], 4)} | "
              f"{f(pu['battle_hp'], 4)} | {f(pr['mean_floor'])} | "
              f"{f(pr['battle_win'], 4)} | {f(pu.get('value_r2', float('nan')), 3)} | "
              f"{f(dp.get('delta', float('nan')))} | {f(dp.get('t', float('nan')), 1)} | "
              f"{f(dr.get('delta', float('nan')))} | {f(dr.get('t', float('nan')), 1)} |")


def main():
    for arg in sys.argv[1:]:
        path = Path(arg)
        print(f'\n## {path.parent.name if path.name == "history.json" else path.stem}')
        obj = json.loads(path.read_text())
        if isinstance(obj, list):
            history_table(obj)
        else:
            eval_table(obj)


if __name__ == '__main__':
    main()
