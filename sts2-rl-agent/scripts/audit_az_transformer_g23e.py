"""Freeze support and resource metadata; no self-play search or training run."""
import gc
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.boss_search_curriculum import generate,VERSION as COURSE
from sts2_env.az.boss_cards import CODEC
from sts2_env.az.content import BOSS_CONTENT,profiles
from sts2_env.az.rewards import V6
from sts2_env.az.entity_encoder import SCHEMA,SCHEMA_HASH,encode_entities
from sts2_env.az.entity_replay import pack_observation,REPLAY_VERSION
from sts2_env.az.expanded_mechanics import registry_manifest
from sts2_env.az.model_factory import create_transformer,model_metadata
from sts2_env.az.network import code_digest
from sts2_env.az.config import atomic_json,content_hash


def main():
    torch.set_num_threads(1)
    torch.manual_seed(17)
    seen_cards,seen_monsters,choices,actions=set(),set(),set(),set()
    lengths=[]
    observations=[]
    started=perf_counter()
    for slot in range(180):
        env=ObservableCombatAdapter(generate(42,0,slot),reward_version=V6)
        rng=np.random.default_rng(slot+800)
        while not env.outcome().done:
            info=env.information
            obs=encode_entities(info)
            if len(observations)<20 and slot%9==0 and info.history.decisions==0: observations.append(obs)
            seen_cards.update(info.hand+info.discard+info.draw_composition+info.exhaust)
            seen_monsters.update(e.monster_id for e in info.enemies)
            if info.choice: choices.add(info.choice.mechanism)
            actions.update(a.action_type for a in obs.actions)
            lengths.append((len(obs.entities),len(obs.actions),len(json.dumps(pack_observation(obs),separators=(',',':')).encode())))
            env.step(int(rng.choice(np.flatnonzero(info.legal_mask))))
    duration=perf_counter()-started
    tiers={}
    for tier in ('XS','S','M','L','XL'):
        model=create_transformer(tier,content_version=BOSS_CONTENT)
        entry=model_metadata(model)
        n=entry['parameter_count']
        tiers[tier]={'parameters':n,'fp32_parameter_gradient_adam_bytes':16*n,'config':entry['config'],
                     'allocation':'actual CPU parameters; no experiment'}
        if tier in ('XS','S'):
            start=perf_counter()
            for obs in observations: model.predict(obs,action_chunk_size=32)
            tiers[tier]['serial_20_initial_states_seconds']=perf_counter()-start
        del model
        gc.collect()
    columns=('engine','observation','action','network','belief_search','tests')
    status={k:True for k in columns}
    manifest=registry_manifest()
    manifest.pop('program_source')
    report={'version':'g23e-transformer-audit-v1','schema':SCHEMA,'schema_hash':SCHEMA_HASH,
        'code_digest':code_digest(),'content':BOSS_CONTENT,'reward':V6,'replay':REPLAY_VERSION,'course':COURSE,
        'experiment_started':False,'quality_claim':False,'heldout_manifest_read':False,
        'support':{'card_variants':{k:status for k in CODEC.factories},
                   'encounters':{k:status for k in profiles(BOSS_CONTENT)},
                   'monster_entities':{k:status for k in manifest['monsters']}},
        'scope_counts':{'base_cards':len({t.removesuffix('+') for t in CODEC.factories}),
                        'card_variants':len(CODEC.factories),'encounters':len(profiles(BOSS_CONTENT)),
                        'monster_entities':len(manifest['monsters'])},
        'mechanic_manifest':manifest,
        'coverage':{'kind':'180 training recipe random contract trajectories; seed 42, iteration 0; not quality evaluation',
                    'recipes_hash':content_hash([generate(42,0,i).to_dict() for i in range(180)]),
                    'decisions':len(lengths),'seconds':duration,'seen_card_variants':sorted(seen_cards),
                    'seen_monsters':sorted(seen_monsters),'seen_choices':sorted(choices),'action_types':sorted(actions),
                    'max_entities':max(n for n,a,b in lengths),'max_actions':max(a for n,a,b in lengths),
                    'mean_packed_feature_bytes':sum(b for n,a,b in lengths)/len(lengths),
                    'max_packed_feature_bytes':max(b for n,a,b in lengths),
                    'note':'feature JSON bytes excludes public audit and gzip; not total Replay memory'},
        'tiers':tiers,'test_evidence':'docs/transformer_g23e_tests.txt',
        'tests_include':'63 descriptors, 180 full train trajectories, synthetic choices/later forms/long states, keyed PUCT, spawn/replay/exact resume, legacy engine regressions',
        'limitations':['Only frozen G2.3e and starter contracts; no arbitrary full-game content.',
                        'Synthetic later-form/length fixtures are not natural full-combat victories.',
                        'Maximum schema length is validated, not an all-tier throughput or memory guarantee.',
                        'No unseen-combination/ID generalization or policy-quality acceptance.']}
    destination=Path(__file__).resolve().parents[1]/'docs/transformer_g23e_audit.json'
    atomic_json(destination,report)
    print(json.dumps({k:report[k] for k in ('scope_counts','coverage','tiers')},indent=2))


if __name__=='__main__': main()
