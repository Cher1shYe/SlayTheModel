"""Human command line over the simulator: public-only display, real choices, save/undo."""
import random

from spire_rl import play_cli as cli
from spire_rl import public_obs as p


def to_combat(backend):
    state = backend.observe()
    backend.act(next(i for i, a in enumerate(state.actions) if a.key.args[:1] == ("GOLDEN_PEARL",)))
    for _ in range(4):
        if backend.observe().facts["combat"] is not None:
            return backend.state
        backend.act(0)
    raise AssertionError("deterministic opening did not enter combat")


def test_scripted_runs_label_every_action_and_never_stop_on_the_contract():
    seen = set()
    for r in range(6):
        backend = cli.SimulatorBackend(f"CLITEST{r}", 10)
        rng, out, count = random.Random(r), [], [0]

        def read(prompt):
            count[0] += 1
            state = backend.state
            if state is None or count[0] > 2500:
                return "quit"
            for action in state.actions:
                seen.add(action.key.kind)
                assert not cli.action_label(action.key, state.facts).startswith(action.key.kind + "("), action.key
            if rng.random() < 0.05:
                return rng.choice(["deck", "draw", "discard", "exhaust", "map", "state", "help", "undo", "99999"])
            pool = [i for i, a in enumerate(state.actions) if a.key.kind == "play"] if state.facts["combat"] else []
            return str(rng.choice(pool or range(len(state.actions))))

        assert cli.play(backend, read=read, write=out.append) == 0
        assert not any("公共接口不支持" in text for text in out)
    assert {"neow_relic", "move", "play", "end_turn", "take_card"} <= seen


def test_display_shows_only_public_information():
    backend = cli.SimulatorBackend("PARITY0001", 10)
    state = to_combat(backend)
    shown = cli.render(state) + cli.render_pile(state.facts, "draw")
    original = list(backend.rc.battle.draw)
    changed = False
    for seed in range(1, 8):
        copy = backend.rc.clone()
        copy.battle.resample_hidden(seed)
        changed |= list(copy.battle.draw) != original
        other = p.from_simulator(copy)
        assert cli.render(other) + cli.render_pile(other.facts, "draw") == shown
    assert changed, "the test must really change the hidden draw order"


def test_undo_save_and_load_restore_the_same_public_screen(tmp_path):
    backend = cli.SimulatorBackend("PARITY0001", 10)
    state = to_combat(backend)
    before = cli.render(state)
    backend.save(tmp_path / "turn1.bin")
    backend.act(1)
    assert cli.render(backend.observe()) != before
    assert backend.undo() and cli.render(backend.observe()) == before
    backend.act(1)
    backend.load(tmp_path / "turn1.bin")
    assert cli.render(backend.observe()) == before


def test_out_of_range_choice_is_rejected_without_acting():
    backend = cli.SimulatorBackend("PARITY0001", 10)
    lines = iter(["42", "quit"])
    out = []
    cli.play(backend, read=lambda prompt: next(lines), write=out.append)
    assert any("没有编号 42" in text for text in out)
    assert backend.history == []
