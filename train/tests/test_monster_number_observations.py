"""Public numeric state follows monster effects; isolated simulator scenarios."""
import numpy as np

from spire_rl.sim import sim
from spire_rl import public_obs as public


def scenario(encounter):
    run = sim.RunContext()
    run.init_seed("PARITY0001", 10)
    for _ in range(12):
        if run.screen == sim.RunScreen.COMBAT:
            break
        state = public.from_simulator(run)
        choice = next((i for i, action in enumerate(state.actions)
                       if action.key.kind == "neow_relic" and action.key.args[0] == "GOLDEN_PEARL"), 0)
        assert public.step_simulator(run, state, choice)
    assert run.screen == sim.RunScreen.COMBAT
    defend = next(i for i in range(1, sim.CARD_COUNT)
                  if sim.card_name(i) == "Defend")
    # Keep a real run's combat phase, replace only the isolated battle fixture.
    run.battle.init(int(getattr(sim.Encounter, encounter)), 2718, [defend] * 20,
                    [False] * 20, 10, 9999, 9999)
    return run


def test_aeonglass_public_amount_counter_and_hidden_state():
    run = scenario("SETUP_AEONGLASS_BOSS")
    ident = "POWER.WITHERING_PRESENCE_POWER"
    before = public.from_simulator(run)
    assert all(row[0] != ident for row in before.facts["powers"])
    power = next(row for row in before.facts["enemies"][0]["powers"] if row[0] == ident)
    assert power == (ident, 6, 6, (("CardsLeft", 6),))
    action = next(a for a in run.battle.legal_actions() if a[0] == int(sim.ActionType.PLAY_CARD))
    assert run.battle.step(*action)
    after = public.from_simulator(run)
    power = next(row for row in after.facts["enemies"][0]["powers"] if row[0] == ident)
    assert power == (ident, 6, 5, (("CardsLeft", 5),))
    copy = run.clone()
    copy.battle.resample_hidden(981)
    cloned = public.from_simulator(copy)
    assert public.differences(after, cloned) == []
    expected, actual = public.encode(after), public.encode(cloned)
    for field in ("kind", "id", "num", "cand_type", "cand_index", "cand_num"):
        np.testing.assert_array_equal(getattr(expected, field), getattr(actual, field))


def test_prism_growth_updates_public_tainted_values_in_existing_piles():
    run = scenario("SETUP_INFESTED_PRISMS_ELITE")
    def amounts():
        state = public.from_simulator(run)
        return [affliction[1] for card in state.facts["cards"] for affliction in card["afflictions"]
                if affliction[0] == "AFFLICTION.TAINTED"]
    assert amounts() and set(amounts()) == {3}
    for _ in range(5):
        action = next(a for a in run.battle.legal_actions() if a[0] == int(sim.ActionType.END_TURN))
        assert run.battle.step(*action)
        if set(amounts()) != {3}:
            break
    assert set(amounts()) == {6}
