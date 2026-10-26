"""Single-process CPU benchmarks; native rollouts, Python steps, and MCTS."""
import json
from pathlib import Path
import random
import re
import statistics
import time
import run_agent as run

sts, torch, policy = run.sts, run.torch, run.policy


def collect(model):
    samples = []
    for seed in (1, 2, 3):
        gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
        ag = sts.Agent()
        ag.simulation_count_base = 2000
        for name in ('card_reward', 'map', 'rest', 'shop', 'event', 'battle'):
            setattr(ag, 'pause_on_' + name, True)
        seen = set()
        for _ in range(600):
            if gc.outcome != sts.GameOutcome.UNDECIDED:
                break
            ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED:
                break
            if gc.screen_state == sts.ScreenState.BATTLE:
                bc = sts.BattleContext()
                bc.init(gc)
                # One opening and one later decision per act and seed.
                selected = gc.act not in seen
                for step in range(800):
                    if bc.outcome != sts.Outcome.UNDECIDED:
                        break
                    actions = sts.get_legal_actions(bc)
                    if not actions:
                        raise RuntimeError('No actions')
                    if selected and step in (0, 8) and len(actions) > 1:
                        samples.append((dict(seed=seed, act=gc.act, floor=gc.floor_num,
                                             step=step, encounter=str(bc.encounter)), bc.clone()))
                    (actions[0] if len(actions) == 1 else sts.mcts_recommend(bc, 2000)).execute(bc)
                if bc.outcome == sts.Outcome.UNDECIDED:
                    raise RuntimeError('Combat guard')
                seen.add(gc.act)
                bc.exit_battle(gc)
            else:
                _, descs, actions = policy.build_choices(gc)
                if not actions:
                    if gc.screen_state == sts.ScreenState.REWARDS:
                        gc.skip_reward_cards()
                        continue
                    raise RuntimeError('No noncombat action')
                with torch.inference_mode():
                    idx = int(model.score(torch.tensor(policy.obs_vec(gc), dtype=torch.float32), descs).argmax())
                actions[idx](gc)
        if gc.outcome == sts.GameOutcome.UNDECIDED:
            raise RuntimeError('Game guard')
    return samples


def main():
    torch.set_num_threads(1)
    model = policy.Scorer((128, 128))
    model.load_state_dict(torch.load(run.REPO/'weights/armG_model_G128x128_15k.pt', weights_only=True))
    model.eval()
    samples = collect(model)
    print(f'Collected {len(samples)} fixed states', flush=True)
    results = []
    for metadata, state in samples:
        # repr includes the process-global action counter, not part of this state.
        fingerprint = lambda s: re.sub(r'sum: \d+', 'sum: GLOBAL', repr(s))
        before = fingerprint(state)
        sts.benchmark_native_rollouts(state, 50)
        sts.mcts_recommend(state, 100)
        native = []
        for _ in range(5):
            start = time.perf_counter()
            actions, hp = sts.benchmark_native_rollouts(state, 2000)
            elapsed = time.perf_counter()-start
            native.append(dict(seconds=elapsed, rollouts=2000, actions=actions, hp_checksum=hp))
        searches = {}
        for budget in (100, 2000, 50000):
            timings = []
            for _ in range(5):
                start = time.perf_counter()
                sts.mcts_recommend(state, budget)
                timings.append(time.perf_counter()-start)
            searches[str(budget)] = timings
        rng = random.Random(42)
        py_actions = 0
        start = time.perf_counter()
        for _ in range(100):
            bc = state.clone()
            for _ in range(2000):
                if bc.outcome != sts.Outcome.UNDECIDED:
                    break
                actions = sts.get_legal_actions(bc)
                if not actions:
                    raise RuntimeError('No random action')
                actions[rng.randrange(len(actions))].execute(bc)
                py_actions += 1
            if bc.outcome == sts.Outcome.UNDECIDED:
                raise RuntimeError('Random combat guard')
        py_seconds = time.perf_counter()-start
        assert fingerprint(state) == before, 'Benchmark mutated root'
        results.append(dict(**metadata, native=native, mcts=searches,
                            python=dict(actions=py_actions, seconds=py_seconds, rollouts=100)))
        print(f'{metadata}: done', flush=True)
    native_s = sum(x['seconds'] for row in results for x in row['native'])
    native_a = sum(x['actions'] for row in results for x in row['native'])
    native_n = sum(x['rollouts'] for row in results for x in row['native'])
    summary = dict(native_actions_per_second=native_a/native_s,
                   native_rollouts_per_second=native_n/native_s,
                   mean_actions_per_rollout=native_a/native_n,
                   python_actions_per_second=sum(r['python']['actions'] for r in results)/sum(r['python']['seconds'] for r in results),
                   states=len(samples), mcts={})
    for budget in (100, 2000, 50000):
        times = [t for r in results for t in r['mcts'][str(budget)]]
        summary['mcts'][budget] = dict(simulations_per_second=budget*len(times)/sum(times),
            mean_ms=statistics.mean(times)*1000, median_ms=statistics.median(times)*1000,
            min_state_median_ms=min(statistics.median(r['mcts'][str(budget)]) for r in results)*1000,
            max_state_median_ms=max(statistics.median(r['mcts'][str(budget)]) for r in results)*1000)
    report = dict(cpu='Intel Core Ultra X7 358H', parallel_workers=1, python=run.sys.version,
                  warmups='50 native rollouts + 100 MCTS before each state', repeats=5,
                  selection='Seeds 1,2,3; first battle per reached act, decision 0 and 8 if nonterminal with >1 action; collected with MCTS 2000',
                  summary=summary, details=results)
    out=Path(__file__).with_name('speed_benchmark.json')
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
