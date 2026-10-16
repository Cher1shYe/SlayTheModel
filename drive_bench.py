"""Measure the engine's per-step advance cost."""
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
print("start_run:", send({"cmd": "start_run", "character": "Ironclad", "seed": "stepbench"}).get("type"))
for enc in ("NIBBITS_NORMAL", "SHRINKER_BEETLE_WEAK"):
    r = send({"cmd": "enter_room", "type": "combat", "encounter": enc})
    if r.get("type") != "error":
        print(f"enter_room({enc}) ok"); break

print("--- warmup call (JIT) ---")
w = send({"cmd": "step_bench", "n": 12})
print("warmup played=", w.get("played"), "played_turns=", w.get("ended_turns"))

# restart a fresh fight so we measure a clean warm run
for enc in ("NIBBITS_NORMAL", "SHRINKER_BEETLE_WEAK"):
    if send({"cmd": "enter_room", "type": "combat", "encounter": enc}).get("type") != "error":
        break

r = send({"cmd": "step_bench", "n": 25})
print("===== WARM STEP BENCH =====")
print(json.dumps(r, indent=2, ensure_ascii=False))

try: send({"cmd": "quit"})
except Exception: pass
p.kill()
