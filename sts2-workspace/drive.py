"""Drive the sts2-cli headless engine, play a fight deeper, then run the clone probe."""
import json, os, subprocess, sys, time

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
            print("NO OUTPUT — process died. stderr:", flush=True)
            print(p.stderr.read()[:4000], flush=True)
            sys.exit(1)
        if line.lstrip().startswith("{"):
            return json.loads(line)

def send(cmd):
    p.stdin.write(json.dumps(cmd) + "\n"); p.stdin.flush()
    return read_json()

print("banner:", read_json())
print("start_run:", send({"cmd": "start_run", "character": "Ironclad", "seed": "cloneprobe"}).get("type"))

r = None
for enc in ("VANTOM_BOSS", "CEREMONIAL_BEAST_BOSS", "NIBBITS_NORMAL"):
    got = send({"cmd": "enter_room", "type": "combat", "encounter": enc})
    if got.get("type") != "error":
        print(f"enter_room({enc}) -> decision={got.get('decision')}", flush=True)
        r = got
        break
    print(f"  {enc} failed: {got.get('message')}", flush=True)
if r is None:
    sys.exit(1)

def play_once(r):
    d = r.get("decision") or r.get("type")
    hand = r.get("hand") or []
    if d == "combat_play" or hand:
        for c in hand:
            if isinstance(c, dict) and c.get("can_play"):
                tgt = 0 if c.get("target_type") == "AnyEnemy" else -1
                return send({"cmd": "action", "action": "play_card",
                             "args": {"card_index": c["index"], "target_index": tgt}})
        return send({"cmd": "action", "action": "end_turn"})
    if d == "card_select":
        return send({"cmd": "action", "action": "select_cards", "args": {"indices": "0"}})
    return None

prev_sig, stuck = None, 0
for i in range(6):
    nxt = play_once(r)
    if nxt is None:
        print(f"  stop at move {i}: decision={r.get('decision')} keys={list(r.keys())[:14]}", flush=True)
        break
    r = nxt
    sig = (r.get("decision"), r.get("round"), r.get("energy"), len(r.get("hand") or []))
    stuck = stuck + 1 if sig == prev_sig else 0
    prev_sig = sig
    if True:
        print(f"  move {i}: decision={r.get('decision')} round={r.get('round')} "
              f"energy={r.get('energy')} hand={len(r.get('hand') or [])} "
              f"draw={r.get('draw_pile_count')} discard={r.get('discard_pile_count')}", flush=True)
    if stuck > 4:
        print(f"  no progress after move {i}, stopping", flush=True)
        break

print(f"\nfinal decision={r.get('decision')} round={r.get('round')}", flush=True)
probe = send({"cmd": "clone_probe"})
print("\n===== CLONE PROBE (deep state) =====", flush=True)
print(json.dumps(probe, indent=2, ensure_ascii=False), flush=True)

try: send({"cmd": "quit"})
except Exception: pass
p.kill()
