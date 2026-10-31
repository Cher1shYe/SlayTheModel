"""64-bit Python boundary and explicit raw/string seed contracts."""
import json
from pathlib import Path

import pytest

from agent.common import sim


def test_raw_uint64_seed_is_not_truncated_or_double_hashed():
    for seed in (0, 22, 2**32 + 22, 2**63 + 7, 2**64 - 1):
        run = sim.RunContext()
        run.init(seed, 0)
        assert run.seed == seed
        assert json.loads(json.dumps({"seed": run.seed}))["seed"] == seed
        restored = sim.RunContext()
        assert restored.restore(run.snapshot())
        assert restored.seed == seed


def test_ascii_game_seed_uses_native_canonicalization_and_hash():
    fixture = Path(__file__).parents[1] / "simulator/tests/fixtures/native_rng_41cef1ea.json"
    for case in json.loads(fixture.read_text())["canonical"]:
        run = sim.RunContext()
        run.init_seed(case["text"], 0)
        assert run.seed == case["hash"]
    raw = sim.RunContext()
    raw.init(22, 0)
    text = sim.RunContext()
    text.init_seed("22", 0)
    assert raw.seed == 22
    assert text.seed == 1884361412985708340


def test_invalid_numeric_seed_and_unsupported_unicode_are_rejected():
    run = sim.RunContext()
    for invalid in (-1, 2**64):
        with pytest.raises((TypeError, OverflowError)):
            run.init(invalid, 0)
    with pytest.raises(ValueError, match="ASCII"):
        run.init_seed("é", 0)
