import gzip
import json
import copy
import pytest
from sts2_env.az.native_generic import encode,validate_raw


def test_restrict_protocol_excludes_upgrades_and_preserves_unaffected_recipes():
    from sts2_env.az.native_generic_backend import frozen_protocol,restrict_protocol_cards
    p=frozen_protocol(['BASH','BASH+','SPLASH','SPLASH+'],['CEREMONIAL_BEAST_BOSS'],32)
    q=restrict_protocol_cards(p,{'SPLASH'})
    assert q['cards']==['BASH','BASH+'] and q['manifest_sha256']!=p['manifest_sha256']
    assert len({r['scenario_id'] for r in q['validation']})==32
    for old,new in zip(p['validation'],q['validation']):
        assert new['seed']==old['seed'] and new['encounter']==old['encounter']
        assert set(new['deck'])<=set(q['cards'])
        if set(old['deck'])<=set(q['cards']): assert new==old
    assert restrict_protocol_cards(q,{'SPLASH'})==q
    with pytest.raises(ValueError): restrict_protocol_cards(p,{'BASH','SPLASH'})


def test_validation_cutoff_is_scored_but_never_enters_training():
    from sts2_env.az.native_generic import to_episode
    with gzip.open('tests/fixtures/native_validation_cutoff_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    assert raw['outcome']['decisions']==100 and not raw['complete']
    assert len(validate_raw(raw,allow_validation_cutoff=True))==100
    assert raw['outcome']['reward']==pytest.approx(-.61765625)
    assert not any(s['terminalAfter'] for s in raw['steps'])
    with pytest.raises(ValueError): validate_raw(raw)
    with pytest.raises(ValueError): to_episode(raw)
    for path,value in [(('arm',),'puct'),(('split',),'train'),
                       (('outcome','terminationReason'),'death'),
                       (('outcome','decisions'),99),(('outcome','reward'),-.5),
                       (('outcome','cutoff','risk'),float('nan')),
                       (('outcome','cutoff','pendingChoice'),True)]:
        bad=copy.deepcopy(raw); target=bad
        for key in path[:-1]: target=target[key]
        target[path[-1]]=value
        with pytest.raises(ValueError): validate_raw(bad,allow_validation_cutoff=True)


def test_recorded_hexed_and_downgraded_calculated_features():
    with gzip.open('tests/fixtures/native_hexed_calculated_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    entities=[e for s in raw['steps'] for e in encode(s['observation'])['entities'] if e['kind']=='card']
    hexed=[e for e in entities if e['native']['model']=='EVIL_EYE' and e['native']['affliction']=='HEXED']
    assert hexed and all('Ethereal' in e['Keywords'] and 'Ethereal' in e['native']['keywords'] for e in hexed)
    downgraded=[e for e in entities if e['native']['model']=='EXPECT_A_FIGHT' and e['native']['upgrade']==0]
    assert downgraded and all(e['native']['variables']['CalculatedBlock']==e['native']['variables']['CalculationBase']==15 for e in downgraded)
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_stratagem_contains_all_semantic_two_card_combinations():
    from itertools import combinations
    with gzip.open('tests/fixtures/native_stratagem_choices_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    frame=next(s['observation'] for s in raw['steps'] if s['observation']['choice'])
    assert frame['choice']['min']==frame['choice']['max']==2
    def key(cards): return tuple(sorted(json.dumps(c,sort_keys=True) for c in cards))
    expected={key(pair) for pair in combinations(frame['choice']['options'],2)}
    actual={key(x['card'] for x in a['features']['selected']) for a in frame['actions']}
    assert len(actual)==37 and actual==expected
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_catastrophe_repeated_play_and_choice_continuations():
    with gzip.open('tests/fixtures/native_catastrophe_sequence_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    actions=[s['action'] for s in raw['steps']]
    assert sum(a.startswith('PlayCard:CATASTROPHE:') for a in actions)>=2
    assert any(a.startswith('choice:PlayCard:CATASTROPHE:') for a in actions)
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_tunneler_block_break_stun_survives_turn_boundary():
    with gzip.open('tests/fixtures/native_tunneler_burrow_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    assert raw['outcome']['turns']>8
    assert any(i['kind']=='StunIntent' for s in raw['steps'] for e in s['observation']['intents'] for i in e['intents'])
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_tear_asunder_retained_root_history_is_not_double_counted():
    with gzip.open('tests/fixtures/native_tear_asunder_history_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    assert raw['seed']==1600000142 and raw['outcome']['decisions']==28
    assert raw['steps'][14]['action'].startswith('PlayCard:TEAR_ASUNDER:')
    # The fourth-turn hit must leave 11 block, not 1 from double-counted live damage events.
    enemies=[c for c in raw['steps'][15]['observation']['observation']['Creatures'] if c['PlayerId'] is None]
    assert any(c['Block']==11 for c in enemies)


def test_native_dark_orb_projection_and_capacity_survive_encoding():
    from sts2_env.az.native_generic import to_episode
    with gzip.open('tests/fixtures/native_dark_orb_projection_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    packed=validate_raw(raw)
    players=[next(e for e in p['entities'] if e['kind']=='player') for p in packed]
    with_orbs=[p for p in players if p['Orbs']]
    assert len(with_orbs)==24 and all(p['OrbCapacity']>=len(p['Orbs']) for p in with_orbs)
    assert all(o['Passive']==6 for p in with_orbs for o in p['Orbs'])
    assert max(o['Evoke'] for p in with_orbs for o in p['Orbs'])>6
    assert len(to_episode(raw)['rows'])==25


def test_seeker_killing_blow_does_not_leave_a_choice():
    with gzip.open('tests/fixtures/native_seeker_terminal_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    assert raw['outcome']['won'] and raw['outcome']['finalHp']==80
    last=raw['steps'][-1]
    assert last['action'].startswith('PlayCard:SEEKER_STRIKE:') and last['terminalAfter']
    assert last['successorParityScope']=='complete_continuation'


def test_evileye_two_block_events_share_unmovable_card_play():
    with gzip.open('tests/fixtures/native_evileye_unmovable_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    gains=[]
    for s,next_step in zip(raw['steps'],raw['steps'][1:]):
        if s['action'].startswith('PlayCard:EVIL_EYE:'):
            before=s['observation']['observation']['Creatures'][0]
            after=next_step['observation']['observation']['Creatures'][0]
            if any(p['ModelId']=='POWER.UNMOVABLE_POWER' for p in before['Powers']):
                gains.append(after['Block']-before['Block'])
    assert 32 in gains and 24 not in gains


def test_training_cutoff_preserves_labels_reward_and_replay_resume(tmp_path):
    from sts2_env.az.native_generic import to_episode,GenericReplay
    with gzip.open('tests/fixtures/native_training_cutoff_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    with pytest.raises(ValueError):validate_raw(raw)
    validate_raw(raw,allow_training_cutoff=True)
    episode=to_episode(raw)
    assert episode['complete'] and not raw['complete']
    assert episode['outcome']['termination_reason']=='time_limit' and episode['outcome']['truncated']
    assert not raw['steps'][-1]['terminalAfter']
    assert episode['rows'][-1]['z']==pytest.approx(-.18015625)
    replay=GenericReplay(tmp_path,leaf_mode='mixed',value_mix=.5);replay.commit(episode)
    restored=GenericReplay(tmp_path,leaf_mode='mixed',value_mix=.5)
    assert restored.read_episode(episode['episode_id'])==episode
    for mutate in [lambda r:r['outcome'].update(reward=-1),
                   lambda r:r['steps'][-1].update(terminalAfter=True),
                   lambda r:r['outcome'].update(terminationReason='death')]:
        bad=copy.deepcopy(raw);mutate(bad)
        with pytest.raises(ValueError):to_episode(bad)


def test_possess_strength_is_refunded_between_whirlwind_hits():
    with gzip.open('tests/fixtures/native_possess_multihit_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    last=raw['steps'][-1]
    assert last['action'].startswith('PlayCard:WHIRLWIND:')
    creatures=last['observation']['observation']['Creatures']
    assert [c['CurrentHp'] for c in creatures]==[40,7,21]
    assert any(p['ModelId']=='POWER.STRENGTH_POWER' and p['Amount']==2 for p in creatures[0]['Powers'])
    # Two hits: 10 then 12 after THE_LOST returns 2 stolen strength.
    # Deferred refund dealt only 20, leaving THE_FORGOTTEN alive at 1 HP.
    assert last['terminalAfter'] and raw['outcome']['won']
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_hidden_gem_can_give_playable_status_three_replays():
    with gzip.open('tests/fixtures/native_hidden_gem_status_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    assert raw['seed']==37003
    assert any(s['action'].startswith('PlayCard:HIDDEN_GEM:') for s in raw['steps'])
    assert any(s['action'].startswith('PlayCard:SLIMED:') and '|replay=3|' in s['action'] for s in raw['steps'])
    assert all(s['featureParity'] and s['successorParity'] and s['successorParityScope']=='complete_continuation' for s in raw['steps'])


def test_brand_self_damage_inferno_finishes_before_exhaust_choice():
    with gzip.open('tests/fixtures/native_brand_inferno_terminal_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    last=raw['steps'][-1]
    assert last['action'].startswith('PlayCard:BRAND:') and last['terminalAfter']
    assert raw['outcome']['won'] and raw['outcome']['finalHp']==76
    assert any(s['action'].startswith('choice:PlayCard:BRAND:') for s in raw['steps'])
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_steam_eruption_phase_switch_preserves_subsequent_hits():
    with gzip.open('tests/fixtures/native_steam_multihit_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    giant=next(c for s in raw['steps'] for c in s['observation']['observation']['Creatures'] if c['MaxHp']>100000)
    assert giant['CurrentHp']==999999989
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_headbutt_killing_blow_does_not_request_discard_choice():
    with gzip.open('tests/fixtures/native_headbutt_terminal_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    last=raw['steps'][-1]
    assert last['action'].startswith('PlayCard:HEADBUTT:') and last['terminalAfter']
    assert raw['outcome']['won']
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_calamity_stomp_entry_counts_attack_finished_before_generation():
    with gzip.open('tests/fixtures/native_calamity_stomp_entry_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    validate_raw(raw)
    before,after=raw['steps'][-2:]
    assert before['action'].startswith('PlayCard:BREAKTHROUGH:')
    assert not any(c['data']['model']=='STOMP' for c in before['observation']['cards'])
    stomp=next(c['data'] for c in after['observation']['cards'] if c['data']['model']=='STOMP')
    assert stomp['cost']==2
    assert after['action'].startswith('PlayCard:STOMP:') and after['terminalAfter']
    assert any(s['action'].startswith('choice:PlayCard:HEADBUTT:') for s in raw['steps'])
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])


def test_injected_selector_finishes_setup_before_rampart_hook():
    with gzip.open('tests/fixtures/native_selector_turn_start_v1.json.gz','rt',encoding='utf-8') as f:
        raw=json.load(f)
    assert raw['format']=='native-diagnostic-replay-v1'
    assert len(raw['steps'])==12
    last=raw['steps'][-1]
    assert last['action'].startswith('choice:EndTurn:')
    assert any(c['MonsterId']=='MONSTER.LIVING_SHIELD' for c in last['observation']['observation']['Creatures'])
    assert 'LIVING_SHIELD' not in raw['continuation']
    assert '/TURRET_OPERATOR/-/17/41/0/RELOAD_MOVE' in raw['continuation']
    assert all(s['featureParity'] and s['successorParity'] for s in raw['steps'])
