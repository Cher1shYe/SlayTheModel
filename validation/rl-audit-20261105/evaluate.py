"""Independent evaluation on the held-out test seeds (30,000,000+).

    python validation/rl-audit-20261105/evaluate.py --checkpoint <ppo.pt> \
        --seeds 32 --out D:/sts2_rl_runs/eval_ref/eval.json

Thin wrapper so the exact command and its content profile / search budget are
recorded with the results.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from deployment.evaluate_armg import main  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "deployment.evaluate_armg"
    main(sys.argv[1:])
