"""Public-search instrumentation and legal ordering counterfactuals; no tuning."""
from .action_candidates import action_candidates
from .dynamic_search import search_dynamic, KeyedParticle
from .entity_encoder import encode_entities
from .information import BeliefSampler
from .risk_reward import search_utility
from .search_config import DYNAMIC_RISK
from .entity_transition import public_snapshot
from .config import content_hash


def token_action(info,token):
    for action in action_candidates(info)[0]:
        if action.action_type=='play' and info.hand[int(action.source_ref.split('/')[1])]==token:
            return action.action_key
    raise ValueError(f'No legal action for {token}')


def sequence(env_factory,tokens):
    env=env_factory(); root=env.information; steps=[]
    for token in tokens:
        key=token_action(env.information,token)
        env.step(action_candidates(env.information)[1][key])
        info=env.information
        steps.append(dict(token=token,action=key,block=info.player_block,enemy_hp=info.enemy_hp,
                          player_hp=info.player_hp,cutoff_utility=search_utility(root,info)))
    return steps


def probe(info,model=None,budget=8,search_seed=1729):
    depths=[]; backups=[]
    original=content_hash(public_snapshot(info))
    class Particle:
        def __init__(self,particle): self.particle=particle; self.depth=0
        @property
        def info(self): return self.particle.info
        def step(self,key):
            self.depth+=1
            depths[-1]=self.depth
            return self.particle.step(key)
    def sample(public,rng):
        depths.append(0)
        return Particle(KeyedParticle(BeliefSampler().sample(public,rng)))
    def evaluate(public):
        if model is not None: return model.predict(encode_entities(public))
        keys=action_candidates(public)[1]
        return {k:1/len(keys) for k in keys},0.
    def cutoff(root,leaf):
        value=search_utility(root,leaf)
        backups.append(dict(depth=depths[-1],terminal=leaf.terminal_value() is not None,value=value))
        return value
    result=search_dynamic(info,sample,evaluate,lambda i:action_candidates(i)[1],
        model_version='frozen-combo-diagnostic',budget=budget,search_seed=search_seed,
        search_version=DYNAMIC_RISK,cutoff_reward=cutoff)
    if original!=content_hash(public_snapshot(info)): raise ValueError('Search mutated public root')
    return dict(budget=budget,search_seed=search_seed,action=result.action,
        visits=result.root_visits,q={k:e.q for k,e in result.root.edges.items()},
        priors=result.root_priors,depths=depths,backups=backups,
        max_depth=max(depths,default=0),forced=result.forced_action)
