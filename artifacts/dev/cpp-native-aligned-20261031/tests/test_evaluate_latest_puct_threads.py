from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from deployment import evaluate_latest_puct_threads as threaded


def test_threads_use_per_episode_controllers_without_global_monkeypatch(monkeypatch, tmp_path):
    barrier = Barrier(2)
    sentinel = object()
    monkeypatch.setattr(threaded, '_models', lambda *_: (object(), object()))
    monkeypatch.setattr(threaded.base, '_mcts_plan', sentinel)
    threaded._search_slots = threaded.threading.BoundedSemaphore(2)

    class Controller:
        def __init__(self, _policy, seed, _activity, *_args):
            self.seed = seed
            self.decisions = 1
            self.floor_decisions = {(1, False, False): 1}
            self.normal_decisions = 1
            self.boss_decisions = self.elite_decisions = 0
            self.normal_simulations = 2000
            self.boss_simulations_completed = self.elite_simulations = 0
            self.simulations = 2000

        def plan(self):
            return self.seed

        def budget_for_context(self, *_args):
            return 2000

        def prepare_combat(self, *_args):
            pass

    def collect(seed, _model, **kwargs):
        barrier.wait(timeout=5)
        assert threaded.base._mcts_plan is sentinel
        assert kwargs['mcts_plan']() == seed + 1000
        return {'status': 'terminated', 'won': False, 'floor': 1, 'hp': 0,
                'mcts_searches': 1, 'mcts_simulations': 2000}

    monkeypatch.setattr(threaded.trainer, 'FloorRootPuctController', Controller)
    monkeypatch.setattr(threaded.base, 'collect_episode', collect)
    tasks = [(n, 0, n + 1000, 0, 'weights', True, 2000, 200, 0, 0,
              5000, str(tmp_path), 'oracle', 'policy') for n in (10, 20)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(threaded._play, tasks))
    assert [r['mcts_searches'] for r in results] == [1, 1]
    assert threaded.base._mcts_plan is sentinel
