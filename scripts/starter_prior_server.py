"""Resident inference bridge; no Python world reconstruction or simulation.

Experimental native-starter-prior-v1 feature adapter for a frozen ALL checkpoint.
Only three unmodified starter cards and deterministic no-player-power encounters.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from types import SimpleNamespace as NS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--checkpoint', required=True)
    args = parser.parse_args()
    os.chdir(args.source)  # Legacy static card registry resolves reference docs from cwd.
    sys.path.insert(0, args.source)
    import torch
    torch.set_num_threads(1)
    from sts2_env.az.model_factory import load_transformer_checkpoint
    from sts2_env.az.entity_encoder import Entity, EntityObservation, ActionCandidate, numeric
    from sts2_env.az.expanded_entities import card_entity, pile_state
    from sts2_env.az.all_entities import enemy_entities
    from sts2_env.az.monster_registry import info_for
    from sts2_env.az.content import ALL_CONTENT
    from sts2_env.az.rewards import V7
    from native_prior_features import encode_native
    model, metadata = load_transformer_checkpoint(args.checkpoint, 'XS', ALL_CONTENT, V7)
    sha = hashlib.sha256(open(args.checkpoint, 'rb').read()).hexdigest()
    print(json.dumps(dict(ready=True, model=metadata['model_version'], sha256=sha)), flush=True)
    for line in sys.stdin:
        try:
            started = time.perf_counter()
            d = json.loads(line)
            obs = encode_native(d)
            actions = obs.actions
            encoded = time.perf_counter()
            probabilities, _ = model.predict(obs)  # Value head intentionally unused.
            print(json.dumps(dict(priors=[probabilities[a.action_key] for a in actions],
                                  encodeMs=(encoded-started)*1000,
                                  inferMs=(time.perf_counter()-encoded)*1000)), flush=True)
        except Exception as exc:
            print(json.dumps(dict(error=f'{type(exc).__name__}: {exc}')), flush=True)


if __name__ == '__main__':
    main()
