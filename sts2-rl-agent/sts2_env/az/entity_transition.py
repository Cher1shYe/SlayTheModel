"""Public audit codec and complete episode collection for the entity backend."""
from dataclasses import asdict, fields
from .config import EpisodeLimits, content_hash, derive_seed
from .information import InformationState, PublicHistory
from .entity_encoder import encode_entities
from .entity_replay import pack_observation, EntityReplayBuffer
from .action_candidates import starter_candidates
from .dynamic_search import plan_dynamic


def public_snapshot(info):
    data = asdict(info)
    del data['legal_mask']
    return data


def public_from_dict(data):
    values = dict(data)
    history = dict(values['history'])
    for f in fields(PublicHistory):
        if isinstance(f.default, tuple):
            history[f.name] = tuple(history[f.name])
    values['history'] = PublicHistory(**history)
    values['limits'] = EpisodeLimits(**values['limits'])
    for name in ('hand', 'draw_composition', 'discard', 'exhaust', 'intent', 'known_top', 'known_bottom',
                 'known_deck', 'hand_states', 'enemies'):
        values[name] = tuple(values[name])
    from .mechanic_registry import card_descriptor
    from sts2_env.core.constants import MAX_HAND_SIZE, MAX_ENEMIES
    mask = [False]*115
    if values['termination_reason'] is None:
        mask[0] = True
        for i, name in enumerate(values['hand']):
            d = card_descriptor(name)
            if values['energy'] >= d.cost:
                mask[1+MAX_HAND_SIZE+i*MAX_ENEMIES if d.target == 'enemy' else i+1] = True
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
            scenario_id=recipe.scenario_id, model_version=job.model_version,
            observation=pack_observation(encode_entities(info)), public_information=public, public_digest=content_hash(public),
            root_visits=result.root_visits, policy_target=result.policy_target, chosen_action=result.action,
            search_seconds=result.elapsed, search_simulations=result.simulations, forced_action=result.forced_action))
        _, mapping = starter_candidates(info)
        env.step(mapping[result.action])
    outcome = asdict(env.outcome())
    for row in rows:
        row['z'] = outcome['reward']
    return dict(episode_id=identity, complete=True, split=recipe.split, rows=rows, outcome=outcome,
                final_public=public_snapshot(env.information),
                compatibility=EntityReplayBuffer.compatibility_for(), job_id=job.job_id, iteration=job.iteration)
