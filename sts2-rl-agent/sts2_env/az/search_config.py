"""Search-label semantics; legacy defaults stay reproducible."""
LEGACY = "legacy-zero-index-v1"
PRIOR = "prior-tie-v1"
PARENT = "parent-fpu-v1"
COMBINED = "parent-prior-v1"
DYNAMIC = "dynamic-key-puct-v1"
DYNAMIC_RISK = "dynamic-risk-puct-v2"
DYNAMIC_VERSIONS = (DYNAMIC, DYNAMIC_RISK)
VERSIONS = (LEGACY, PRIOR, PARENT, COMBINED)


def validate_search(version):
    if version not in VERSIONS + DYNAMIC_VERSIONS:
        raise ValueError("Unknown search version")
    return version
