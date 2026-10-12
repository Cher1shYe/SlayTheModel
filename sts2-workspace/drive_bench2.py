"""Measure the engine's per-step advance cost (single fight)."""
import json, os, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sts2-cli")
EXE = os.path.join(ROOT, "src", "Sts2Headless", "bin", "Debug", "net9.0", "Sts2Headless.exe")
env = dict(os.environ, STS2_LIB=os.path.join(ROOT, "lib"), DOTNET_CLI_TELEMETRY_OPTOUT="1")

p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1, env=env)

def read_json():
    while True:
        line = p.stdout.readline()
        if not line:
            print("NO OUTPUT. stderr tail:"); print(p.stderr.read()[-3000:]); sys.exit(1)
        if line.lstrip().startswith("{"):
            return json.loads(line)

def send(cmd):
    p.stdin.write(json.dumps(cmd) + "\n"); p.stdin.flush()
    return read_json()

read_json()
send({"cmd": "start_run", "character": "Ironclad", "seed": "stepbench"})
for enc in ("NIBBITS_NORMAL", "SHRINKER_BEETLE_WEAK"):
    if send({"cmd": "enter_room", "type": "combat", "encounter": enc}).get("type") != "error":
        print(f"encounter: {enc}"); break

r = send({"cmd": "step_bench", "n": 12})
print(f"played={r.get('played')} ended_turns={r.get('ended_turns')}")
print("play_card :", json.dumps(r.get("play_card_total", {})))
print("end_turn  :", json.dumps(r.get("end_turn_total", {})))
print("detect_dp :", json.dumps(r.get("detect_decision_point", {})))
print("enqueue   :", json.dumps(r.get("enqueue", {})))
print("wait_exec :", json.dumps(r.get("wait_for_executor", {})))
try: send({"cmd": "quit"})
except Exception: pass
p.kill()
