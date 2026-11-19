#!/usr/bin/env bash
# Start the staged native headless host (real game DLL, isolated user directory).
# Usage: ./run_host.sh [port] [user-dir-name] [test-scenario]
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
game="$root/artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/SlayTheSpire2.app"
port="${1:-18777}"
user="${2:-SlayTheModelParity}"
scenario="${3:-}"
[[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || { echo "Invalid local port" >&2; exit 2; }
[[ "$user" =~ ^SlayTheModelParity[A-Za-z0-9_.-]*$ ]] || { echo "Use an isolated SlayTheModelParity user directory" >&2; exit 2; }
stage="$here/stage"
sed -i '' "s/config\/custom_user_dir_name=\"[^\"]*\"/config\/custom_user_dir_name=\"$user\"/" "$stage/project/project.godot"
exec env -u SENTRY_GODOT_LIB_PATH STS2_GAME_PACK="$game/Contents/Resources/Slay the Spire 2.pck" \
    STS2_HEADLESS_PORT="$port" STS2_HEADLESS_SCENARIO="$scenario" \
    STS2_HEADLESS_USER_DIR="$HOME/Library/Application Support/$user" \
    "$stage/HeadlessHost.app/Contents/MacOS/HeadlessHost" --headless --path "$stage/project" \
    --log-file "$stage/godot-$port.log" --force-steam=off
