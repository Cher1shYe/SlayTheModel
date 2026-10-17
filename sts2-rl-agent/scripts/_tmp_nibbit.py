"""Temporary nibbit debug (not a test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.cards.ironclad import create_ironclad_starter_deck  # noqa: F401
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.encounters.act1 import setup_nibbits_weak
from sts2_env.az.roster import intent_signal
from sts2_env.az.monster_registry import info_for

world = CombatState(80, 80, create_ironclad_starter_deck(), 5, relics=[], potions=[],
                    character_id='Ironclad')
setup_nibbits_weak(world, Rng(5))
world.start_combat()
enemy = world.enemies[0]
ai = world.enemy_ais[enemy.combat_id]
print('id', enemy.monster_id, 'move', ai._current_state_id, 'intents', intent_signal(ai))
info = info_for('NIBBIT')
print('sigs', info.intent_signatures)
print('initials', info.initial_moves)
print('graph moves', info.moves)
