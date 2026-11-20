"""Checklist A2: enemy move identity and the next-move distribution (no RNG read).

Ground truth: resample the hidden RNG (including the monster AI stream) many times,
actually end the turn (twice for the second step), and look at the move each enemy
really shows. Every observed move must be inside the predicted support, and the
observed frequencies must match the predicted probabilities.
"""
from collections import Counter, defaultdict
import random

import pytest

from spire_rl import public_obs as p
from spire_rl.sim import sim


def combat_states(seeds, every=7):
    rng = random.Random(seeds[0])
    for seed in seeds:
        rc = sim.RunContext(); rc.init(seed, 10)
        for step in range(1500):
            if rc.is_terminal:
                break
            s = p.from_simulator(rc)
            if not s.actions:
                break
            if s.facts["screen"] == "combat" and step % every == 0 and any(a.key.kind == "end_turn" for a in s.actions):
                yield rc, s
            plays = [i for i, a in enumerate(s.actions) if a.key.kind == "play"]
            pool = plays if plays and rng.random() < 0.85 else range(len(s.actions))
            p.step_simulator(rc, s, rng.choice(list(pool)))


def end_turn(rc):
    s = p.from_simulator(rc)
    end = next((i for i, a in enumerate(s.actions) if a.key.kind == "end_turn"), None)
    if end is None:
        return None
    p.step_simulator(rc, s, end)
    if rc.is_terminal or rc.screen != sim.RunScreen.COMBAT:
        return None
    after = p.from_simulator(rc)
    return after if after.facts["screen"] == "combat" else None


def test_step0_is_the_shown_move_and_steps_are_distributions():
    for _, s in combat_states(list(range(7100, 7110))):
        for e in s.facts["enemies"]:
            moves = e["moves"]
            assert len(moves) == 3 and len(moves[0]) == 1 and moves[0][0][2] == 1.0
            first = moves[0][0]
            attacks = [i for i in e["intents"] if i[0] in ("Attack", "DeathBlow")]
            if attacks and not e["stunned"]:
                assert first[3] == 0 and first[4] == attacks[0][1], (e["modelId"], first, e["intents"])
            for step in moves[1:]:
                assert sum(m[2] for m in step) == pytest.approx(1.0)


def test_observed_next_moves_follow_the_prediction():
    observed = defaultdict(Counter)   # (state key, step) -> Counter(move)
    predicted = {}
    checked = 0
    for case, (rc, s) in enumerate(combat_states(list(range(7200, 7240)))):
        targets = [e for e in s.facts["enemies"] if e["alive"] and not e["stunned"] and not e["reviving"]]
        if not targets:
            continue
        key0 = case
        for trial in range(24):
            copy = rc.clone()
            copy.battle.resample_hidden(1000 + trial)
            after1 = end_turn(copy)
            if after1 is None:
                continue
            after2 = end_turn(copy) if trial < 8 else None
            for e in targets:
                for k, after in ((1, after1), (2, after2)):
                    if after is None:
                        continue
                    now = next((x for x in after.facts["enemies"] if x["order"] == e["order"]), None)
                    if now is None or now["modelId"] != e["modelId"] or not now["alive"] or now["stunned"]:
                        continue
                    support = {m[0]: m[2] for m in e["moves"][k]}
                    shown = now["moves"][0][0][0]
                    assert shown in support, (e["modelId"], k, shown, support)
                    observed[(key0, e["order"], k)][shown] += 1
                    predicted[(key0, e["order"], k)] = support
                    checked += 1
    assert checked > 1500, checked
    # Frequencies: Pearson chi-square over every random step-1 choice (observed vs
    # predicted counts), pooled. Under a correct prediction chi2/df is about 1; a wrong
    # weight table shows up as a large ratio. Sampling noise alone stays well below 1.6.
    chi2 = df = 0.0
    for key, counts in observed.items():
        n = sum(counts.values())
        support = predicted[key]
        if key[2] != 1 or n < 20 or len(support) < 2:
            continue
        chi2 += sum((counts.get(m, 0) - n * q) ** 2 / (n * q) for m, q in support.items() if q > 0)
        df += len(support) - 1
    assert df >= 40, df
    assert chi2 / df < 1.6, (chi2, df)


def test_prediction_ignores_the_hidden_ai_stream():
    for rc, s in combat_states(list(range(7300, 7305))):
        base = [e["moves"] for e in s.facts["enemies"]]
        for seed in range(1, 6):
            copy = rc.clone(); copy.battle.resample_hidden(seed)
            assert [e["moves"] for e in p.from_simulator(copy).facts["enemies"]] == base
