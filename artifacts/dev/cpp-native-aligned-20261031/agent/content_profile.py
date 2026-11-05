"""Single-player Ironclad training/evaluation content profile.

The engine's ``RunContentProfile.SINGLE_PLAYER_TRAINING`` filters the event bag
(CrystalSphere is excluded) and every card-generation entry point already
rejects ``CF_MULTIPLAYER_ONLY`` cards. This module pins that configuration in
one place so training and evaluation cannot drift apart, records its identity
for checkpoints, and provides the runtime assertions the acceptance tests use.

It changes the native content distribution: one event is missing from the
generated pool. Do not report runs made with it as "unmodified native content".
"""
from __future__ import annotations

import hashlib
import json

from .common import CARD_COUNT, SCREEN, sim

PROFILE = sim.RunContentProfile.SINGLE_PLAYER_TRAINING
PROFILE_NAME = sim.run_content_profile_name(int(PROFILE))
EXCLUDED_EVENTS = ("CRYSTAL_SPHERE",)


def multiplayer_only_ids() -> frozenset[int]:
    """Card ids the engine flags as multiplayer-only (single-player rejects)."""
    return frozenset(i for i in range(1, CARD_COUNT) if sim.card_multiplayer_only(i))


def event_ids_for_act(act_type: int) -> list[int]:
    return list(sim.event_pool_profile(int(act_type), int(PROFILE)))


def identity() -> dict:
    """Stable identity of the active filtering configuration."""
    payload = {"profile": int(PROFILE), "name": PROFILE_NAME,
               "excluded_events": list(EXCLUDED_EVENTS),
               "event_pools": {str(act): event_ids_for_act(act) for act in range(4)}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "sha256": hashlib.sha256(encoded).hexdigest()}


_FORBIDDEN = frozenset(i for i in range(sim.event_count())
                       if sim.event_info(i)[0] in EXCLUDED_EVENTS)
_MULTIPLAYER = frozenset(i for i in range(1, sim.CARD_COUNT)
                         if sim.card_multiplayer_only(i))


def forbidden_event_ids() -> frozenset[int]:
    return _FORBIDDEN


def assert_run_is_clean(rc) -> None:
    """Fail loudly if a profile-forbidden event or card reached the run.

    Called after every simulated step by the training/evaluation harnesses so
    excluded content cannot be drawn and then silently skipped.
    """
    if int(rc.content_profile) != int(PROFILE):
        raise RuntimeError(f"run uses content profile {rc.content_profile}, expected {int(PROFILE)}")
    if int(rc.card_grid_kind) == 0 and rc.screen == SCREEN.EVENT:
        if int(rc.event_id) in _FORBIDDEN:
            raise RuntimeError(f"forbidden event {rc.event_name} reached the run")
    for row in rc.deck:
        if int(row[0]) in _MULTIPLAYER:
            raise RuntimeError(f"multiplayer card {sim.card_name(int(row[0]))} reached the deck")
    if rc.screen == SCREEN.COMBAT:
        for row in rc.battle.hand:
            if int(row[0]) in _MULTIPLAYER:
                raise RuntimeError(
                    f"multiplayer card {sim.card_name(int(row[0]))} reached combat")
