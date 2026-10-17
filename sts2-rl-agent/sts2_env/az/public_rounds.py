"""Actual visible action/death events; no private AI cursor or future state."""
from dataclasses import replace
from collections import Counter
from .card_generation import CardGeneration
from .boss_phases import public_cursor,FORM_HP,KNOCKOUT,DEFEAT


def finish(before,world,history):
    events=world.visible_card_events[len(before.history.public_events):]
    moves=[list(e.moves) for e in before.enemies]
    phase=list(before.history.boss_events)
    for event in events:
        if event[0]=='enemy_action':
            slot=event[1]
            if not 0<=slot<len(before.enemies):raise ValueError('Unobserved enemy acted')
            if before.monster_id=='TEST_SUBJECT':
                move=public_cursor(tuple(phase))[2]
                phase.append(move)
            else:
                from .summon import public_move
                old=before.enemies[slot]
                move=public_move(replace(old,moves=tuple(moves[slot])),len(before.enemies))
            moves[slot].append(move)
        elif event[0]=='enemy_knockout' and before.monster_id=='TEST_SUBJECT':
            if event[1]!=0 or event[2] not in FORM_HP:raise ValueError('Invalid public Boss knockout')
            phase.append(DEFEAT if event[2]==FORM_HP[-1] else KNOCKOUT)
    # Native generated status cards are visible. Count their actual appearance,
    # including modified block and turn-end automatic attacks before the enemy.
    generated=tuple(e for e in history.generated if e.mechanism not in
        ('distract-dazed-v1','boss-burn-v1','boss-wound-v1'))
    generated+=tuple(e for e in before.history.generated if e.mechanism in
        ('distract-dazed-v1','boss-burn-v1','boss-wound-v1'))
    count=Counter(e[1] for e in events if e[0]=='generated' and e[1] in ('DAZED','BURN','WOUND'))
    from .summon import DAZED_SOURCE
    for token,(source,mechanism) in {'DAZED':(DAZED_SOURCE,'distract-dazed-v1'),
        'BURN':('TEST_SUBJECT.BURNING_GROWL','boss-burn-v1'),
        'WOUND':('TEST_SUBJECT.PAINFUL_STABS','boss-wound-v1')}.items():
        if count[token]:generated+=(CardGeneration(history.decisions,source,token,'discard',mechanism,count[token]),)
    generated=tuple(sorted(generated,key=lambda e:e.decision))
    roster=tuple(tuple(m) for m in moves)
    return replace(history,enemy_moves=roster[0],roster_moves=roster,boss_events=tuple(phase),generated=generated)
