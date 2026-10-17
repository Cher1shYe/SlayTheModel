"""Explicit public basic status contract; no RNG or hidden card order."""
from dataclasses import replace
from copy import copy
from sts2_env.cards import ironclad, colorless
from sts2_env.core.enums import PowerId
from .mechanic_registry import Operation as O, MechanicDescriptor

FACTORIES={}
for module,names in ((ironclad,'uppercut setup_strike mangle fight_me cruelty colossus pyre aggression drum_of_battle hellraiser stampede spite tear_asunder rampage thrash flame_barrier grapple unrelenting juggernaut crimson_mantle inferno juggling one_two_punch rupture unmovable vicious dark_embrace infernal_blade'),
                     (colorless,'shockwave dark_shackles prowess panic_button prep_time stratagem mayhem_card jackpot calamity_card')):
    for name in names.split():
        factory=getattr(module,'make_'+name)
        # Factory metadata is cached below without consuming simulation identities.
        from sts2_env.cards import base
        saved=base._next_instance_id
        try: FACTORIES[factory().card_id.name]=factory
        finally: base._next_instance_id=saved
PLAYER=('SETUP_STRIKE','DEXTERITY','CRUELTY','COLOSSUS','NO_BLOCK','PREP_TIME','VIGOR','PYRE','AGGRESSION','DRUM_OF_BATTLE','STRATAGEM','HELLRAISER','MAYHEM','STAMPEDE','FLAME_BARRIER','FREE_ATTACK','JUGGERNAUT','CRIMSON_MANTLE','INFERNO','JUGGLING','ONE_TWO_PUNCH','RUPTURE')
PLAYER+=('UNMOVABLE','VICIOUS','DARK_EMBRACE','CALAMITY')
ENEMY=('WEAK','MANGLE','DARK_SHACKLES','GRAPPLE','KNOCKDOWN','TAG_TEAM')

def descriptor(card):
    n,v=card.card_id.name,card.effect_vars
    target={'SELF':'self','ANY_ENEMY':'enemy','ALL_ENEMIES':'all_enemies'}[card.target_type.name]
    effects=[]
    if card.base_damage and n!='TEAR_ASUNDER': effects.append(O('damage',target,'on_play',card.base_damage,hits=2 if n=='THRASH' else v.get('repeat',1)))
    if card.base_block: effects.append(O('block','self','on_play',card.base_block))
    if n in ('UPPERCUT','SHOCKWAVE'):
        effects += [O('weak',target,'on_play',v['power']),O('vulnerable',target,'on_play',v['power'])]
    elif n=='SETUP_STRIKE_CARD': effects += [O('temporary_strength','self','on_play',v['strength'])]
    elif n in ('MANGLE','DARK_SHACKLES'): effects += [O('temporary_strength','enemy','on_play',-v['strength_loss'])]
    elif n=='FIGHT_ME': effects += [O('strength','self','on_play',v['strength']),O('strength','enemy','on_play',v['enemy_strength'],condition='target_alive')]
    elif n=='PROWESS': effects += [O('strength','self','on_play',v['strength']),O('dexterity','self','on_play',v['dexterity'])]
    elif n=='CRUELTY_CARD': effects += [O('vulnerable_multiplier_bonus','self','outgoing_powered_attack',v['cruelty_power']/100)]
    elif n=='COLOSSUS_CARD': effects += [O('vulnerable_attacker_mitigation','self','incoming_powered_attack',.5),O('duration','self','enemy_turn_end',v['colossus'])]
    elif n=='PANIC_BUTTON': effects += [O('no_block','self','powered_card_block',v['turns'])]
    elif n=='PREP_TIME': effects += [O('vigor','self','turn_start',v['prep_time'])]
    elif n=='AGGRESSION_CARD': effects += [O('retrieve_upgrade_attacks','discard','before_side_turn_start',1)]
    elif n=='DRUM_OF_BATTLE_CARD': effects += [O('draw','self','on_play',v['cards']),O('exhaust_draw_top','draw','before_hand_draw_late',v['drum_of_battle_power'])]
    elif n=='STRATAGEM': effects += [O('choose_to_hand','draw','after_shuffle',v.get('stratagem',1))]
    elif n=='HELLRAISER_CARD': effects += [O('auto_play_drawn_strikes','self','on_draw',1)]
    elif n=='MAYHEM_CARD': effects += [O('auto_play_draw','draw','before_hand_draw_late',1)]
    elif n=='STAMPEDE_CARD': effects += [O('auto_play_hand_attack','hand','player_turn_end',v['power'])]
    elif n=='SPITE': effects += [O('draw','self','after_play_damage',v['cards'],condition='player_damaged_this_turn')]
    elif n=='TEAR_ASUNDER': effects += [O('damage_per_received_hit','enemy','on_play',card.base_damage,hits=1,coefficient=1)]
    elif n=='JACKPOT': effects += [O('generate_character_zero_cost','hand','after_play_damage',v['cards']),O('upgrade_generated','generated','after_play_damage',int(card.upgraded))]
    elif n=='RAMPAGE': effects += [O('grow_self_damage','self','after_play_damage',v['increase'])]
    elif n=='THRASH': effects += [O('random_exhaust_attack','hand','after_play_damage',1),O('grow_from_exhausted_damage','self','after_exhaust',1)]
    elif n=='FLAME_BARRIER_CARD': effects += [O('retaliate_attack','enemy','incoming_powered_attack',v['damage_back'])]
    elif n=='GRAPPLE': effects += [O('damage_on_applier_block','enemy','after_block',v['grapple_power'])]
    elif n=='UNRELENTING': effects += [O('free_attack','self','before_attack_play',1)]
    elif n=='JUGGERNAUT_CARD': effects += [O('damage_unpowered','random_enemy','after_block',v['juggernaut_power'])]
    elif n=='CRIMSON_MANTLE': effects += [O('block','self','turn_start',v['crimson_mantle_power']),O('hp_loss','self','turn_start',1)]
    elif n=='INFERNO_CARD': effects += [O('damage_unpowered','all_enemies','on_unblocked_hit',v['inferno_power']),O('hp_loss','self','turn_start',1)]
    elif n=='JUGGLING_CARD': effects += [O('copy_third_attack','hand','after_attack_play',1)]
    elif n=='ONE_TWO_PUNCH_CARD': effects += [O('replay_attack','self','before_attack_play',v['attacks'])]
    elif n=='RUPTURE_CARD': effects += [O('strength_on_hp_loss','self','on_unblocked_hit',v['strength'])]
    elif n=='UNMOVABLE': effects += [O('double_first_block','self','powered_card_block',1)]
    elif n=='VICIOUS_CARD': effects += [O('draw_on_vulnerable','self','on_play',v['cards'])]
    elif n=='DARK_EMBRACE_CARD': effects += [O('draw','self','on_exhaust',1)]
    elif n=='INFERNAL_BLADE': effects += [O('generate_character_attack','hand','on_play',1),O('cost','generated','generated_card',0)]
    elif n=='CALAMITY_CARD': effects += [O('generate_character_attack','hand','after_attack_play',1)]
    elif n=='PYRE': effects += [O('max_energy','self','turn_start',v['energy'])]
    else: raise ValueError(n)
    effects += [O(k,'self','after_play',1) for k in sorted(card.keywords)]
    return MechanicDescriptor(card.card_type.value,card.cost,target,tuple(e.validate() for e in effects))

def capture(world):
    return tuple((slot,n,c.powers[PowerId[n]].amount) for slot,c in enumerate([world.player,*world.enemies],-1)
                 for n in (p.name for p in c.powers) if n in (PLAYER if slot==-1 else ENEMY))

def amount(info,slot,name):
    return next((v for s,n,v in info.basic_statuses if s==slot and n==name),0)

def effects(info,slot):
    result=[]
    for s,n,a in info.basic_statuses:
        if s!=slot: continue
        ops={
          'WEAK':('weak','outgoing_powered_attack',a),
          'MANGLE':('temporary_strength','enemy_turn_end',-a),
          'DARK_SHACKLES':('temporary_strength','enemy_turn_end',-a),
          'SETUP_STRIKE':('temporary_strength','player_turn_end',a),
          'DEXTERITY':('dexterity','powered_card_block',a),
          'CRUELTY':('vulnerable_multiplier_bonus','outgoing_powered_attack',a/100),
          'COLOSSUS':('vulnerable_attacker_mitigation','incoming_powered_attack',.5),
          'NO_BLOCK':('no_block','powered_card_block',a),
          'PREP_TIME':('vigor','turn_start',a), 'VIGOR':('vigor','before_attack_play',a),
          'PYRE':('max_energy','turn_start',a),
          'AGGRESSION':('retrieve_upgrade_attacks','before_side_turn_start',a),
          'RUPTURE':('strength_on_hp_loss','on_unblocked_hit',a),
          'CALAMITY':('generate_character_attack','after_attack_play',a),
          'DARK_EMBRACE':('draw','on_exhaust',a),
          'VICIOUS':('draw_on_vulnerable','after_choice',a),
          'UNMOVABLE':('double_first_block','powered_card_block',a),
          'CRIMSON_MANTLE':('block_unpowered','turn_start',a),
          'INFERNO':('damage_all_on_hp_loss','on_unblocked_hit',a),
          'JUGGLING':('copy_third_attack','after_attack_play',a),
          'ONE_TWO_PUNCH':('replay_attack','before_attack_play',a),
          'FLAME_BARRIER':('retaliate_attack','incoming_powered_attack',a),
          'FREE_ATTACK':('free_attack','before_attack_play',a),
          'JUGGERNAUT':('damage_random_on_block','after_block',a),
          'GRAPPLE':('damage_on_applier_block','after_block',a),
          'MAYHEM':('auto_play_draw','before_hand_draw_late',a),
          'STAMPEDE':('auto_play_hand_attack','player_turn_end',a),
          'HELLRAISER':('auto_play_drawn_strikes','on_draw',a),
          'STRATAGEM':('choose_to_hand','after_shuffle',a),
          'DRUM_OF_BATTLE':('exhaust_draw_top','before_hand_draw_late',a),
          'KNOCKDOWN':('knockdown','incoming_powered_attack',a),
          'TAG_TEAM':('tag_team','incoming_powered_attack',a)}
        k,t,v=ops[n];result.append(O(k,'self',t,v))
        if n in ('COLOSSUS','NO_BLOCK','WEAK','KNOCKDOWN','TAG_TEAM'):result.append(O('duration','self','enemy_turn_end',a))
    return tuple(result)

def validate(info):
    from .content import EXPANSION_CONTENT
    if info.content_version!=EXPANSION_CONTENT:
        if info.basic_statuses or info.history.basic_plays:raise ValueError('Basic statuses outside version')
        return
    from .deck_observation import prototype
    if (type(info.history.basic_plays)is not tuple or any(type(row)is not tuple or len(row)!=2
        or row[0].removesuffix('+') not in (*FACTORIES,'BRAND') or type(row[1])is not int
        or not 1<=row[1]<=info.turn for row in info.history.basic_plays)):
        raise ValueError('Invalid basic play ledger')
    if len(info.history.basic_plays)>info.history.decisions and not info.history.public_events:raise ValueError('Basic plays exceed decisions')
    if any(type(e.strength)is not int or not -100000<=e.strength<=100000 for e in info.enemies):raise ValueError('Invalid signed strength')
    seen=set()
    if type(info.basic_statuses)is not tuple:raise ValueError('Immutable status rows required')
    for row in info.basic_statuses:
        if (type(row)is not tuple or len(row)!=3):raise ValueError('Invalid status row')
        slot,n,a=row
        if (type(slot)is not int or not -1<=slot<len(info.enemies) or n not in (PLAYER if slot==-1 else ENEMY)
            or type(a)is not int or not (0<=a<=100000 if n in ('ONE_TWO_PUNCH','FREE_ATTACK') else -100000<=a<=100000 if n in ('DEXTERITY','SETUP_STRIKE') else 0<a<=100000) or (slot,n) in seen):raise ValueError('Invalid basic status')
        seen.add((slot,n))
    if info.max_energy!=3+amount(info,-1,'PYRE'):raise ValueError('Max energy disagrees with Pyre')

def capture_enemies(world,history,initial_hp,old_capture):
    # Read-only view for legacy phase/roster validation; new public statuses are
    # represented explicitly alongside the unchanged monster programs.
    proxy=copy(world); proxy.enemies=[]
    for e in world.enemies:
        c=copy(e);c.powers={p:v for p,v in e.powers.items() if p.name not in ENEMY}
        if PowerId.STRENGTH in c.powers and c.powers[PowerId.STRENGTH].amount<=0:
            c.powers.pop(PowerId.STRENGTH)
        proxy.enemies.append(c)
    slots,boss=old_capture(proxy,history,initial_hp)
    slots=tuple(replace(s,strength=e.powers[PowerId.STRENGTH].amount if PowerId.STRENGTH in e.powers else 0)
                for s,e in zip(slots,world.enemies))
    return slots,boss

def validate_enemies(info,old_validate):
    if info.boss:
        powers=dict(info.boss.powers)
        slots=(replace(info.enemies[0],strength=powers.get('STRENGTH',0)),)
    else:
        from .summon import expected_roster_strength
        slots=tuple(replace(e,strength=expected_roster_strength(e) if e.hp>0 else 0) for e in info.enemies)
    # Validate roster, phase, HP, intent and lifecycle independently of card-sourced strength.
    return old_validate(replace(info,enemies=slots,enemy_strength=slots[0].strength))

def restore(world,info):
    from sts2_env.core.creature import get_power_class
    create_power=lambda pid,a:get_power_class(pid)(a)
    for slot,n,a in info.basic_statuses:
        c=world.player if slot==-1 else world.enemies[slot]
        p=create_power(PowerId[n],a);p.applier=world.player
        if n=='GRAPPLE':p._instances=[(a,world.player)]
        # Knockdown only spares damage dealt by its applier; the player applied
        # it, so the reconstructed instance carries that public applier.
        if n=='KNOCKDOWN':p._instances=[(a,world.player)]
        # These cards apply during the player turn; the first enemy-end tick is due.
        p.skip_next_tick=False
        c.powers[PowerId[n]]=p
    from .content import ALL_CONTENT
    for c,e in zip(world.enemies,info.enemies):
        if info.content_version == ALL_CONTENT:
            # All-content slot powers are the exact visible list; a zero-amount
            # Strength power is still present in the engine until it is cleaned.
            powers = dict(e.powers)
            c.powers.pop(PowerId.STRENGTH, None)
            if 'STRENGTH' in powers:
                c.powers[PowerId.STRENGTH] = create_power(PowerId.STRENGTH, powers['STRENGTH'])
        else:
            c.powers.pop(PowerId.STRENGTH,None)
            if e.strength:c.powers[PowerId.STRENGTH]=create_power(PowerId.STRENGTH,e.strength)


def strength(info):
    from .deck_observation import prototype
    return (sum(prototype(t).effect_vars['strength'] for t,turn in info.history.basic_plays
               if t.removesuffix('+') in ('FIGHT_ME','PROWESS')) + amount(info,-1,'SETUP_STRIKE')
        + sum(e[1] for e in info.history.public_events if e[0] in ('rupture_strength','brand_strength')))

