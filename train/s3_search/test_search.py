import numpy as np

from rasch import Fit, fit, screen, select


def test_screen_includes_endpoints_and_marginalizes_prior():
    rates = np.array([[.149, .15, .85, .851]])
    pilot = Fit(np.arange(5), np.diag(np.arange(1, 6)), rates)
    keep, (mean, cov) = screen(pilot)
    np.testing.assert_array_equal(keep, [1, 2])
    np.testing.assert_array_equal(mean, [1, 2, 4])
    np.testing.assert_array_equal(cov, np.diag([2, 3, 5]))


def test_new_child_inherits_parent_without_recounting_calibration():
    pilot = fit(np.array([[0., 0.], [1., 1.]]), [-1, 0])
    _, prior = screen(pilot)
    future = np.full((3, 2), np.nan)
    inherited = fit(future, [-1, 0, 1], prior)
    np.testing.assert_allclose(inherited.mean[:-1], prior[0])
    np.testing.assert_allclose(inherited.mean[-1], prior[0][-1])
    np.testing.assert_allclose(inherited.cov[:-1, :-1], prior[1])
    future[2] = 1
    updated = fit(future, [-1, 0, 1], prior)
    assert updated.pred[2].mean() > inherited.pred[2].mean()


def test_two_survivors_and_two_distinct_historical_parents():
    retained, extra = select([.90, .80, .75, .88, .92, .91], [1, 2, 4, 5])
    assert retained == [4, 5]
    assert extra == [0, 3]


def test_parent_feedback_includes_pending_and_explains_only_weaker_children():
    import json
    import sqlite3
    from search import TRIALS, parent_feedback

    db = sqlite3.connect(":memory:")
    db.execute(TRIALS)
    lineage = [-1, 0, 0, 1, 0]
    candidates = [dict(id=i, parent=p, hash=str(i), direction=f"direction {i}")
                  for i, p in enumerate(lineage)]
    for i, wins in [(0, [True, False, True]), (1, [False, True, False])]:
        for seed, won in enumerate(wins):
            row = dict(won=won, reason="terminal" if won else "loop", screen="CARD_GRID")
            db.execute("INSERT INTO trials VALUES (?,?,?,?)", (str(i), seed, won, json.dumps(row)))
    report = dict(candidates=[dict(id=i, estimate=x) for i, x in enumerate([.6, .4, .7, .3])])
    feedback = parent_feedback(0, candidates, report, db, [0, 1])
    weak, strong, pending = feedback["children"]
    assert [c["direction"] for c in feedback["children"]] == ["direction 1", "direction 2", "direction 4"]
    assert weak["parent_only_wins"] == [0] and weak["child_only_wins"] == [1]
    assert "loop/CARD_GRID 1 局" in weak["problem_summary"]
    assert "problem_summary" not in strong and pending["result"] is None
    assert parent_feedback(4, candidates, report, db, [])["children"] == []
    db.close()


def test_admit_requires_direction_and_restores_it_on_resume(tmp_path):
    import pytest
    import torch
    from search import admit

    base = dict(model={"w": torch.zeros(1)}, model_config={})
    req = dict(id=1, parent=0, submit="submit.pt")
    ck = dict(model={"w": torch.ones(1)}, model_config={})
    for direction in (None, " "):
        ck["direction"] = direction
        torch.save(ck, tmp_path / req["submit"])
        with pytest.raises(ValueError, match="direction"):
            admit(tmp_path, req, base["model"], [], base)
    ck["direction"] = "a direction chosen by the proposer"
    torch.save(ck, tmp_path / req["submit"])
    record = admit(tmp_path, req, base["model"], [], base)
    assert record["direction"] == ck["direction"]
    assert admit(tmp_path, req, base["model"], [], base) == record

def test_live_seed_screening_recomputed_and_cache_reused():
    from live_batches import select_batch, use_results

    used = np.zeros(4, dtype=bool)
    initial = np.array([[.9, .1, .5, .15], [.9, .1, .5, .85]])
    assert select_batch(initial, used, range(4)) == [3, 2]
    used[3] = True
    updated = np.array([[.8, .1, .99, .5], [.6, .2, .96, .5]])
    assert select_batch(updated, used, range(4)) == [0, 1]
    obs = np.full((3, 4), np.nan)
    result = np.array([[1.], [0.]])
    for _ in range(2):
        use_results(obs, [0, 2], [1], result)
    assert np.isfinite(obs).sum() == 2

def test_reveal_refits_each_new_answer_and_skips_shared_history():
    from live_batches import reveal_block

    obs = np.array([[1., 0.], [np.nan, np.nan], [np.nan, np.nan]])
    parents = [-1, 0, 0]
    start = fit(obs, parents)
    events = []
    def record(c, q, posterior):
        events.append((c, q, int(np.isfinite(obs).sum()), posterior.pred.copy()))
    z = reveal_block(obs, parents, [0, 1, 2], 0, [1, 1, 0], start, record)
    assert [(c,q,n) for c,q,n,_ in events] == [(1,0,3), (2,0,4)]
    assert not np.array_equal(events[0][3], events[1][3])
    assert reveal_block(obs, parents, [0, 1, 2], 0, [1, 1, 0], z, record) is z
    assert len(events) == 2
