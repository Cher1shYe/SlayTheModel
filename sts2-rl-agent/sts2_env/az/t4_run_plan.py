"""Immutable T4 execution budgets; creating a plan never starts work."""
from dataclasses import replace
from .config import content_hash
from .natural_course import checked, sample_entry
from .t4_protocol import validate_protocol,training_recipes
import numpy as np

VERSION='transformer-t4-run-v1'


def plan(protocol,course,mode,seed):
    validate_protocol(protocol,course['entries']);checked(course)
    if mode not in ('smoke','formal') or seed not in ((41,) if mode=='smoke' else (42,43)):
        raise ValueError('Frozen T4 mode/seed required')
    return dict(version=VERSION,mode=mode,seed=seed,rounds=2 if mode=='smoke' else 3,
        full_episodes=135,late_episodes=45,episode_order='full-full-full-late',
        updates=4 if mode=='smoke' else 16,batch_full=48,batch_late=16,microbatch=8,
        replay_full_rows=150000,replay_late_rows=50000,replay='t4-mixed-replay-v1',
        resident_replay_episodes=16,
        sampling='kind-3:1/episode-uniform/row-uniform-with-replacement',
        storage='gzip-json/atomic-manifest/whole-episode-fifo/archive-evicted',
        tier='S',device='cpu',threads=1,precision='float32',simulations=8,max_depth=128,
        c_puct=1.5,training_epsilon=.25,training_alpha=.3,temperature_steps=10,
        learning_rate=.0003,weight_decay=.0001,gradient_clip=1.,
        max_turns=100,max_decisions=400,validation_count=256,validation_search_simulations=0,
        promotion='network-utility-v1',reward='risk-terminal-v7',search='dynamic-risk-puct-v2',
        protocol_sha256=protocol['sha256'],course_sha256=course['sha256'],
        initialization='fresh-only',resume='completed-episode/update/evaluation-row-boundaries',
        oom='stop-no-budget-change',heldout='formal-only-after-both-champions-frozen',
        heldout_network_battles_per_seed=96,
        startup_free_bytes=10*1024**3,disk_reserve_bytes=2*1024**3,
        formal_requires='same-binding-two-round-smoke-both-and-final-network-gates-pass')


def jobs(p,protocol,course,iteration):
    if not 0<=iteration<p['rounds']:raise ValueError('Round outside budget')
    recipes=training_recipes(protocol);full_index=0
    from .config import derive_seed
    for index in range(p['full_episodes']+p['late_episodes']):
        identity=content_hash([p,iteration,index])
        if index%4==3:
            entry=sample_entry(course,np.random.default_rng(derive_seed(p['seed'],iteration,index,'late-start')))
            yield dict(identity=identity,kind='late',index=index,start=entry)
        else:
            # Exact combo stays frozen; only train IDs and disjoint environment seeds change.
            template=recipes[(iteration*p['full_episodes']+full_index)%len(recipes)]
            recipe=replace(template,scenario_id=f"{VERSION}-train-{p['seed']}-{iteration}-{index}",
                environment_seed=1_600_000_000+p['seed']*100000+iteration*1000+index)
            yield dict(identity=identity,kind='full',index=index,recipe=recipe.to_dict())
            full_index+=1
