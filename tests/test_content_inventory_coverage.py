"""The coverage report must not claim every card is tested.

The 2026-11-04 audit found ``(names | refs) & cpp_tests | py_tests`` in
``scripts/content_inventory.py``: ``&`` binds tighter than ``|``, so every
card whose reference list touched *any* Python file counted as tested, and a
"zero untested cards" claim could not be supported. This pins the corrected
intersection on the real tables.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "content_inventory.py"


@pytest.fixture(scope="module")
def inventory():
    if not SCRIPT.exists():
        pytest.skip("inventory script absent")
    spec = importlib.util.spec_from_file_location("content_inventory", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cards = module.parse_cards(module.read(module.SIM / "include/sts2/cards_generated.inc"))
    cpp_tests = {p.name for p in module.SIM.glob("tests/*.cpp")}
    py_tests = {p.name for p in ROOT.glob("tests/*.py")}
    refs = module.reference_index("CardId")
    names = module.name_refs({c["id"]: c["name"] for c in cards})
    return module, cards, cpp_tests, py_tests, refs, names


def _tested(card, cpp_tests, py_tests, refs, names):
    seen = names.get(card["id"], set()) | refs.get(card["id"], set())
    return sorted((seen & cpp_tests) | (seen & py_tests))


def test_implementation_only_references_are_not_counted_as_tested(inventory):
    """A card implemented in cards_*.cpp is not thereby covered by a test."""
    _, cards, cpp_tests, py_tests, refs, names = inventory
    implementation_only = [c for c in cards
                           if refs.get(c["id"]) and not (_tested(c, cpp_tests, py_tests,
                                                                 refs, names))]
    assert implementation_only, "some cards are referenced only by source files"
    for card in implementation_only:
        assert refs[card["id"]] - (cpp_tests | py_tests), card["id"]


def test_a_reference_outside_the_test_suites_does_not_count(inventory):
    _, cards, cpp_tests, py_tests, refs, names = inventory
    for card in cards:
        for name in _tested(card, cpp_tests, py_tests, refs, names):
            assert name in cpp_tests or name in py_tests


def test_untested_count_is_not_zero_for_the_whole_table(inventory):
    _, cards, cpp_tests, py_tests, refs, names = inventory
    untested = [c["id"] for c in cards
                if not _tested(c, cpp_tests, py_tests, refs, names)]
    assert len(untested) == 368
