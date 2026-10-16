"""G2.3f diagnostic only: immutable training replay, fixed rule and frozen network.

Never reads test-* artifacts, updates weights, or changes curriculum/reward.
Run from repository root; output is independently versioned evidence.
"""
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.action_candidates import action_candidates
from sts2_env.az.boss_curriculum import block_rule_action
from sts2_env.az.config import content_hash
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.entity_transition import public_from_dict, public_snapshot
from sts2_env.az.information import BeliefSampler
from sts2_env.az.rewards import V7
from sts2_env.az.scenarios import CombatScenario


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def phase(info):
    return info.boss.phase.cursor[0]


def describe(recipe, infos, keys, outcome):
    counts = Counter(k.split(':')[0] for k in keys)
    early = sum(k == 'end_turn' and any(a.action_type == 'play' for a in action_candidates(i)[0])
                for i, k in zip(infos, keys))
    return dict(scenario_id=recipe.scenario_id, split=recipe.split,
                deck_signature=content_hash([asdict(x) for x in recipe.deck]),
                initial_hp=recipe.player_hp, decisions=len(keys), actions=dict(counts),
                end_with_playable=early, only_end_turn=bool(keys) and set(keys)=={'end_turn'},
                phase_decisions=dict(Counter(str(phase(i)) for i in infos[:-1])),
                max_phase=max(phase(i) for i in infos),
                burn_hand_decisions=sum('BURN' in i.hand for i in infos[:-1]),
                wound_hand_decisions=sum('WOUND' in i.hand for i in infos[:-1]),
                damage_progress=infos[-1].boss.phase.damage_progress, outcome=outcome)


def trajectory(recipe, policy=None, episode=None):
    env = ObservableCombatAdapter(recipe, reward_version=V7)
    infos, keys, boundaries = [], [], []
    seen = set()
    while not env.outcome().done:
        info = env.information
        if episode is not None:
            row = episode['rows'][len(keys)]
            if public_from_dict(row['public_information']) != info:
                raise ValueError('Native replay public mismatch')
            key = row['chosen_action']
        else:
            key = policy(info)
        actions, mapping = action_candidates(info)
        marker = (phase(info), info.boss.phase.cursor[1])
        if marker not in seen:
            # Public reconstruction only. No native hidden deck/RNG copied here.
            particle = BeliefSampler().sample(info, np.random.default_rng(1729))
            if particle.info != info:
                raise ValueError('Boundary reconstruction mismatch')
            boundaries.append(dict(step=len(keys), public=public_snapshot(info)))
            seen.add(marker)
        infos.append(info)
        keys.append(key)
        env.step(mapping[key])
    infos.append(env.information)
    outcome = json.loads(json.dumps(asdict(env.outcome())))
    if episode is not None and (public_from_dict(episode['final_public']) != infos[-1]
                                or episode['outcome'] != outcome):
        raise ValueError('Native replay final mismatch')
    summary = describe(recipe, infos, keys, outcome)
    witness = dict(recipe=recipe.to_dict(), actions=keys, boundaries=boundaries,
                   final_public=public_snapshot(infos[-1]), outcome=outcome)
    return summary, witness


def aggregate(rows):
    return dict(episodes=len(rows), utility=sum(r['outcome']['reward'] for r in rows)/len(rows),
                outcomes=dict(Counter(r['outcome']['termination_reason'] for r in rows)),
                phase_reached={str(p):sum(r['max_phase']>=p for r in rows) for p in range(3)},
                phase_decisions={str(p):sum(r['phase_decisions'].get(str(p),0) for r in rows) for p in range(3)},
                mean_progress=sum(r['damage_progress'] for r in rows)/len(rows),
                only_end_turn=sum(r['only_end_turn'] for r in rows),
                end_with_playable=sum(r['end_with_playable'] for r in rows),
                burn_hand_decisions=sum(r['burn_hand_decisions'] for r in rows),
                wound_hand_decisions=sum(r['wound_hand_decisions'] for r in rows),
                actions=dict(sum((Counter(r['actions']) for r in rows), Counter())))


def run(root, output):
    import torch
    from sts2_env.az.model_factory import load_transformer_checkpoint
    torch.set_num_threads(1)
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    hashes, groups, witnesses, labels = {}, {}, {}, Counter()
    def source(path):
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for seed in (42,43):
        folder = root/f'seed-{seed}'
        recipes = {}
        for iteration in range(3):
            path=folder/f'manifests/train-{iteration}.json'; source(path)
            recipes.update({r['scenario_id']:CombatScenario.from_dict(r) for r in read(path)['scenarios']})
        training, rule = [], []
        for path in sorted((folder/'replay/episodes').glob('*.json.gz')):
            episode=json.loads(gzip.decompress(path.read_bytes()))
            if episode['rows'][0]['encounter_id'] != 'setup_test_subject_boss': continue
            source(path)
            recipe=recipes[episode['rows'][0]['scenario_id']]
            row,witness=trajectory(recipe,episode=episode)
            row.update(episode_id=episode['episode_id'],iteration=episode['iteration'])
            training.append(row)
            if len(training)%50==0: print(seed,'replayed Boss episodes',len(training),flush=True)
            for r in episode['rows']:
                labels[str(r['z'])]+=1
                labels['positive_visit_actions']+=sum(v>0 for v in r['root_visits'].values())
                labels['candidate_actions']+=len(r['root_visits'])
                labels['rows']+=1
            tag=f'replay-phase-{row["max_phase"]}'
            witnesses.setdefault(tag,witness)
            if '-focus-' in recipe.scenario_id:
                def policy(info):
                    native=block_rule_action(info)
                    return next(k for k,v in action_candidates(info)[1].items() if v==native)
                rr,ww=trajectory(recipe,policy)
                rule.append(rr)
                if rr['outcome']['termination_reason']=='win':
                    witnesses.setdefault('rule-win-'+rr['deck_signature'][:12],ww)
        groups[f'{seed}/training_search']=training
        groups[f'{seed}/training_rule']=rule
        print(seed,'replay',aggregate(training),'rule',aggregate(rule),flush=True)
        checkpoint=folder/('candidate-1.pt' if seed==42 else 'candidate-2.pt'); source(checkpoint)
        model,_=load_transformer_checkpoint(checkpoint,'S',BOSS_CONTENT,V7)
        path=root/'manifest.json'; source(path)
        validation=[CombatScenario.from_dict(r) for r in read(path)['scenarios']
                    if r['split']=='validation' and r['encounter_id']=='setup_test_subject_boss']
        network=[]
        for recipe in validation:
            def network_policy(info):
                probs,_=model.predict(encode_entities(info))
                return max(sorted(probs),key=probs.get)
            row,_=trajectory(recipe,network_policy)
            network.append(row)
        groups[f'{seed}/validation_network']=network
        print(seed,'network',aggregate(network),flush=True)
    for name,witness in witnesses.items():
        (output/(name+'.json')).write_text(json.dumps(witness,ensure_ascii=False,indent=2),encoding='utf-8')
    report=dict(version='transformer-g23f-audit-v1',reward=V7,training_started=False,
                final_test_read=False,phase_index='0,1,2 = first, second, third form',
                source_sha256=hashes,groups=groups,summary={k:aggregate(v) for k,v in groups.items()},
                training_labels=dict(labels),witness_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.glob('*.json') if p.name!='audit.json'})
    # Confirm diagnostics did not mutate any source artifact.
    for path,digest in hashes.items():
        if hashlib.sha256((root/path).read_bytes()).hexdigest()!=digest:
            raise ValueError('Source changed during audit')
    (output/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('audit complete',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='output/az_transformer_t3_v7_formal_20261016')
    parser.add_argument('--output',default='docs/g23f_audit')
    run(**vars(parser.parse_args()))
