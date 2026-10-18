"""Audited public choices and draw-pile operations (no native closures stored)."""
from collections import Counter
from dataclasses import replace
from sts2_env.cards import ironclad,colorless
from .mechanic_registry import Operation as O,MechanicDescriptor
NAMES=('BRAND','THINKING_AHEAD','SECRET_TECHNIQUE','SECRET_WEAPON','SEEKER_STRIKE','CINDER','ANOINTED','DISCOVERY')
FACTORIES={n:getattr(ironclad if n in ('BRAND','CINDER') else colorless,'make_'+n.lower()) for n in NAMES}
CHOICES=NAMES[:5]+('DISCOVERY',)
REVEAL=('SECRET_TECHNIQUE','SECRET_WEAPON','SEEKER_STRIKE')

def descriptor(c):
    n,v=c.card_id.name,c.effect_vars;ops=[]
    target='enemy' if c.is_attack else 'self'
    if c.base_damage:ops.append(O('damage',target,'on_play',c.base_damage))
    if n=='BRAND':ops += [O('hp_loss','self','on_play',v['hp_loss']),O('choose_exhaust','hand','on_play',1),O('strength','self','after_choice',v['strength'])]
    elif n=='THINKING_AHEAD':ops += [O('draw','self','on_play',v['cards']),O('choose_topdeck','hand','after_choice',1)]
    elif n in ('SECRET_TECHNIQUE','SECRET_WEAPON'):ops += [O('choose_draw_type','draw','on_play',2 if n=='SECRET_TECHNIQUE' else 1)]
    elif n=='SEEKER_STRIKE':ops += [O('reveal_random_draw','draw','after_play_damage',v['cards']),O('choose_to_hand','draw','after_choice',1)]
    elif n=='CINDER':ops += [O('exhaust_draw_top','draw','after_play_damage',v['cards_to_exhaust'])]
    elif n=='ANOINTED':ops += [O('retrieve_rarity','draw','on_play',4)]
    elif n=='DISCOVERY':ops += [O('choose_generated_character','generated','on_play',3),O('cost','generated','after_choice',0)]
    ops += [O(k,'self','after_play',1) for k in sorted(c.keywords)]
    return MechanicDescriptor(c.card_type.value,c.cost,target,tuple(o.validate() for o in ops))

def observe_choice(world,codec):
    from .choice_state import PublicChoiceOption,PublicChoiceState,capture_choice
    card=codec.capture(world._pending_play['card']);n=card.token.removesuffix('+');ch=world.pending_choice
    if n in (*REVEAL,'DISCOVERY'):
        options=tuple(PublicChoiceOption('revealed',i,codec.capture(o.card)) for i,o in enumerate(ch.options))
        choice=PublicChoiceState(card.token,options,tuple(sorted(ch.selected_indices)),ch.min_choices,ch.max_choices,ch.allow_skip)
    else:choice=capture_choice(ch,{'hand':world.hand},codec,mechanism=card.token,action_size=4096)
    return card,choice.validate(codec,4096)

def validate(info):
    n=info.pending_card.token.removesuffix('+');choice=info.choice
    from .g1 import codec_for
    from .selection_batch import validate_choice_shape
    codec=codec_for(info.content_version)
    codec.validate(info.pending_card);choice.validate(codec,4096);validate_choice_shape(info.pending_card,choice)
    if choice.mechanism!=info.pending_card.token:raise ValueError('Choice mechanism mismatch')
    if n=='DISCOVERY':
        from sts2_env.cards.factory import eligible_character_cards
        pool={c.name for c in eligible_character_cards('ironclad',generation_context='combat',is_multiplayer=False)}
        tokens=[o.card.token for o in choice.options]
        if len(tokens)!=3 or len(set(tokens))!=3 or any(t not in pool for t in tokens):raise ValueError('Invalid native Discovery candidates')
        if any(o.pile!='revealed' or o.index!=i or o.card!=codec.capture(codec._reference(o.card.token)) for i,o in enumerate(choice.options)):raise ValueError('Invalid Discovery faces')
    elif n in REVEAL:
        if any(o.pile!='revealed' or o.index!=i for i,o in enumerate(choice.options)):raise ValueError('Invalid reveal refs')
        if Counter(o.card.token for o in choice.options)-Counter(info.draw_composition):raise ValueError('Reveal outside draw composition')
        from .deck_observation import prototype
        required=2 if n=='SECRET_TECHNIQUE' else 1
        if n!='SEEKER_STRIKE' and Counter(o.card.token for o in choice.options)!=Counter(t for t in info.draw_composition if prototype(t).card_type.value==required):raise ValueError('Filtered reveal mismatch')
        if n=='SEEKER_STRIKE' and len(choice.options)!=min(dict(info.pending_card.effect_vars)['cards'],len(info.draw_composition)):raise ValueError('Seeker reveal size')
    else:
        if tuple((o.pile,o.index,o.card) for o in choice.options)!=tuple(('hand',i,c) for i,c in enumerate(info.hand_states)):raise ValueError('Hand selection mismatch')
    if info.terminal_value() is None and choice.legal_mask(codec,4096)!=info.legal_mask:raise ValueError('Choice legal mask mismatch')

def restore(world,info):
    from .g1 import codec_for
    codec=codec_for(info.content_version);card=codec.restore(info.pending_card);card.owner=world.player
    world.play_pile.append(card);n=card.card_id.name
    if n=='DISCOVERY':cards=[codec.restore(o.card) for o in info.choice.options]
    elif n in REVEAL:
        pool=list(world.draw_pile);cards=[]
        for o in info.choice.options:
            c=next(c for c in pool if codec.capture(c)==o.card);pool.remove(c);cards.append(c)
    else:cards=info.choice.bind_options({'hand':world.hand},codec,4096)
    def resolve(selected):
        if n=='DISCOVERY':
            if selected is not None:
                selected.set_temporary_cost_for_turn(0)
                world.add_generated_card_to_creature_hand(world.player,selected)
            return
        if n=='BRAND':
            world.run_card_steps(card,([('exhaust_card',selected)] if selected is not None else [])+[('power_target',-1,'STRENGTH',card.effect_vars['strength'])])
            return
        if selected is not None:
            if n=='BRAND':world.exhaust_card(selected)
            elif n=='THINKING_AHEAD':world.insert_card_into_draw_pile(selected,random_position=False)
            else:world.move_card_to_hand(selected)
    world.request_card_choice(prompt='Resolve public selection',cards=cards,source_pile='generated' if n=='DISCOVERY' else 'draw' if n in REVEAL else 'hand',resolver=resolve,allow_skip=n=='DISCOVERY')
    paid=info.history.payments[-1].energy;card.energy_spent=paid
    world._pending_play=dict(card=card,target=world.enemies[info.history.pending_target] if n=='SEEKER_STRIKE' else None,
        owner=world.player,remaining_plays=0,play_count=1,energy_spent=paid,energy_value=paid,force_exhaust=False,is_auto_play=False,awaiting_after_hook=True)

def finish_history(before,world,history,action):
    from .decks import card_token
    n=before.pending_card.token.removesuffix('+') if before.pending_card else None
    top,bottom=history.known_top,history.known_bottom
    if n in REVEAL and action:
        token=before.choice.options[action-1].card.token
        # A same-token selection may refer to any duplicate. Keep only positions
        # whose identity is certain after removal (never invent a hidden index).
        top=top[:top.index(token)] if token in top else top
        bottom=bottom[bottom.index(token)+1:] if token in bottom else bottom
    elif not before.choice and action:
        from .actions import decode_card_action
        slot,_=decode_card_action(action, before.content_version);n=before.hand[slot].removesuffix('+')
        if n=='CINDER':
            added=Counter(card_token(c) for c in world.exhaust_pile)-Counter(before.exhaust)
            count=sum(added.values())
            if count>=len(before.draw_composition):top,bottom=(),()
            else:top=top[count:]
        elif n=='ANOINTED' or n in REVEAL:
            from .deck_observation import prototype
            # All rare cards move in draw order up to the hand limit. The native
            # move operation sends overflow to discard.
            added=Counter(card_token(c) for c in world.hand)-Counter(t for i,t in enumerate(before.hand) if i!=slot)
            def prune(seq):
                seq=list(seq)
                for t in added:
                    if t in seq:seq=seq[:seq.index(t)]
                return tuple(seq)
            top=prune(top);bottom=tuple(reversed(prune(tuple(reversed(bottom)))))
    return replace(history,known_top=top,known_bottom=bottom)
