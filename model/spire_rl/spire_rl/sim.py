"""Locates and imports the C++ simulator extension (``sts2_sim``)."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIM_DIR = REPO_ROOT / "artifacts" / "dev" / "cpp-native-aligned-20261031" / "simulator"


def load_sim():
    """Import ``sts2_sim`` from $STS2_SIM_DIR or the default port location."""
    path = Path(os.environ.get("STS2_SIM_DIR", DEFAULT_SIM_DIR))
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    try:
        module = importlib.import_module("sts2_sim")
    except ImportError as exc:  # pragma: no cover - environment problem
        raise ImportError(
            f"cannot import sts2_sim from {path}; build it with "
            "`python artifacts/dev/cpp-native-aligned-20261031/validation/build_local.py` "
            "or point STS2_SIM_DIR at the directory holding the extension") from exc
    if not hasattr(module, "MACRO_OBS_VERSION"):
        raise ImportError("sts2_sim is too old: rebuild it (macro_observation is missing)")
    return module


sim = load_sim()


def identity() -> dict:
    """Simulator properties a checkpoint depends on."""
    return {
        "ruleset": str(sim.ENGINE_RULESET_ID),
        "macro_obs_version": int(sim.MACRO_OBS_VERSION),
        "macro_entity_num": int(sim.MACRO_ENTITY_NUM),
        "macro_cand_num": int(sim.MACRO_CAND_NUM),
        "macro_phases": int(sim.MACRO_PHASES),
        "macro_vocab": [int(v) for v in sim.macro_vocab()],
        "run_action_types": int(sim.RUN_ACTION_TYPES),
    }
