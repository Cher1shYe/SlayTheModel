"""Temporary roster round-trip debug (not a test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.information import PublicHistory
from sts2_env.az.monster_registry import ENCOUNTERS
from sts2_env.az.roster import after_round, capture_slots, create_slots, restore_slots, validate_slots
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.rng import Rng

encounter = sys.argv[1] if len(sys.argv) > 1 else 'setup_nibbits_weak'
world = CombatState(80, 80, create_ironclad_starter_deck(), 5, relics=[], potions=[],
                    character_id='Ironclad')
ENCOUNTERS[encounter](world, Rng(5))
world.start_combat()
world.rng = Rng(6)
history = PublicHistory(roster_moves=tuple(() for _ in world.enemies))
slots = capture_slots(world, history, tuple(e.max_hp for e in world.enemies))
print('initial', [(s.monster_id, s.move, s.moves) for s in slots])
for turn in range(4):
    if world.is_over:
        print('over', world.player_won)
        break
    world.end_player_turn()
    history = PublicHistory(roster_moves=after_round(slots, world.is_over))
    print('turn', turn + 1, 'history', history.roster_moves, 'player_hp', world.player.current_hp,
          'enemies', [(e.monster_id, e.current_hp, world.enemy_ais[e.combat_id]._current_state_id)
                      for e in world.enemies])
    slots = capture_slots(world, history, tuple(e.max_hp for e in world.enemies))
    validate_slots(slots)
