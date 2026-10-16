#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
game_app="${STS2_GAME_APP:-$HOME/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.app}"
port=18777
skip_build=0
server_only=0
client_args=()
test_scenario="${STS2_HEADLESS_SCENARIO:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --game-app) game_app="$2"; shift 2 ;;
        --port) port="$2"; shift 2 ;;
        --skip-build) skip_build=1; shift ;;
        --server-only) server_only=1; shift ;;
        --test-scenario) test_scenario="$2"; shift 2 ;;
        --) shift; client_args=("$@"); break ;;
        --help|-h) echo 'Usage: ./scripts/headless-macos.sh [--game-app PATH] [--port 18777] [--skip-build] [--server-only] [--test-scenario NAME] [-- CLIENT_OPTIONS]'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1024 && port <= 65535)) || { echo 'Invalid port.' >&2; exit 2; }
managed_dir="$game_app/Contents/Resources/data_sts2_macos_arm64"
game_pack="$game_app/Contents/Resources/Slay the Spire 2.pck"
[[ "$(uname -m)" == arm64 && -f "$managed_dir/sts2.dll" && -f "$game_pack" ]] || { echo 'The macOS ARM64 STS2 installation was not found.' >&2; exit 1; }
expected="$(awk -F'"' '/"sha256"/ { print tolower($4); exit }' "$repo_dir/contracts/sts2-v0.111.0.json")"
actual="$(shasum -a 256 "$managed_dir/sts2.dll" | awk '{print $1}')"
[[ "$expected" == "$actual" ]] || { echo 'This host requires the verified v0.111.0 game assembly.' >&2; exit 1; }
if [[ "$skip_build" == 0 ]]; then
    dotnet build "$repo_dir/tools/Sts2.HeadlessHost" -c ExportRelease "-p:Sts2ManagedDir=$managed_dir"
    python3 "$repo_dir/scripts/headless-stage.py" --platform macos --game "$game_app"
fi
stage="$repo_dir/artifacts/headless"
exe="$stage/HeadlessHost.app/Contents/MacOS/HeadlessHost"
[[ -x "$exe" ]] || { echo 'Build headless once before using --skip-build.' >&2; exit 1; }
env -u SENTRY_GODOT_LIB_PATH STS2_GAME_PACK="$game_pack" STS2_HEADLESS_PORT="$port" \
    STS2_HEADLESS_SCENARIO="$test_scenario" \
    STS2_HEADLESS_USER_DIR="$HOME/Library/Application Support/SlayTheModelHeadless" "$exe" --headless --path "$stage/project" \
    --log-file "$stage/godot.log" --force-steam=off >"$stage/stdout.log" 2>"$stage/stderr.log" &
host_pid=$!
trap 'kill "$host_pid" 2>/dev/null || true; wait "$host_pid" 2>/dev/null || true' EXIT INT TERM
deadline=$((SECONDS + 90))
while true; do
    if health="$(curl -fsS --max-time 1 "http://127.0.0.1:$port/api/health" 2>/dev/null)"; then
        if [[ "$health" != *"\"pid\":$host_pid}"* ]]; then
            echo "Port $port belongs to another process. Choose --port with an unused port." >&2
            exit 1
        fi
        break
    fi
    if ! kill -0 "$host_pid" 2>/dev/null || ((SECONDS >= deadline)); then
        tail -n 30 "$stage/stdout.log" >&2
        tail -n 40 "$stage/stderr.log" >&2
        echo "Headless startup failed; see $stage logs." >&2
        exit 1
    fi
    sleep 0.2
done
if [[ "$server_only" == 1 ]]; then
    echo "Headless host PID $host_pid; API http://127.0.0.1:$port. Logs: $stage"
    wait "$host_pid"
else
    if ((${#client_args[@]})); then
        python3 "$repo_dir/scripts/headless-play.py" --url "http://127.0.0.1:$port" --new "${client_args[@]}"
    else
        python3 "$repo_dir/scripts/headless-play.py" --url "http://127.0.0.1:$port" --new
    fi
fi
