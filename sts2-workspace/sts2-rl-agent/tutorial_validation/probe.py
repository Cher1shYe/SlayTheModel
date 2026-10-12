"""Read-only simulator probes derived from tutorials and local C# inspection.

Run from repository root: .venv/Scripts/python.exe -B tutorial_validation/probe.py
Writes only tutorial_validation/results.json. Mismatches are findings, not crashes.
The expected values are manually derived from C#; this does not execute C#.
"""
from pathlib import Path
import hashlib
import json
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def hashes():
    paths = [ROOT / "spec.md", ROOT / "pyproject.toml", ROOT / "uv.lock"]
    for folder in ("sts2_env", "tests", "scripts", "configs", "decompiled"):
        paths.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


before = hashes()
from sts2_env.gym_env.combat_env import STS2CombatEnv  # established import order
import sts2_env.powers
from sts2_env.cards.ironclad_basic import make_strike_ironclad, create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import PowerId, ValueProp
from sts2_env.core.hooks import modify_damage, fire_after_damage_given
from sts2_env.core.damage import apply_damage
from sts2_env.core.rng import Rng
from sts2_env.monsters.act1_weak import create_shrinker_beetle
from sts2_env.powers.base import PowerInstance


def scene():
    c = CombatState(player_hp=80, player_max_hp=80,
                    deck=create_ironclad_starter_deck(), rng_seed=42)
    enemy, ai = create_shrinker_beetle(Rng(42))
    c.add_enemy(enemy, ai)
    c.start_combat()
    c.player.powers.clear()
    enemy.powers.clear()
    enemy.max_hp = enemy.current_hp = 50
    return c, enemy


rows = []


def record(name, expected, observed, basis):
    rows.append(dict(name=name, expected=expected, observed=observed,
                     matches=expected == observed, basis=basis))


for enchant, strength, expected in [(None, 3, 9), ("Favored", 0, 12),
                                    ("Favored", 3, 15), ("Corrupted", 3, 12)]:
    c, enemy = scene()
    card = make_strike_ironclad()
    if enchant:
        card.enchantments[enchant] = 1
    if strength:
        c.player.apply_power(PowerId.STRENGTH, strength)
    observed = modify_damage(6, c.player, enemy, ValueProp.MOVE, c, card)
    record(f"damage_{enchant}_strength_{strength}", expected, observed,
           "Hook.cs ModifyDamage: enchant multiplier before ModifyDamageInternal additive pass")

# Instrument the real dispatcher without replacing functions or editing game models.
events = []
def listener(label):
    return SimpleNamespace(enabled=True, after_damage_given=lambda *args: events.append(label))
c, enemy = scene()
c.player.powers[PowerId.STRENGTH] = listener("player_power")
enemy.powers[PowerId.STRENGTH] = listener("enemy_power")
c.relics.append(listener("player_relic"))
fire_after_damage_given(c.player, enemy, 1, ValueProp.MOVE, c)
record("listener_order", ["player_power", "player_relic", "enemy_power"], events,
       "CombatState.cs IterateHookListeners: each creature's powers then its player relics")


class DamageRecorder(PowerInstance):
    def __init__(self, log):
        super().__init__(PowerId.VIGOR, 1)
        self.log = log

    def on_block_broken(self, owner, combat):
        self.log.append("block")

    def after_current_hp_changed(self, owner, creature, delta, combat):
        if creature is owner:
            self.log.append("hp")

    def after_damage_given(self, owner, dealer, target, damage, props, combat):
        if target is owner:
            self.log.append("given")

    def after_damage_received(self, owner, target, dealer, damage, props, combat):
        if target is owner:
            self.log.append("received")


for lethal in (False, True):
    c, enemy = scene()
    log = []
    enemy.powers[PowerId.VIGOR] = DamageRecorder(log)
    enemy.block = 2
    apply_damage(enemy, 100 if lethal else 5, ValueProp.MOVE, c, c.player)
    record(f"damage_hook_order_lethal_{lethal}",
           ["block", "hp", "given"] + ([] if lethal else ["received"]), log,
           "CreatureCmd.cs Damage: block, HP, given, received only for surviving target")

source_paths = {
    "hook": "decompiled/MegaCrit.Sts2.Core.Hooks/Hook.cs",
    "combat": "decompiled/MegaCrit.Sts2.Core.Combat/CombatState.cs",
    "ngame": "decompiled/MegaCrit.Sts2.Core.Nodes/NGame.cs",
}
sources = {k: (ROOT / p).read_text(encoding="utf-8-sig") for k, p in source_paths.items()}
after = hashes()
changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
report = {
    "scope": "Python runtime probes plus manually inspected local C#; no live game or C# execution",
    "probes": rows,
    "matched": sum(r["matches"] for r in rows),
    "mismatched": sum(not r["matches"] for r in rows),
    "static_checks": {
        "autoslay_release_guard": '!IsReleaseGame() && CommandLineHelper.HasArg("autoslay")' in sources["ngame"],
        "tutorial_new_guard_name_present_locally": "IterateCombatHookListeners" in sources["hook"],
        "tutorial_badge_listener_name_present_locally": "BadgeModels" in sources["combat"],
    },
    "source_sha256": {p: before[p] for p in source_paths.values()},
    "existing_files_checked": len(before), "changed_existing_files": changed,
}
(Path(__file__).parent / "results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if changed:
    raise SystemExit("Existing files changed during probe; inspect results.")
