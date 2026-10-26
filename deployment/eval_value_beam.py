"""Frozen STS1 value network: one-step versus receding-horizon beam search."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
import traceback

import run_agent as runtime
sys.path.insert(0, str(runtime.REPO / 'combat_experiments'))
import armB_value as V

sts, torch = runtime.sts, runtime.torch
MODEL = None
ORIGINAL_ENCODE = V.MB.encode_battle


class CutoffError(RuntimeError):
    pass


class Proxy:
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        return getattr(self.obj, name)


class PlayerProxy(Proxy):
    def get_status(self, status):
        if status == sts.PlayerStatus.BARRICADE:
            return int(self.obj.has_status(status))
        return self.obj.get_status(status)


def encode_fixed(state):
    proxy = Proxy(state)
    proxy.player = PlayerProxy(state.player)
    return ORIGINAL_ENCODE(proxy)


def initialize(repair_barricade=False):
    global MODEL
    torch.set_num_threads(1)
    V.MB.encode_battle = encode_fixed if repair_barricade else ORIGINAL_ENCODE
    MODEL = V.ValueNet((256, 256))
    MODEL.load_state_dict(torch.load(runtime.REPO / 'weights/armB_model_VAL256x256.pt',
                                    map_location='cpu', weights_only=True))
    MODEL.eval()


@torch.inference_mode()
def choose(root, width, depth):
    # Entries: state, original root action, evaluation. No lossy state deduplication.
    beam = [(root, None, 0.)]
    expanded = evaluated = 0
    for _ in range(depth):
        children, pending, encoded = [], [], []
        for state, first, score in beam:
            if state.outcome != sts.Outcome.UNDECIDED:
                children.append((state, first, score))
                continue
            actions = sts.get_legal_actions(state)
            if not actions:
                raise RuntimeError('Nonterminal search state has no legal actions')
            for action in actions:
                child = state.clone()
                action.execute(child)
                expanded += 1
                first_action = action if first is None else first
                if child.outcome != sts.Outcome.UNDECIDED:
                    score = V._battle_value(child)
                else:
                    score = None
                    pending.append(len(children))
                    encoded.append(V.MB.encode_battle(child))
                children.append((child, first_action, score))
        if encoded:
            values = MODEL.net(torch.tensor(encoded, dtype=torch.float32)).squeeze(-1)
            if not torch.isfinite(values).all():
                raise RuntimeError('Nonfinite values')
            evaluated += len(encoded)
            for index, value in zip(pending, values.tolist()):
                child, first, _ = children[index]
                children[index] = (child, first, value)
        # Stable ordering provides deterministic tie handling.
        children.sort(key=lambda row: row[2], reverse=True)
        beam = children[:width]
        if all(state.outcome != sts.Outcome.UNDECIDED for state, _, _ in beam):
            break
    if not beam or beam[0][1] is None:
        raise RuntimeError('Search did not produce a root action')
    return beam[0][1], expanded, evaluated


def worker(job):
    seed, width, depth = job
    began = time.perf_counter()
    stats = dict(seed=seed, width=width, depth=depth, searches=0, expanded=0,
                 value_evaluations=0, search_seconds=0., combat_actions=0, battles=0)
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    agent = sts.Agent()
    agent.simulation_count_base = 2000
    agent.pause_on_battle = True  # Match original value experiment's built-in noncombat policy.
    try:
        for outer in range(600):
            if gc.outcome != sts.GameOutcome.UNDECIDED:
                break
            agent.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED:
                break
            if gc.screen_state != sts.ScreenState.BATTLE:
                raise RuntimeError(f'Unexpected pause: {gc.screen_state}')
            bc = sts.BattleContext()
            bc.init(gc)
            for step in range(800):
                if bc.outcome != sts.Outcome.UNDECIDED:
                    break
                actions = sts.get_legal_actions(bc)
                if not actions:
                    raise RuntimeError('Nonterminal live state has no legal actions')
                if len(actions) == 1:
                    action = actions[0]
                else:
                    start = time.perf_counter()
                    action, expanded, evaluated = choose(bc, width, depth)
                    stats['search_seconds'] += time.perf_counter()-start
                    stats['searches'] += 1
                    stats['expanded'] += expanded
                    stats['value_evaluations'] += evaluated
                action.execute(bc)
                stats['combat_actions'] += 1
            if bc.outcome == sts.Outcome.UNDECIDED:
                raise CutoffError('Combat guard: 800 decisions reached')
            bc.exit_battle(gc)
            stats['battles'] += 1
        if gc.outcome == sts.GameOutcome.UNDECIDED:
            raise CutoffError('Run guard: 600 outer steps reached')
        stats.update(status='completed', outcome=str(gc.outcome),
                     win=gc.outcome == sts.GameOutcome.PLAYER_VICTORY)
    except CutoffError as exc:
        stats.update(status='cutoff', reason=str(exc), win=False)
    except Exception:
        stats.update(status='error', error=traceback.format_exc(), win=None)
    stats.update(floor=gc.floor_num, seconds=time.perf_counter()-began)
    return stats


def summarize(rows):
    result = {}
    for width, depth in ((1, 1), (8, 4)):
        group = [r for r in rows if r['width'] == width and r['depth'] == depth]
        done = [r for r in group if r['status'] == 'completed']
        searches = sum(r['searches'] for r in done)
        result[f'w{width}d{depth}'] = dict(finished_jobs=len(group), complete_runs=len(done),
            errors=sum(r['status']=='error' for r in group),
            cutoffs=sum(r['status']=='cutoff' for r in group),
            bounded_mean_floor=statistics.mean(r['floor'] for r in group) if group and all(r['status']!='error' for r in group) else None,
            mean_floor=statistics.mean(r['floor'] for r in done) if done else None,
            wins=sum(r['win'] for r in done),
            mean_search_ms=1000*sum(r['search_seconds'] for r in done)/searches if searches else None,
            mean_run_seconds=statistics.mean(r['seconds'] for r in done) if done else None,
            mean_expanded_per_search=sum(r['expanded'] for r in done)/searches if searches else None)
    paired = {}
    for r in rows:
        if r['status'] == 'completed':
            paired.setdefault(r['seed'], {})[r['width']] = r['floor']
    differences = [r[8]-r[1] for r in paired.values() if 1 in r and 8 in r]
    if differences:
        result['paired'] = dict(n=len(differences), mean_floor_difference=statistics.mean(differences),
            beam_better=sum(x>0 for x in differences), tied=sum(x==0 for x in differences),
            beam_worse=sum(x<0 for x in differences))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=50)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repair-barricade', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    seed_file = runtime.REPO/'eval/eval_seeds_50.txt'
    seeds = [int(x) for x in seed_file.read_text(encoding='utf-8').splitlines() if x and not x.startswith('#')][:args.count]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    config = dict(seeds=seeds, variants=[dict(width=1,depth=1),dict(width=8,depth=4)],
        noncombat='built-in ScumSearchAgent2, simulation_count_base=2000',
        character='IRONCLAD', ascension=0, workers=args.workers,
        value='shipped VAL256x256; no retraining, no clipping',
        barricade_boolean_encoding_fix=args.repair_barricade,
        terminal_value='win_indicator + current_hp/max_hp',
        semantics='expand all actions, retain top width by value each layer; terminal states carried; execute only first action and replan; depth counts actions including end-turn/choices',
        weight_sha256=digest(runtime.REPO/'weights/armB_model_VAL256x256.pt'),
        native_sha256=digest(Path(sts.__file__)), script_sha256=digest(Path(__file__)),
        note='Patched Windows simulator; not a reproduction of the historical unpatched Linux score.')
    (args.out/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    rows=[]; started=time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize, initargs=(args.repair_barricade,)) as pool:
        jobs = [pool.submit(worker,(seed,w,d)) for seed in seeds for w,d in ((1,1),(8,4))]
        for future in as_completed(jobs):
            row=future.result(); rows.append(row)
            (args.out/f"seed-{row['seed']}-w{row['width']}d{row['depth']}.json").write_text(json.dumps(row,indent=2),encoding='utf-8')
            progress=dict(jobs_done=len(rows),jobs_total=len(jobs),wall_seconds=time.perf_counter()-started,summary=summarize(rows))
            (args.out/'progress.json').write_text(json.dumps(progress,indent=2),encoding='utf-8')
            print(f"{len(rows)}/{len(jobs)} seed={row['seed']} w={row['width']} d={row['depth']} floor={row['floor']} {row['status']}",flush=True)
    result=dict(config=config,wall_seconds=time.perf_counter()-started,summary=summarize(rows),runs=rows)
    (args.out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],indent=2),flush=True)


if __name__ == '__main__':
    main()
