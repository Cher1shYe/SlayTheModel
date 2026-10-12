#!/usr/bin/env python3
"""Run the full-run web UI from the repository checkout."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.web.play_run import main


if __name__ == "__main__":
    raise SystemExit(main())
