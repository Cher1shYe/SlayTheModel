"""Every simulator card must encode exactly like the native card of the same model."""
import numpy as np

from parity import card_encoding_audit as audit


def test_all_cards_match_native_identity_facts_and_encoded_rows():
    report = audit.audit()
    assert report["issues"] == [], report["issues"][:5]
    assert report["compared_variants"] > 1100  # every card x upgrade level
    assert {e["card"] for e in report["exceptions"]} == {"STARDUST", "MAD_SCIENCE"}


def test_audit_detects_a_public_difference(monkeypatch):
    """Guard against a vacuous pass: a changed keyword must be reported."""
    from spire_rl.sim import sim
    real = sim.public_card_template

    def tampered(card_id, upgraded=False):
        view = real(card_id, upgraded)
        if view["modelId"] == "CARD.BASH":
            view["keywords"] = ["Exhaust"]
        return view

    monkeypatch.setattr(sim, "public_card_template", tampered)
    report = audit.audit()
    fields = {(i["card"], i["field"]) for i in report["issues"]}
    assert ("BASH", "facts.keywords") in fields and ("BASH", "encoded_row") in fields
