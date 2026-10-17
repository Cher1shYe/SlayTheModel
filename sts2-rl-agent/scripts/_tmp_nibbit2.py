"""Temporary nibbit-graph debug (not a test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.cards.ironclad import create_ironclad_starter_deck  # noqa: F401
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng
from sts2_env.encounters.act1 import setup_nibbits_weak
from sts2_env.az.roster import capture_slots, intent_signal
from sts2_env.az.monster_registry import info_for
from sts2_env.az.information import PublicHistory

world = CombatState(80, 80, create_ironclad_starter_deck(), 5, relics=[], potions=[],
                    character_id='Ironclad')
setup_nibbits_weak(world, Rng(5))
world.start_combat()
world.rng = Rng(6)
info = info_for('NIBBIT')
print('successors', info.successors)
history = PublicHistory(roster_moves=((),))
for turn in range(4):
    ai = world.enemy_ais[world.enemies[0].combat_id]
    print('turn', turn, 'move', ai._current_state_id, 'intents', intent_signal(ai),
          'past', history.roster_moves)
    slots = capture_slots(world, history, (world.enemies[0].max_hp,))
    print('  captured', slots[0].move)
    world.end_player_turn()
    history = PublicHistory(roster_moves=((ai._current_state_id,),))
    # after the round the performed move is the one that was current before
