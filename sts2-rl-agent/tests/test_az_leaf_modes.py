"""Leaf backup semantics, frozen jobs and recovery configuration boundaries."""
from dataclasses import dataclass
import pytest

from sts2_env.az import all_runner as runner
from sts2_env.az.config import EpisodeLimits
from sts2_env.az.dynamic_search import search_dynamic
from sts2_env.az.search_config import DYNAMIC_RISK

CONFIG = 'configs/az_all_xs_v1/config.json'
PROTOCOL = 'configs/az_all_xs_v1/protocol.json'


@dataclass
class State:
    action: str = ''
    terminal: bool = False

    def key(self):
        return self.action, self.terminal

    def terminal_value(self):
        return -1. if self.terminal else None


class Particle:
    def __init__(self, info, rng, terminal=False):
        self.info, self.terminal = info, terminal

    def step(self, action):
        self.info = State(action, self.terminal)
        return self.info


def search(mode='heuristic', mix=.5, terminal=False, depth=1, budget=2):
    def heuristic(root, leaf):
        return -.75 if leaf.terminal else (.8 if leaf.action == 'a' else -.8)
    def predict(state):
        assert not state.terminal  # terminal reward must not be replaced by a network call
        return {'a': .5, 'b': .5}, (-.4 if state.action == 'a' else .4)
    return search_dynamic(State(), lambda info, rng: Particle(info, rng, terminal),
        predict, lambda _: ('a', 'b'), model_version='toy', budget=budget,
        max_depth=depth, c_puct=10, search_version=DYNAMIC_RISK, cutoff_reward=heuristic,
        leaf_mode=mode, value_mix=mix)


@pytest.mark.parametrize('mode,mix,expected', [
    ('heuristic', .5, .8), ('learned', .5, -.4), ('mixed', .25, .5),
    ('mixed', 0., .8), ('mixed', 1., -.4)])
def test_real_puct_backup_uses_selected_evaluator(mode, mix, expected):
    for depth, budget in [(1, 2), (1, 12), (3, 12)]:
        result = search(mode, mix, depth=depth, budget=budget)
        if depth == 1:
            assert result.root.edges['a'].q == pytest.approx(expected)
            assert result.root.edges['b'].q == pytest.approx(-expected)
        assert sum(result.root_visits.values()) == budget
        assert sum(result.policy_target.values()) == pytest.approx(1.)
        assert result.root_visits == search(mode, mix, depth=depth, budget=budget).root_visits


@pytest.mark.parametrize('mode', ['heuristic', 'learned', 'mixed'])
def test_terminal_reward_is_authoritative_in_every_mode(mode):
    result = search(mode, terminal=True)
    assert all(e.q == -.75 for e in result.root.edges.values())


def test_search_reports_actual_depth_separately_from_budget():
    shallow = search('learned', depth=1, budget=32)
    assert shallow.simulations == 32
    assert shallow.mean_depth == shallow.max_depth_reached == 1
    deeper = search('learned', depth=256, budget=32)
    assert deeper.simulations == 32
    assert 1 <= deeper.mean_depth <= deeper.max_depth_reached <= 32


@pytest.mark.parametrize('settings', [dict(leaf_mode='typo'), dict(value_mix=-.1),
    dict(value_mix=1.1), dict(value_mix=float('nan')), dict(value_mix=True),
    dict(collection_model='candidate')])
def test_invalid_settings_rejected(settings):
    with pytest.raises(ValueError):
        runner.effective_settings(runner.load_frozen_config(CONFIG), **settings)


def test_config_and_overrides():
    config = runner.load_frozen_config(CONFIG)
    config['search'].update(leaf_mode='mixed', value_mix=.25)
    config['training']['collection_model'] = 'learner'
    settings = runner.effective_settings(config)
    assert (settings['leaf_mode'], settings['value_mix'], settings['collection_model']) == ('mixed', .25, 'learner')
    assert runner.effective_settings(config, leaf_mode='learned')['leaf_mode'] == 'learned'


@pytest.mark.parametrize('mode', ['heuristic', 'learned', 'mixed'])
def test_serial_spawn_and_replay_modes(tmp_path, mode):
    from sts2_env.az.self_play import initialize_worker, Collector
    initialize_worker()
    config = runner.load_frozen_config(CONFIG)
    model = runner.fresh_model(config, 7)
    kwargs = dict(iteration=0, budget=2, limits=EpisodeLimits(max_turns=1, max_decisions=2),
                  version='leaf-fixture', seed=7, leaf_mode=mode, value_mix=.25)
    recipes = runner.training_recipes(0, 2)
    serial = runner.collect(model, recipes, error_dir=tmp_path/'serial/errors', **kwargs)
    # Fail the test on worker errors instead of allowing the runner's serial fallback.
    class StrictCollector(Collector):
        def collect(self, jobs):
            try:
                return super().collect(jobs)
            except Exception as exc:
                pytest.fail(f'Spawn collection failed: {exc}')
    with StrictCollector(2) as pool:
        parallel = runner.collect(model, recipes, error_dir=tmp_path/'parallel/errors',
                                  workers=2, collector=pool, **kwargs)
    for a, b in zip(serial, parallel):
        for e in (a, b):
            for row in e['rows']:
                row.pop('search_seconds')
        assert a == b
    # Use an unmodified episode to verify compatibility and disk reopening.
    episode = runner.collect(model, recipes[:1], error_dir=tmp_path/'replay-errors', **kwargs)[0]
    replay_kw = dict(content_version=config['content'], reward_version=config['reward'],
                     leaf_mode=mode, value_mix=.25)
    replay = runner.EntityReplayBuffer(tmp_path/'replay', **replay_kw)
    replay.commit(episode)
    assert runner.EntityReplayBuffer(tmp_path/'replay', **replay_kw).size == len(episode['rows'])
    other = 'learned' if mode != 'learned' else 'heuristic'
    with pytest.raises(ValueError, match='compatibility|version'):
        runner.EntityReplayBuffer(tmp_path/'replay', **dict(replay_kw, leaf_mode=other))
    wrong = runner.EntityReplayBuffer(tmp_path/'wrong', **dict(replay_kw, leaf_mode=other))
    with pytest.raises(ValueError):
        wrong.commit(episode)
    if mode == 'mixed':
        with pytest.raises(ValueError, match='version'):
            runner.EntityReplayBuffer(tmp_path/'replay', **dict(replay_kw, value_mix=.75))


def test_resume_rejects_changed_search_or_collection(tmp_path, monkeypatch):
    from tests.test_az_training_readiness import mock_pipeline
    mock_pipeline(monkeypatch)
    kwargs = dict(iterations=1, episodes=1, updates=1, budget=1, batch_size=2,
                  leaf_mode='mixed', value_mix=.25, collection_model='learner')
    report = runner.run(CONFIG, PROTOCOL, tmp_path, **kwargs)
    assert report['history'][0]['collection_checkpoint'] == 'initial.pt'
    for change in [dict(leaf_mode='learned'), dict(value_mix=.75), dict(collection_model='champion')]:
        with pytest.raises(ValueError, match='configuration'):
            runner.run(CONFIG, PROTOCOL, tmp_path, resume=True, **dict(kwargs, **change))


def test_runner_cli_passes_options(monkeypatch, tmp_path):
    def run(*args, **kwargs):
        assert kwargs['leaf_mode'] == 'mixed'
        assert kwargs['value_mix'] == .3
        assert kwargs['collection_model'] == 'learner'
        return dict(version='fixture', history=[], final_validation={})
    monkeypatch.setattr(runner, 'run', run)
    runner.main(['--out', str(tmp_path), '--leaf-mode', 'mixed', '--value-mix', '.3',
                 '--collection-model', 'learner'])


def test_heldout_evaluation_forwards_modes(tmp_path, monkeypatch):
    from dataclasses import replace
    from sts2_env.az.evaluation import evaluate
    from sts2_env.az import dynamic_search
    original = dynamic_search.plan_dynamic
    calls = []
    def plan(*args, **kwargs):
        calls.append((kwargs['leaf_mode'], kwargs['value_mix']))
        return original(*args, **kwargs)
    monkeypatch.setattr(dynamic_search, 'plan_dynamic', plan)
    model = runner.fresh_model(runner.load_frozen_config(CONFIG), 7)
    rows = evaluate(model, 'fixture', [replace(runner.training_recipes(0, 1)[0], split='validation')],
                    simulations=2, limits=EpisodeLimits(max_turns=1, max_decisions=2),
                    error_dir=tmp_path, reward_version='risk-terminal-v7',
                    search_version=DYNAMIC_RISK, leaf_mode='mixed', value_mix=.3)
    assert calls and set(calls) == {('mixed', .3)}
    assert rows[0]['leaf_mode'] == 'mixed' and rows[0]['value_mix'] == .3
