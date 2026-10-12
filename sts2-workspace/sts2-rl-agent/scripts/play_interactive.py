#!/usr/bin/env python3
"""Interactive command-line interface for playing STS2 combat in the headless simulator."""

from __future__ import annotations

import sys

from sts2_env.cards.base import CardInstance, reset_instance_counter
from sts2_env.cards.ironclad import create_ironclad_starter_deck
from sts2_env.core.combat import CombatState
from sts2_env.core.enums import TargetType
from sts2_env.core.rng import INT_MAX, Rng
from sts2_env.encounters.act1 import ALL_ACT1_ENCOUNTERS


def display_state(combat: CombatState) -> None:
    """Print current combat state in a human-readable format."""
    p = combat.primary_player
    print()
    print("=" * 60)
    print(f"  Round {combat.round_number}  |  Energy: {combat.energy}  |  "
          f"HP: {p.current_hp}/{p.max_hp}  |  Block: {p.block}")
    print("=" * 60)

    # Enemies
    print("\n  ENEMIES:")
    for i, e in enumerate(combat.alive_enemies):
        intent = ""
        ai = combat.enemy_ais.get(id(e))
        if ai and ai.state_log:
            intent = f"  [State: {ai.state_log[-1]}]"
        powers_str = ""
        if e.powers:
            powers_str = "  Powers: " + ", ".join(str(pw) for pw in e.powers.values())
        print(f"    [{i}] {e.monster_id}  HP={e.current_hp}/{e.max_hp}  Block={e.block}{powers_str}{intent}")

    # Player powers
    if p.powers:
        print(f"\n  YOUR POWERS: {', '.join(str(pw) for pw in p.powers.values())}")

    # Potions
    potions = combat.potions
    if potions and any(pot is not None for pot in potions):
        print("\n  POTIONS:")
        for i, pot in enumerate(potions):
            if pot is not None:
                print(f"    [p{i}] {pot}")

    # Hand
    print(f"\n  HAND ({len(combat.hand)} cards):")
    for i, card in enumerate(combat.hand):
        playable = "  *" if _card_playable(combat, card) else "   "
        target_hint = ""
        if card.target_type == TargetType.ANY_ENEMY:
            target_hint = " -> pick enemy"
        print(f"  {playable} [{i}] {card!r}{target_hint}")

    # Piles
    print(f"\n  Draw: {len(combat.draw_pile)}  |  Discard: {len(combat.discard_pile)}  |  Exhaust: {len(combat.exhaust_pile)}")
    print()


def _card_playable(combat: CombatState, card: CardInstance) -> bool:
    """Check if a card can be played."""
    if card.has_energy_cost_x:
        return True
    return card.cost <= combat.energy


def display_pending_choice(combat: CombatState) -> None:
    """Display a pending card/selection choice."""
    choice = combat.pending_choice
    if choice is None:
        return
    print()
    print(f"  >>> {choice.prompt} <<<")
    if choice.is_multi:
        print(f"  (Select {choice.min_choices}-{choice.max_choices} options, "
              f"selected so far: {sorted(choice.selected_indices)})")
    for i, opt in enumerate(choice.options):
        selected = " [X]" if i in choice.selected_indices else "    "
        print(f"  {selected} [{i}] {opt.card!r}")
    if choice.allow_skip or choice.can_confirm():
        print(f"        [e] Confirm / Skip")
    print()


def get_action(combat: CombatState) -> None:
    """Get and execute one player action."""
    # Handle pending choice
    if combat.pending_choice is not None:
        display_pending_choice(combat)
        while True:
            raw = input("  Choice> ").strip().lower()
            if raw in ("q", "quit", "exit"):
                sys.exit(0)
            if raw in ("e", "end", "skip", "confirm"):
                combat.resolve_pending_choice(None)
                return
            try:
                idx = int(raw)
                if 0 <= idx < combat.pending_choice.num_options:
                    combat.resolve_pending_choice(idx)
                    return
                print(f"  Invalid index. Choose 0-{combat.pending_choice.num_options - 1}")
            except ValueError:
                print("  Enter a number, 'e' to confirm/skip, or 'q' to quit.")

    # Normal combat action
    print("  Actions:  [0-9] play card  |  [0-9] t [enemy#] targeted  |  p[0-9] use potion  |  e end turn  |  q quit")
    while True:
        raw = input("  Action> ").strip().lower()
        if raw in ("q", "quit", "exit"):
            sys.exit(0)
        if raw in ("e", "end"):
            combat.end_player_turn()
            return
        if raw in ("h", "help", "?"):
            print("  Examples:")
            print("    3        -> play hand card [3] (self/all target)")
            print("    2 t 0    -> play hand card [2] targeting enemy [0]")
            print("    p0       -> use potion slot 0 (self)")
            print("    p1 t 0   -> use potion slot 1 targeting enemy [0]")
            print("    e        -> end turn")
            print("    q        -> quit")
            continue

        # Potion: p0, p1 t 0, etc.
        if raw.startswith("p"):
            parts = raw[1:].split()
            try:
                slot = int(parts[0])
            except (ValueError, IndexError):
                print("  Invalid potion command. Example: p0 or p1 t 0")
                continue
            target_idx = None
            if len(parts) >= 3 and parts[1] == "t":
                try:
                    target_idx = int(parts[2])
                except ValueError:
                    print("  Invalid target index.")
                    continue
            success = combat.use_potion(slot, target_index=target_idx)
            if not success:
                print("  Failed to use potion.")
            return

        # Card play: "3" or "2 t 0"
        parts = raw.split()
        try:
            card_idx = int(parts[0])
        except ValueError:
            print("  Invalid input. Type 'h' for help.")
            continue

        if card_idx < 0 or card_idx >= len(combat.hand):
            print(f"  Invalid card index. Hand has {len(combat.hand)} cards (0-{len(combat.hand)-1}).")
            continue

        card = combat.hand[card_idx]
        target_idx = None

        if card.target_type == TargetType.ANY_ENEMY:
            if len(parts) >= 3 and parts[1] == "t":
                try:
                    target_idx = int(parts[2])
                except ValueError:
                    print("  Invalid target index.")
                    continue
            else:
                enemies = combat.alive_enemies
                if len(enemies) == 1:
                    target_idx = 0
                else:
                    print(f"  Card needs a target. Use: {card_idx} t <enemy#>")
                    continue

        success = combat.play_card(card_idx, target_idx)
        if not success:
            print("  Failed to play card (not enough energy or invalid target).")
        return


def main():
    print("\n  === STS2 Interactive Combat ===\n")

    # List encounters
    print("  Available encounters:")
    for i, enc in enumerate(ALL_ACT1_ENCOUNTERS):
        name = getattr(enc, "__name__", None) or getattr(enc, "name", f"encounter_{i}")
        print(f"    [{i}] {name}")

    # Pick encounter
    print()
    raw = input(f"  Pick encounter (0-{len(ALL_ACT1_ENCOUNTERS)-1}, default=random): ").strip()
    if raw in ("q", "quit", "exit"):
        sys.exit(0)

    import random
    if raw == "":
        enc_idx = random.randrange(len(ALL_ACT1_ENCOUNTERS))
    else:
        enc_idx = int(raw) % len(ALL_ACT1_ENCOUNTERS)

    encounter = ALL_ACT1_ENCOUNTERS[enc_idx]
    enc_name = getattr(encounter, "__name__", None) or getattr(encounter, "name", f"encounter_{enc_idx}")
    print(f"\n  Starting encounter: {enc_name}")

    # Create combat
    reset_instance_counter()
    seed = random.randint(0, INT_MAX)
    rng = Rng(seed)
    deck = create_ironclad_starter_deck()

    combat = CombatState(
        player_hp=80,
        player_max_hp=80,
        deck=deck,
        rng_seed=seed,
        character_id="Ironclad",
    )

    encounter(combat, rng)
    combat.start_combat()

    # Game loop
    while not combat.is_over:
        display_state(combat)
        get_action(combat)

    # Result
    display_state(combat)
    if combat.player_won:
        print("  >>> YOU WIN! <<<")
    else:
        print("  >>> YOU DIED! <<<")
    print()


if __name__ == "__main__":
    main()
