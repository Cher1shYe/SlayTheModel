"""Temporary exoskeleton debug (not a test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.cards.ironclad import create_ironclad_starter_deck  # noqa: F401
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.encounters.act2 import setup_exoskeletons_normal
from sts2_env.az.information import PublicHistory
from sts2_env.az.monster_registry import info_for, variants_for
from sts2_env.az.roster import after_round, capture_slots, intent_signal

world = CombatState(80, 80, create_ironclad_starter_deck(), 5, relics=[], potions=[],
                    character_id='Ironclad')
setup_exoskeletons_normal(world, Rng(5))
world.start_combat()
world.rng = Rng(6)
info = info_for('EXOSKELETON')
print('moves', info.moves)
print('initials', info.initial_moves)
print('successors', info.successors)
print('signatures', info.intent_signatures)
print('variants', [(v[1], v[3]) for v in variants_for('EXOSKELETON')])
history = PublicHistory(roster_moves=tuple(() for _ in world.enemies))
slots = capture_slots(world, history, tuple(e.max_hp for e in world.enemies))
print('captured', [(s.monster_id, s.move, s.moves) for s in slots])
for turn in range(4):
    if world.is_over:
        break
    before = slots
    world.end_player_turn()
    history = PublicHistory(roster_moves=after_round(before, world.is_over))
    try:
        slots = capture_slots(world, history, tuple(e.max_hp for e in world.enemies))
        print('turn', turn + 1, [(s.monster_id, s.move, s.moves) for s in slots])
    except Exception as exc:  # noqa: BLE001
        print('FAIL turn', turn + 1, type(exc).__name__, exc)
        for e in world.enemies:
            ai = world.enemy_ais[e.combat_id]
            print('  ', e.monster_id, 'real', ai._current_state_id, 'intents', intent_signal(ai))
        break
