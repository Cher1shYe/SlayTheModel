"""Public audit codec and complete episode collection for the entity backend."""
from dataclasses import asdict, fields
from .config import EpisodeLimits, content_hash, derive_seed
from .information import InformationState, PublicHistory
from .entity_encoder import encode_entities
from .entity_replay import pack_observation, EntityReplayBuffer
from .content import ALL_CONTENT
from .action_candidates import action_candidates
from .dynamic_search import plan_dynamic


def public_snapshot(info):
    data = asdict(info)
    del data['legal_mask']
    data['legal_actions'] = [i for i,v in enumerate(info.legal_mask) if v]
    return data


def public_from_dict(data):
    values = dict(data)
    legal_actions = values.pop('legal_actions')
    history = dict(values['history'])
    for f in fields(PublicHistory):
        if isinstance(f.default, tuple):
            history[f.name] = tuple(history[f.name])
    from .card_generation import CardGeneration
    from .card_upgrades import CardUpgrade
    from .morph import CardTransformation
    from .selection_batch import TurnPayment
    for name,cls in [('generated',CardGeneration),('upgraded',CardUpgrade),('transformed',CardTransformation),('payments',TurnPayment)]:
        history[name]=tuple(cls(**v) for v in history[name])
    history['public_events']=tuple(
        (v[0], v[1], v[2], tuple(tuple(intent) for intent in v[3]), v[4])
        if v[0] == 'enemy_intent_action' else tuple(v)
        for v in history.get('public_events', ()))
    history['basic_plays']=tuple(tuple(v) for v in history.get('basic_plays', ()))
    values['basic_statuses']=tuple(tuple(v) for v in values.get('basic_statuses', ()))
    history['ability_plays']=tuple(tuple(v) for v in history.get('ability_plays', ()))
    values['player_abilities']=tuple(tuple(v) for v in values.get('player_abilities', ()))
    history['roster_moves']=tuple(tuple(v) for v in history['roster_moves'])
    values['history'] = PublicHistory(**history)
    values['limits'] = EpisodeLimits(**values['limits'])
    for name in ('hand', 'draw_composition', 'discard', 'exhaust', 'intent', 'known_top', 'known_bottom',
                 'known_deck', 'hand_states', 'enemies'):
        values[name] = tuple(values[name])
    from .card_state import PublicCardState
    def card(data):
        return PublicCardState(**{**data,'effect_vars':tuple(tuple(p) for p in data['effect_vars'])})
    values['hand_states']=tuple(card(v) for v in values['hand_states'])
    if values['pending_card'] is not None: values['pending_card']=card(values['pending_card'])
    if values['choice'] is not None:
        from .choice_state import PublicChoiceState,PublicChoiceOption
        c=values['choice']
        values['choice']=PublicChoiceState(**{**c,'selected':tuple(c['selected']),
            'options':tuple(PublicChoiceOption(o['pile'],o['index'],card(o['card'])) for o in c['options'])})
    if values['content_version'] == ALL_CONTENT:
        # All-content rosters carry visible intents per slot plus append-only
        # spawn metadata and per-power public bookkeeping.
        from .roster import EnemySlot
        values['enemies'] = tuple(EnemySlot(**{
            **e, 'powers': tuple(tuple(p) for p in e['powers']),
            'intents': tuple(tuple(i) for i in e['intents']), 'moves': tuple(e['moves'])})
            for e in values['enemies'])
    elif values['enemies']:
        from .summon import SlotState
        values['enemies']=tuple(SlotState(**{**e,'intent':tuple(e['intent']),'moves':tuple(e['moves'])}) for e in values['enemies'])
    if values['boss'] is not None:
        from .boss_reconstruction import BossEnemySnapshot
        b=values['boss']
        from .boss_phases import BossPhaseState
        values['boss']=BossEnemySnapshot(BossPhaseState(b['phase']['hp'],tuple(b['phase']['events']),b['phase']['version']),
            b['block'],tuple(tuple(p) for p in b['powers']),b['version']).validate()
    from .actions import action_size
    size=action_size(values['content_version'])
    if any(type(i)is not int or not 0<=i<size for i in legal_actions) or len(set(legal_actions))!=len(legal_actions):
        raise ValueError('Invalid sparse public action table')
    legal_set = set(legal_actions)
    mask = [i in legal_set for i in range(size)]
    values['legal_mask'] = tuple(mask)
    return InformationState(**values).validate()


def collect_entity_episode(job, model):
    diagnostic = {'job_id': job.job_id}
    try:
        return _collect_entity_episode(job, model, diagnostic)
    except Exception as exc:
        from pathlib import Path
        from .config import atomic_json
        diagnostic['error'] = repr(exc)
        atomic_json(Path(job.error_dir) / f'{content_hash([job.master_seed, job.iteration, job.job_id])}-public.json', diagnostic)
        raise


def _collect_entity_episode(job, model, diagnostic):
    from .adapter import ObservableCombatAdapter
    from .scenarios import CombatScenario
    recipe = CombatScenario.from_dict(job.scenario)
    if recipe.split != 'train':
        raise ValueError('Only training recipes may enter replay')
    env = ObservableCombatAdapter(recipe, limits=job.limits, error_dir=job.error_dir, reward_version=job.reward_version)
    identity = content_hash([job.master_seed, job.iteration, job.job_id])
    rows = []
    while not env.outcome().done:
        info = env.information
        diagnostic.update(public_information=public_snapshot(info), completed_decisions=len(rows))
        result = plan_dynamic(info, model, model_version=job.model_version, budget=job.simulations,
            training=True, temperature=1 if len(rows) < 10 else 0, search_version=job.search_version,
            search_seed=derive_seed(job.master_seed, job.iteration, job.job_id, f'search-{len(rows)}'))
        public = public_snapshot(info)
        rows.append(dict(episode_id=identity, step_index=len(rows), family_id=recipe.family_id,
            encounter_id=recipe.encounter_id,
            scenario_id=recipe.scenario_id, model_version=job.model_version,
            observation=pack_observation(encode_entities(info)), public_information=public, public_digest=content_hash(public),
            root_visits=result.root_visits, policy_target=result.policy_target, chosen_action=result.action,
            search_seconds=result.elapsed, search_simulations=result.simulations, forced_action=result.forced_action))
        _, mapping = action_candidates(info)
        env.step(mapping[result.action])
    outcome = asdict(env.outcome())
    for row in rows:
        row['z'] = outcome['reward']
    return dict(episode_id=identity, complete=True, split=recipe.split, rows=rows, outcome=outcome,
                final_public=public_snapshot(env.information),
                compatibility=EntityReplayBuffer.compatibility_for(info.content_version,info.reward_version), job_id=job.job_id, iteration=job.iteration)

