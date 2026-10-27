"""Paired evaluation driven by an explicit policy JSON list.

Every policy is merged over BASE (the reference non-combat policy); the label
spells out any option that differs from the base so policies never collide.
"""
import argparse, json, statistics, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
sys.path.insert(0, 'deployment')
sys.path.insert(0, 'simulator/build312/Release')
import selfplay_v2 as V2
import armg2 as A

BASE = dict(pick='delta', junk=1, smith_target='high', rest_smith=0.75,
            shop_mode='junk_relic', shop_w=0.0, skip_mode='model', scorer='armg',
            remove_min=3, boss_rest=0.0, boss_win=2, boss_act=2, map_elite=None,
            model='', card_margin=0.0, shop_remove=0, save_potions=0, cfg=None,
            wp=None, wv=None)


def merge(p):
    q = dict(BASE)
    q.update(p)
    return q


def label(p):
    parts = []
    if p.get('wp'):
        parts.append(str(Path(p['wp']).parent.name) + '/' + Path(p['wp']).stem.split('_')[0])
    for k in sorted(p):
        if k in ('wp', 'wv'):
            continue
        if k == 'model':
            if p[k]:
                parts.append(Path(p[k]).name)
            continue
        if k not in BASE or p[k] != BASE[k]:
            parts.append('%s=%s' % (k, p[k]))
    return ','.join(parts) or 'base'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', default='deployment/runs_v2/armD')
    ap.add_argument('--round', type=int, default=4)
    ap.add_argument('--source', default='deployment/runs_v2/lcb_src')
    ap.add_argument('--workers', type=int, default=24)
    ap.add_argument('--seeds', type=int, default=150)
    ap.add_argument('--timed-ms', type=float, default=40.0)
    ap.add_argument('--policies', required=True, help='JSON list of policy dicts')
    ap.add_argument('--out', default='deployment/runs_v2/probe7.json')
    a = ap.parse_args()
    seeds = A.eval_seeds(a.seeds, extra=max(0, a.seeds - 50))
    wp = str(Path(a.run) / ('round%d_policy.pt' % a.round))
    wv = str(Path(a.run) / ('round%d_value.pt' % a.round))
    pols = [merge(p) for p in json.loads(a.policies)]
    cfgs = {}
    for i, p in enumerate(pols):
        c = A.base_cfg(float(p.get('timed_ms', a.timed_ms)))
        c.update(p.get('cfg') or {})
        cfgs[i] = c
    jobs = []
    for s in seeds:
        for i, p in enumerate(pols):
            jobs.append((s, p.get('wp') or wp, p.get('wv') or wv, cfgs[i], 0.0, 'eval',
                         p.get('model', '') or '', p))
    with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                             initargs=(a.source,)) as pool:
        rows = []
        for _i, _r in enumerate(pool.map(A.run_episode, jobs, chunksize=1)):
            rows.append(_r)
            if (_i + 1) % 50 == 0:
                print("progress %d/%d" % (_i + 1, len(jobs)), flush=True)
    by = {}
    for s in seeds:
        for p in pols:
            by.setdefault(label(p), {})[s] = rows.pop(0)
    ref = label(pols[0])
    out = dict(seeds=len(seeds), timed_ms=a.timed_ms, policies={}, ref=ref)
    for p in pols:
        k = label(p)
        rs = list(by[k].values())
        wins = sum(r['win'] for r in rs)
        _bs = [b for r in rs for b in (r.get('battles') or [])]
        _dec = sum(b.get('searched', 0) for b in _bs)
        _ms = sum(b.get('search_ms', 0.0) for b in _bs)
        _boss = [dict(seed=r['seed'], floor=b.get('floor'), enc=b.get('enc'),
                      hp0=b.get('hp0'), maxhp=b.get('maxhp'), win=int(bool(b.get('win'))))
                 for r in rs for b in (r.get('battles') or [])
                 if b.get('floor') in (16, 33, 50) or 'BOSS' in str(b.get('enc', '')).upper()]
        out['policies'][k] = dict(mean_floor=statistics.mean(r['floor'] for r in rs),
                                  boss=_boss,
                                  wins=wins, win_rate=wins / len(rs),
                                  mean_deck=statistics.mean(r['deck'] for r in rs),
                                  mean_ms=(_ms / _dec if _dec else 0.0),
                                  floors=[r['floor'] for r in rs], opts=p)
        print('%-62s floor %.2f win %2d/%d (%4.1f%%) deck %.1f ms %5.1f' % (
            k, out['policies'][k]['mean_floor'], wins, len(rs), 100 * wins / len(rs),
            out['policies'][k]['mean_deck'], out['policies'][k]['mean_ms']), flush=True)
    for p in pols[1:]:
        k = label(p)
        d = [by[k][s]['floor'] - by[ref][s]['floor'] for s in seeds]
        w = [int(by[k][s]['win']) - int(by[ref][s]['win']) for s in seeds]
        print('paired %s - %s: floor %+.2f +- %.2f | wins %+d' % (
            k, ref, statistics.mean(d), statistics.stdev(d) / len(d) ** 0.5, sum(w)), flush=True)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print('saved', a.out, flush=True)


if __name__ == '__main__':
    main()
