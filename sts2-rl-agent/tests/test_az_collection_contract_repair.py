import gzip
import json
from pathlib import Path

import numpy as np
import pytest
import torch

from sts2_env.az import all_runner as runner
from sts2_env.az.config import derive_seed, EpisodeLimits
from sts2_env.az.dynamic_search import plan_dynamic
from sts2_env.az.entity_transition import public_from_dict, collect_entity_episode
from sts2_env.az.entity_encoder import encode_entities
from sts2_env.az.information import BeliefSampler
from sts2_env.az.self_play import CollectionJob


@pytest.mark.parametrize('job', [106, 254, 259])
def test_rejected_public_state_restores_and_searches(job):
    torch.set_num_threads(1)
    path = Path(__file__).parent / 'fixtures' / 'collection_contract_20261018' / f'000-{job}.json.gz'
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        diagnostic = json.load(f)
    info = public_from_dict(diagnostic['public_information'])
    obs = encode_entities(info)
    if job == 259:
        assert any(len(a.target_refs) > 5 for a in obs.actions)
    particle = BeliefSampler().sample(info, np.random.default_rng(0))
    assert particle.info == info
    model = runner.fresh_model(runner.load_frozen_config('configs/az_all_xs_v1/config.json'), 0)
    result = plan_dynamic(info, model, model_version='regression', budget=8, training=True,
        temperature=int(diagnostic['completed_decisions'] < 10), search_version=runner.SEARCH,
        search_seed=derive_seed(job, 0, f'000-{job}', f"search-{diagnostic['completed_decisions']}"))
    assert result.action in result.policy_target


@pytest.mark.parametrize('job_id', [106, 254, 259])
def test_previously_rejected_episode_completes(job_id, tmp_path):
    torch.set_num_threads(1)
    config = runner.load_frozen_config('configs/az_all_xs_v1/config.json')
    model = runner.fresh_model(config, 0)
    recipe = runner.training_recipes(0, 304)[job_id]
    job = CollectionJob(job_id=f'000-{job_id}', iteration=0, master_seed=job_id,
        scenario=recipe.to_dict(), checkpoint='', checkpoint_sha256='', model_version='regression',
        error_dir=str(tmp_path), simulations=8, limits=EpisodeLimits(max_turns=40, max_decisions=400),
        reward_version=runner.V7, search_version=runner.SEARCH)
    episode = collect_entity_episode(job, model)
    assert episode['complete'] and episode['outcome']['done']
    replay = runner.EntityReplayBuffer(tmp_path / 'replay', content_version=config['content'], reward_version=config['reward'])
    replay.commit(episode)
    assert replay.size == len(episode['rows'])


@pytest.mark.parametrize('job_id', [74, 258])
@pytest.mark.parametrize('leaf_mode', ['heuristic', 'learned'])
def test_second_round_contract_rejections(job_id, leaf_mode, tmp_path):
    torch.set_num_threads(1)
    config = runner.load_frozen_config('configs/az_all_xs_v1/config.json')
    model = runner.fresh_model(config, 0)
    recipe = runner.training_recipes(1, 304)[job_id]
    job = CollectionJob(job_id=f'001-{job_id}', iteration=1, master_seed=1000+job_id,
        scenario=recipe.to_dict(), checkpoint='', checkpoint_sha256='', model_version='regression',
        error_dir=str(tmp_path), simulations=8, limits=EpisodeLimits(max_turns=40, max_decisions=400),
        reward_version=runner.V7, search_version=runner.SEARCH, leaf_mode=leaf_mode)
    episode = collect_entity_episode(job, model)
    assert episode['complete'] and episode['outcome']['done']
    replay = runner.EntityReplayBuffer(tmp_path / 'replay', content_version=config['content'],
        reward_version=config['reward'], leaf_mode=leaf_mode)
    replay.commit(episode)
    assert replay.size == len(episode['rows'])


def test_dampen_restoration_preserves_casters_and_removal(simple_combat):
    from copy import deepcopy
    from sts2_env.core.enums import PowerId
    from sts2_env.az.power_memory import capture, restore
    from types import SimpleNamespace
    world = simple_combat
    card = world.hand[0]
    world.upgrade_card(card)
    world.apply_power_to(world.player, PowerId.DAMPEN, 1, applier=world.enemies[0])
    power = world.player.powers[PowerId.DAMPEN]
    power.add_caster(world.enemies[0])
    assert not card.upgraded
    memory = capture(world)
    particle = deepcopy(world)
    restored = particle.player.powers[PowerId.DAMPEN]
    restored._active = False
    restored._downgraded_cards = []
    restored.casters.clear()
    restore(particle, SimpleNamespace(power_memory=memory, enemies=particle.enemies, execution=''))
    assert capture(particle) == memory
    affected = list(restored._downgraded_cards)
    assert affected and restored.casters == {particle.enemies[0]}
    restored.on_ally_death(particle.player, particle.enemies[0], particle)
    assert PowerId.DAMPEN not in particle.player.powers
    assert all(c.upgraded for c in affected)
