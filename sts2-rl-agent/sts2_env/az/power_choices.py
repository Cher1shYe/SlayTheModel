"""Public power-origin selections, independent of an active played card."""
from collections import Counter
from .choice_state import PublicChoiceOption,PublicChoiceState
from .foundation import amount


def capture(world,codec):
    choice=world.pending_choice
    options=tuple(PublicChoiceOption('revealed',i,codec.capture(o.card)) for i,o in enumerate(choice.options))
    pending=codec.capture(world._pending_play['card']) if world._pending_play else None
    return pending,PublicChoiceState('power:STRATAGEM',options,tuple(sorted(choice.selected_indices)),
        choice.min_choices,choice.max_choices,choice.allow_skip).validate(codec,4096)


def validate(info,codec):
    c=info.choice
    if amount(info,-1,'STRATAGEM')<=0 or not info.execution:raise ValueError('Missing Stratagem source/continuation')
    required=min(amount(info,-1,'STRATAGEM'),len(info.draw_composition))
    if (c.min_choices!=required or c.max_choices!=required or c.allow_skip or
        Counter(o.card.token for o in c.options)!=Counter(info.draw_composition) or
        any(o.pile!='revealed' or o.index!=i for i,o in enumerate(c.options))):raise ValueError('Invalid Stratagem selection')
    if info.pending_card:codec.validate(info.pending_card)
    if info.terminal_value() is None and c.legal_mask(codec,4096)!=info.legal_mask:raise ValueError('Invalid Stratagem mask')


def restore(world,info,codec):
    if info.pending_card:
        card=codec.restore(info.pending_card);card.owner=world.player;world.play_pile.append(card)
    pool=list(world.draw_pile);cards=[]
    for option in info.choice.options:
        card=next(c for c in pool if codec.capture(c)==option.card)
        pool.remove(card);cards.append(card)
    world.request_multi_card_choice(prompt='Choose cards from shuffled draw pile',cards=cards,source_pile='draw',
        resolver=lambda selected:[world.move_card_to_hand(c) for c in selected],
        min_count=info.choice.min_choices,max_count=info.choice.max_choices)
    world.pending_choice.mechanism='STRATAGEM'
    world.pending_choice.selected_indices=set(info.choice.selected)
