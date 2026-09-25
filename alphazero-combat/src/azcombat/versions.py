"""Version contracts shared by training, export and evaluation gates.

These values are deliberately kept separate from the training-sample schema:
the JSONL envelope has its own version and must not be changed when the policy
observation ABI changes.
"""

ONNX_MANIFEST_FORMAT = "azcombat.onnx.v4"
FEATURE_ABI = "azcombat.features.v4"
CHECKPOINT_FORMAT = "azcombat.checkpoint.v3"
OBSERVATION_SCHEMA_VERSION = 3
SEARCH_SEMANTICS_VERSION = "azcombat.search.v3"
REWARD_LEDGER_VERSION = "azcombat.reward-ledger.v2"
