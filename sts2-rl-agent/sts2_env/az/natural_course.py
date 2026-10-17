"""Versioned natural late starts. Restore by legal prefix, never by HP mutation.

Suffix records are deliberately incompatible with whole-episode Replay v2.
Their terminal value retains original battle H0 and original action/turn limits.
"""
from dataclasses import asdict
import json
from .adapter import ObservableCombatAdapter
from .action_candidates import action_candidates
from .config import content_hash, EpisodeLimits
from .entity_transition import public_snapshot, public_from_dict
from .entity_encoder import encode_entities
from .entity_replay import pack_observation
from .scenarios import CombatScenario
from .rewards import V7

VERSION='natural-late-course-v1'
REPLAY_VERSION='natural-late-suffix-v1'


def normalized(value):
    return json.loads(json.dumps(value))


def seal(record):
    return {**record,'sha256':content_hash(record)}


def checked(record):
    data={k:v for k,v in record.items() if k!='sha256'}
    if record.get('sha256')!=content_hash(data):
        raise ValueError('Natural course digest mismatch')
    return data


def advance(env,key):
    if env.outcome().done: raise ValueError('Prefix continues after terminal')
    mapping=action_candidates(env.information)[1]
    if key not in mapping: raise ValueError('Illegal natural prefix action')
    env.step(mapping[key])


def export_witness(witness):
    """Validate a complete train witness, extract first natural state per category."""
    recipe=CombatScenario.from_dict(witness['recipe'])
    if recipe.split!='train': raise ValueError('Heldout witness cannot enter curriculum')
    final=public_from_dict(witness['final_public'])
    if final.reward_version!=V7: raise ValueError('Natural course requires V7')
    env=ObservableCombatAdapter(recipe,limits=final.limits,reward_version=V7)
    entries=[]; seen=set(); prefix=[]
    for key in witness['actions']:
        info=env.information
        if info.boss is None: raise ValueError('Natural late course requires Boss')
        phase,life,*_=info.boss.phase.cursor
        categories=[]
        if phase in (1,2) and life=='alive': categories.append(f'phase-{phase}')
        if 'BURN' in info.hand: categories.append('burn-hand')
        if info.choice and info.choice.mechanism.removesuffix('+')=='PURITY' and any(
                o.card.token in ('BURN','WOUND','DAZED') for o in info.choice.options):
            categories.append('purity-status-choice')
        for category in categories:
            if category in seen: continue
            seen.add(category)
            entries.append(seal(dict(version=VERSION,category=category,split='train',
                source_sha256=content_hash(witness),recipe=recipe.to_dict(),prefix=list(prefix),
                public=public_snapshot(info),limits=asdict(final.limits),reward_version=V7,
                value_scope='original-battle-terminal',evaluation_scope='late-diagnostic-only')))
        advance(env,key); prefix.append(key)
    if (env.information!=final or normalized(asdict(env.outcome()))!=witness['outcome']
            or not env.outcome().done):
        raise ValueError('Incomplete or inconsistent natural witness')
    return normalized(entries)


def restore(entry):
    data=checked(entry)
    if (data['version']!=VERSION or data['reward_version']!=V7 or data['split']!='train'
            or data['value_scope']!='original-battle-terminal'
            or data['evaluation_scope']!='late-diagnostic-only'):
        raise ValueError('Incompatible natural course contract')
    recipe=CombatScenario.from_dict(data['recipe'])
    if recipe.split!='train': raise ValueError('Heldout late start rejected')
    env=ObservableCombatAdapter(recipe,limits=EpisodeLimits(**data['limits']),reward_version=V7)
    for key in data['prefix']: advance(env,key)
    if env.outcome().done or env.information!=public_from_dict(data['public']):
        raise ValueError('Natural prefix/public mismatch or terminal snapshot')
    encode_entities(env.information)
    return env


def validate_course(document,sources):
    data=checked(document)
    if data['version']!=VERSION or not data['entries']: raise ValueError('Empty/incompatible course')
    expected=[]
    for witness in sources: expected.extend(export_witness(witness))
    if data['entries']!=expected: raise ValueError('Course does not match complete source witnesses')
    if len({e['sha256'] for e in expected})!=len(expected): raise ValueError('Duplicate late starts')
    return expected


def collect_suffix(entry,decide,model_version):
    """decide(public)->DynamicSearchResult. No optimizer or full-episode promotion.

    This explicit collector is available to the next versioned training runner;
    it does not silently change T3 jobs or accept suffixes into T3 Replay.
    """
    if not model_version: raise ValueError('Model version required')
    env=restore(entry); rows=[]
    while not env.outcome().done:
        info=env.information; result=decide(info)
        rows.append(dict(step_index=len(rows),absolute_step=info.history.decisions,
            public=public_snapshot(info),observation=pack_observation(encode_entities(info)),
            chosen_action=result.action,policy_target=result.policy_target,
            root_visits=result.root_visits,simulations=result.simulations,forced=result.forced_action))
        advance(env,result.action)
    for row in rows: row['z']=env.outcome().reward
    record=normalized(dict(version=REPLAY_VERSION,course_version=VERSION,start=entry,
        model_version=model_version,rows=rows,final_public=public_snapshot(env.information),
        outcome=asdict(env.outcome()),value_scope='original-battle-terminal',
        evaluation_scope='late-diagnostic-only'))
    validate_suffix(record)
    return record


def validate_suffix(record):
    import math
    if (record['version']!=REPLAY_VERSION or record['course_version']!=VERSION
            or record['value_scope']!='original-battle-terminal'
            or record['evaluation_scope']!='late-diagnostic-only' or not record['rows']):
        raise ValueError('Invalid suffix contract')
    env=restore(record['start'])
    for index,row in enumerate(record['rows']):
        info=env.information; keys=set(action_candidates(info)[1])
        pi,visits=row['policy_target'],row['root_visits']; n=row['simulations']
        if (row['step_index']!=index or row['absolute_step']!=info.history.decisions
                or public_from_dict(row['public'])!=info
                or row['observation']!=pack_observation(encode_entities(info))
                or row['chosen_action'] not in keys or set(pi)!=keys or set(visits)!=keys
                or any(not math.isfinite(v) or v<0 for v in pi.values())
                or any(type(v)!=int or v<0 for v in visits.values())
                or not math.isclose(sum(pi.values()),1,abs_tol=1e-6)):
            raise ValueError('Invalid suffix row')
        if row['forced']:
            if len(keys)!=1 or n!=0 or sum(visits.values())!=0: raise ValueError('Invalid forced suffix')
        elif type(n)!=int or n<1 or sum(visits.values())!=n or any(
                not math.isclose(pi[k],visits[k]/n,abs_tol=1e-7) for k in keys):
            raise ValueError('Invalid suffix visit target')
        advance(env,row['chosen_action'])
    if (not env.outcome().done or public_from_dict(record['final_public'])!=env.information
            or record['outcome']!=normalized(asdict(env.outcome()))
            or any(r['z']!=env.outcome().reward for r in record['rows'])):
        raise ValueError('Invalid suffix terminal/labels')
    return True


def training_rows(records,course,protocol):
    """Explicit bridge to Learner.update_entities; never mixes old Replay storage.

    Caller chooses sampling/optimizer budgets in a separately authorized runner.
    Every suffix must originate in this frozen course, whose combinations/IDs
    are included in the protocol leakage check.
    """
    from .t4_protocol import validate_protocol
    checked(course)
    validate_protocol(protocol,course['entries'])
    admitted={entry['sha256'] for entry in course['entries']}
    rows=[]
    for record in records:
        if record['start']['sha256'] not in admitted: raise ValueError('Suffix outside frozen course')
        validate_suffix(record)
        rows.extend(record['rows'])
    if not rows: raise ValueError('No natural training rows')
    return rows


def sample_entry(course,rng):
    """v1: uniform source trajectory, then uniform unique prefix within source.

    Multiple category tags at one boundary never multiply its sampling weight.
    Mixing ratio with first-form episodes is a future runner configuration.
    """
    from copy import deepcopy
    data=checked(course)
    if data['version']!=VERSION or not data['entries']: raise ValueError('Empty/incompatible course')
    groups={}
    for entry in data['entries']:
        checked(entry)
        groups.setdefault(entry['source_sha256'],{}).setdefault(content_hash(entry['prefix']),entry)
    sources=sorted(groups)
    states=groups[sources[int(rng.integers(len(sources)))]]
    return deepcopy(states[sorted(states)[int(rng.integers(len(states)))]])
