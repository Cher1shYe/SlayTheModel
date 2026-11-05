import sys, json
sys.path.insert(0, '.')
import hashlib, pathlib
from agent.common import sim, LOADED_SIMULATOR_SHA256
import agent.armg as armg
from agent import content_profile
from agent.run_reward import DeckElo
print(json.dumps({
    "ruleset": sim.ENGINE_RULESET_ID,
    "public_obs_version": int(sim.PUBLIC_OBS_VERSION),
    "public_obs_dim": int(sim.PUBLIC_OBS_DIM),
    "public_combat_obs_dim": int(sim.PUBLIC_COMBAT_OBS_DIM),
    "public_run_dim": int(sim.PUBLIC_RUN_DIM),
    "action_schema_version": int(sim.ACTION_SCHEMA_VERSION),
    "action_feat_dim": int(sim.ACTION_FEAT_DIM),
    "card_feat_dim": int(sim.CARD_FEAT_DIM),
    "armg_feature_version": armg.ARMG_FEATURE_VERSION,
    "armg_obs_dim": armg.ARMG_OBS_DIM,
    "armg_action_dim": armg.ARMG_ACTION_DIM,
    "simulator_sha256": LOADED_SIMULATOR_SHA256,
    "content_profile": content_profile.identity(),
    "elo_snapshot": DeckElo().identity(),
    "native_parity_complete": bool(sim.NATIVE_PARITY_COMPLETE),
    "target_dll_sha256": sim.TARGET_GAME_DLL_SHA256,
}, ensure_ascii=False, indent=2, default=str))
