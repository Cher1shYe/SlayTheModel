"""Local Windows entry point: shipped Ironclad A0 policy + native MCTS."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / 'sts-rl-agent'
BUILD = ROOT / 'simulator/build312/Release'
os.environ['STS_BOT_DIR'] = str(REPO / 'agent')
os.environ['STS_LIGHTSPEED_BUILD'] = str(BUILD)
sys.path[:0] = [str(BUILD), str(REPO / 'agent')]

import torch
import slaythespire as sts
import armG_train as policy


def play(seed, simulations, model):
    started = time.perf_counter()
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    agent = sts.Agent()
    agent.simulation_count_base = simulations
    for name in ('card_reward', 'map', 'rest', 'shop', 'event', 'battle'):
        setattr(agent, 'pause_on_' + name, True)
    decisions = battles = combat_actions = 0
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        agent.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state == sts.ScreenState.BATTLE:
            bc = sts.BattleContext()
            bc.init(gc)
            for _ in range(800):
                if bc.outcome != sts.Outcome.UNDECIDED:
                    break
                actions = sts.get_legal_actions(bc)
                if not actions:
                    raise RuntimeError('Unfinished battle has no legal actions')
                action = actions[0] if len(actions) == 1 else sts.mcts_recommend(bc, simulations)
                action.execute(bc)
                combat_actions += 1
            if bc.outcome == sts.Outcome.UNDECIDED:
                raise RuntimeError('Battle exceeded 800 actions')
            bc.exit_battle(gc)
            battles += 1
        else:
            kind, descriptors, actions = policy.build_choices(gc)
            if not descriptors:
                if gc.screen_state == sts.ScreenState.REWARDS:
                    gc.skip_reward_cards()
                    continue
                raise RuntimeError(f'No choices at {gc.screen_state}: {kind}')
            with torch.inference_mode():
                scores = model.score(torch.tensor(policy.obs_vec(gc), dtype=torch.float32), descriptors)
                if not torch.isfinite(scores).all():
                    raise RuntimeError('Nonfinite policy scores')
                index = int(scores.argmax())
            actions[index](gc)
            decisions += 1
    if gc.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('Run exceeded 600 outer steps')
    return dict(seed=seed, simulations=simulations, floor=gc.floor_num,
                win=gc.outcome == sts.GameOutcome.PLAYER_VICTORY,
                outcome=str(gc.outcome), battles=battles, combat_actions=combat_actions,
                noncombat_decisions=decisions, seconds=round(time.perf_counter()-started, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', default='1', help='Comma-separated integration seeds')
    parser.add_argument('--simulations', type=int, default=100)
    parser.add_argument('--output', type=Path, default=ROOT / 'deployment/smoke.json')
    args = parser.parse_args()
    if args.simulations < 1:
        parser.error('--simulations must be positive')
    torch.set_num_threads(1)
    model = policy.Scorer((128, 128))
    weight = REPO / 'weights/armG_model_G128x128_15k.pt'
    model.load_state_dict(torch.load(weight, map_location='cpu', weights_only=True))
    model.eval()
    result = dict(python=sys.version, torch=torch.__version__, module=sts.__file__,
                  weight=str(weight), parameters=sum(p.numel() for p in model.parameters()),
                  observation_dim=policy.OBS_DIM, candidate_dim=policy.DESC_DIM,
                  note='Integration smoke, not the published 50-seed benchmark; combat rules patched.', runs=[])
    for seed in map(int, args.seeds.split(',')):
        record = play(seed, args.simulations, model)
        result['runs'].append(record)
        print(json.dumps(record), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Report: {args.output}', flush=True)


if __name__ == '__main__':
    main()
