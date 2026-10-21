from collections import Counter
from scripts.run_native_replay_ablation import schedules, split_episodes


def test_holdout_keeps_whole_episodes_and_is_order_independent():
    recipes = [dict(encounter=f'e{i%3}', scenario_id=str(i)) for i in range(30)]
    held = split_episodes(recipes)
    assert held == split_episodes(list(reversed(recipes)))
    assert len(held) == 6
    assert Counter(r['encounter'] for r in recipes if r['scenario_id'] in held) == {
        'e0':2, 'e1':2, 'e2':2}


def test_replay_preserves_update_sample_budget_and_resumable_schedule():
    sizes = ([64]*292 + [37])*3
    for replay in (False, True):
        batches = list(schedules({0:999, 1:1001}, sizes, replay))
        assert len(batches) == 879 and sum(map(len, batches)) == 56175
        assert [len(b) for b in batches] == sizes
        assert batches == list(schedules({0:999, 1:1001}, sizes, replay))
        counts = Counter(k for b in batches for k,i in b)
        if replay:
            assert abs(counts[0]-counts[1]) == 1
            for k, n in ((0,999), (1,1001)):
                cycle = [i for b in batches for r,i in b if r == k][:n]
                assert sorted(cycle) == list(range(n))
        else:
            assert counts == {1:56175}
