#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${STS_ENV_FILE:-$ROOT/.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

export STS_LIVE_POLICY="${STS_LIVE_POLICY:-learned}"
export STS_SEED="${STS_SEED:-24242}"
export STS_SEED_TOKEN="${STS_SEED_TOKEN:-$STS_SEED}"
export STS_LIVE_LOG="${STS_LIVE_LOG:-$ROOT/runs/${STS_LIVE_POLICY}-seed-${STS_SEED}.jsonl}"

exec "${STS_PYTHON:-python3}" "$ROOT/steam/live_model_bridge.py" "$@"
