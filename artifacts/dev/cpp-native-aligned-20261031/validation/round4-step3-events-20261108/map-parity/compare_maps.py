"""Compare C++ act maps with native maps recorded by the headless probe.

Each probe decision log records the seed string and, per act, the native
map_points (coordinate, point_type, children). The C++ map for the same seed
and act is generated with sts2_sim.generate_map(run seed, act, ascension).
"""
import glob, json, sys
sys.path.insert(0, 'simulator')
import sts2_sim as sim

TYPES = {int(v): k for k, v in sim.MapPointType.__members__.items()}
NATIVE = {'Monster': 'MONSTER', 'Unknown': 'UNKNOWN', 'RestSite': 'REST', 'Treasure': 'TREASURE',
          'Shop': 'SHOP', 'Elite': 'ELITE', 'Ancient': 'ANCIENT', 'Boss': 'BOSS'}

def native_maps(path):
    report = json.load(open(path.replace('.decisions.jsonl', '')))
    seed, asc, maps = report.get('seed'), report.get('ascension', 0) or 0, {}
    for line in open(path):
        o = json.loads(line).get('request', {}).get('observation')
        if not o or 'map_points' not in o or o.get('act_index') in maps: continue
        pts = {}
        for p in o['map_points']:
            c = p['coordinate']
            pts[(c['row'], c['column'])] = (NATIVE.get(p['point_type'], p['point_type']),
                                           sorted((k['row'], k['column']) for k in p.get('children', [])))
        maps[o['act_index']] = pts
    return seed, asc, maps

def cpp_map(raw_seed, act, asc):
    _, _, nodes = sim.generate_map(raw_seed, act, asc)
    rc = {i: (r, c) for i, _, c, r, _, _ in nodes}
    return {(r, c): (TYPES[t], sorted(rc[k] for k in kids)) for i, t, c, r, kids, _ in nodes}

total = same = 0
seen = set()
for path in sorted(glob.glob('/Users/yebohou/Workspace/SlayTheModel/artifacts/headless/**/*.decisions.jsonl', recursive=True)):
    seed, asc, maps = native_maps(path)
    if not seed or not maps: continue
    rc = sim.RunContext(); rc.init_seed(seed, asc)
    for act, native in sorted(maps.items()):
        if (seed, act) in seen: continue
        seen.add((seed, act))
        cpp = cpp_map(rc.seed, act, asc)
        # The native list omits the boss node in some logs; compare rooms 0..rows-1.
        keys = set(native) | set(cpp)
        diffs = [k for k in sorted(keys) if native.get(k, (None,))[0] not in ('BOSS',) and
                 cpp.get(k, (None,))[0] not in ('BOSS',) and native.get(k) != cpp.get(k)]
        total += 1
        same += not diffs
        types_n = sorted(v[0] for k, v in native.items()); types_c = sorted(v[0] for k, v in cpp.items() if v[0] != 'BOSS')
        print(f"{seed} act{act} asc{asc}: {'MATCH' if not diffs else f'{len(diffs)} differing points'}"
              + ('' if not diffs else f"; e.g. {diffs[0]} native={native.get(diffs[0])} cpp={cpp.get(diffs[0])}"))
# Terminal traces: {"map": {"nodes": [{x, y, kind}], "edges": [{from, to}]}}; acts in order of appearance.
def trace_maps(path):
    seed, maps, seen_keys = None, [], set()
    def find(o):
        if isinstance(o, dict):
            if isinstance(o.get('map'), dict) and 'nodes' in o['map']: return o['map']
            for v in o.values():
                r = find(v)
                if r: return r
        elif isinstance(o, list):
            for v in o:
                r = find(v)
                if r: return r
    for line in open(path):
        r = json.loads(line)
        if r.get('type') == 'run_context': seed = r.get('seed')
        m = find(r)
        if not m: continue
        key = tuple(sorted(n['id'] for n in m['nodes']))
        if key in seen_keys: continue
        seen_keys.add(key)
        kids = {}
        for e in m.get('edges', []): kids.setdefault(e['from'], []).append(e['to'])
        pt = lambda i: (int(i.split(':')[1].split(',')[1]), int(i.split(':')[1].split(',')[0]))
        maps.append({(n['y'], n['x']): (NATIVE.get(n['kind'], n['kind']), sorted(pt(k) for k in kids.get(n['id'], [])))
                     for n in m['nodes']})
    return seed, maps

for path in ['/Users/yebohou/Workspace/SlayTheModel/artifacts/headless/random-a84ee33a/run.jsonl']:
    seed, maps = trace_maps(path)
    rc = sim.RunContext(); rc.init_seed(seed, 0)
    for act, native in enumerate(maps[:3]):
        cpp = cpp_map(rc.seed, act, 0)
        diffs = [k for k in sorted(set(native) | set(cpp)) if 'BOSS' not in (native.get(k, (None,))[0], cpp.get(k, (None,))[0])
                 and native.get(k) != cpp.get(k)]
        total += 1; same += not diffs
        print(f"{seed} act{act} (trace): {'MATCH' if not diffs else f'{len(diffs)} differing points'}"
              + ('' if not diffs else f"; e.g. {diffs[0]} native={native.get(diffs[0])} cpp={cpp.get(diffs[0])}"))
print(f"{same}/{total} act maps identical")
