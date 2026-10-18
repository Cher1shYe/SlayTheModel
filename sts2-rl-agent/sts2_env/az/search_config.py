"""Search-label semantics; legacy defaults stay reproducible."""
LEGACY = "legacy-zero-index-v1"
PRIOR = "prior-tie-v1"
PARENT = "parent-fpu-v1"
COMBINED = "parent-prior-v1"
DYNAMIC = "dynamic-key-puct-v1"
DYNAMIC_RISK = "dynamic-risk-puct-v2"
DYNAMIC_VERSIONS = (DYNAMIC, DYNAMIC_RISK)
VERSIONS = (LEGACY, PRIOR, PARENT, COMBINED)

LEAF_MODES = ('heuristic', 'learned', 'mixed')


def leaf_settings(mode='heuristic', value_mix=.5):
    """Weight is the learned-value share, used only in mixed mode."""
    import math
    if mode not in LEAF_MODES:
        raise ValueError('Unknown leaf evaluation mode')
    if type(value_mix) not in (int, float) or not math.isfinite(value_mix) or not 0 <= value_mix <= 1:
        raise ValueError('value_mix must be finite and in [0, 1]')
    return dict(leaf_mode=mode, value_mix=float(value_mix))


def validate_search(version):
    if version not in VERSIONS + DYNAMIC_VERSIONS:
        raise ValueError("Unknown search version")
    return version
