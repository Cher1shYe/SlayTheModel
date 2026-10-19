"""Narrow native teacher adapter; never mix privileged labels into observable replay."""
from collections import Counter
from types import SimpleNamespace as NS
import math

from .config import content_hash
from .content import ALL_CONTENT
from .rewards import V7
from .entity_encoder import Entity, EntityObservation, ActionCandidate, numeric
from .entity_replay import EntityReplayBuffer, pack_observation
from .expanded_entities import card_entity, pile_state
from .all_entities import enemy_entities, POWER_OPS
from .monster_registry import info_for
from .risk_reward import utility

FORMAT = 'native-collection-pilot-v1'
TEACHER = 'native_checkpoint_privileged'
CARDS = {'STRIKE_IRONCLAD': 1, 'DEFEND_IRONCLAD': 1, 'BASH': 2}
EXPANDED_CARDS = {**CARDS, 'IRON_WAVE': 1, 'POMMEL_STRIKE': 1, 'TWIN_STRIKE': 1}
ENCOUNTERS = {'BYRDONIS_ELITE': 'BYRDONIS', 'NIBBITS_WEAK': 'NIBBIT'}
EXPANDED_FORMAT = 'native-collection-v2'


def integer(value, low=0, high=100000):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid native integer')
    return value


def encode_native(d):
    """Return public features and a bijection from native actions to current action keys.

    Draw order, RNG, native state fingerprints and card instance identities are
    never network features. Native intent damage is authoritative (Byrdonis=17,
    whereas the Python monster registry currently says 16).
    """
    v2 = d['version'] == 'native-collection-observation-v2'
    cards_allowed = EXPANDED_CARDS if v2 else CARDS
    if not v2 and d['version'] != 'native-starter-prior-v1':
        raise ValueError('Unknown native observation schema')
    for k in ('played', 'attacks', 'unblockedHits', 'decisions', 'block'):
        integer(d[k])
    integer(d['turn'], 1, 40)
    integer(d['maxHp'], 1)
    integer(d['hp'], 1, d['maxHp'])
    integer(d['initialHp'], 1, d['maxHp'])
    integer(d['energy'], 0, 3)
    if d['attacks'] > d['played'] or len(d['enemies']) != 1:
        raise ValueError('Unsupported native scope')
    entities = [Entity('state', 'state', 'none', None, numeric(
        turn=d['turn'], decisions=d['decisions'], max_decisions=100 if v2 else 400, max_turns=40,
        initial_hp=d['initialHp'], played_this_turn=d['played'], completed_plays=d['played'],
        attack_count=d['attacks'], enemy_rounds=d['turn']-1, received_unblocked_hits=d['unblockedHits'])),
        Entity('player', 'player', 'none', None, numeric(hp=d['hp'], max_hp=d['maxHp'],
            block=d['block'], energy=d['energy'], max_energy=3))]
    enemy = d['enemies'][0]
    if enemy['id'] not in (ENCOUNTERS.values() if v2 else ('BYRDONIS',)):
        raise ValueError('Unaudited native encounter')
    integer(enemy['hp'], 1, integer(enemy['maxHp'], 1))
    integer(enemy['block'])
    script = info_for(enemy['id'])
    histories = []
    for initial in script.initial_moves:
        move, history = initial, []
        for _ in range(d['turn']-1):
            history.append(move)
            successors = dict(script.successors)[move]
            if len(successors) != 1:
                raise ValueError('Ambiguous native history')
            move = successors[0]
        if enemy['move'] == move:
            histories.append(history)
    if len(histories) != 1:
        raise ValueError('Native move/history mismatch')
    history, move = histories[0], enemy['move']
    intents = dict(script.intent_signatures)[move]
    hits = enemy['hits']
    expected_count = sum(n for kind, _, n in intents if kind in ('ATTACK', 'MULTI_ATTACK'))
    if len(hits) != expected_count or len(set(hits)) > 1:
        raise ValueError('Native intent shape mismatch')
    for damage in hits:
        integer(damage)
    intents = tuple((kind, hits[0], n) if kind in ('ATTACK', 'MULTI_ATTACK') else (kind, damage, n)
                    for kind, damage, n in intents)
    powers = tuple((p['id'].removesuffix('_POWER'), p['amount']) for p in enemy['powers'])
    if len(dict(powers)) != len(powers) or any(name not in POWER_OPS for name, _ in powers):
        raise ValueError('Unsupported native power')
    for _, amount in powers:
        integer(amount, -10000)
    values = dict(slot=0, monster_id=enemy['id'], hp=enemy['hp'], max_hp=enemy['maxHp'],
        initial_hp=enemy['maxHp'], block=enemy['block'], move=move, moves=tuple(history),
        intents=intents, powers=powers, primary=True, spawned=False, reviving=False)
    for field in ('vulnerable', 'strength', 'slow', 'territorial', 'artifact', 'illusion', 'minion'):
        values[field] = dict(powers).get(field.upper(), 0)
    entities.extend(enemy_entities(NS(enemies=[NS(**values)], history=NS(pending_target=None))))
    for zone in ('hand', 'discard', 'draw'):
        tokens = [c['id'] for c in d[zone]]
        if any(token not in cards_allowed for token in tokens):
            raise ValueError('Unsupported native card')
        if v2:
            from .expanded_mechanics import describe_card
            for card in d[zone]:
                description = describe_card(card['id'])
                if card['cost'] != description.cost:
                    raise ValueError('Native/Python card cost mismatch')
                for effect in description.effects:
                    variable = {'damage': 'Damage', 'block': 'Block', 'draw': 'Cards'}.get(effect.kind)
                    if variable and card['baseValues'].get(variable) != effect.amount:
                        raise ValueError('Native/Python card effect value mismatch')
        entries = sorted(Counter(tokens).items()) if zone == 'draw' else [(t, 1) for t in tokens]
        for i, (token, count) in enumerate(entries):
            entities.append(card_entity(f'{zone}/{i}', pile_state(token, 0), zone,
                                       count=count, slot=i+1 if zone == 'hand' else 0))
    actions, mapping = [], {}
    for a in d['actions']:
        if a['Key'] in mapping:
            raise ValueError('Duplicate native action')
        if a['Kind'] == 'EndTurn':
            key = 'end_turn'
            action = ActionCandidate(key, 'end_turn')
        else:
            if a['Kind'] not in ('PlayCard', 'Play') or a['CardId'] not in cards_allowed:
                raise ValueError('Unsupported native action kind/card')
            if a['CardUpgradeLevel'] != 0 or a['CardEnchantmentId'] or a.get('SelectedCards'):
                raise ValueError('Modified cards/selections outside pilot')
            matches = [i for i, c in enumerate(d['hand']) if c['stateKey'] == a['CardStateKey']]
            occurrence = integer(a['CardStateOccurrence'], 0, len(matches)-1)
            i = matches[occurrence]
            card = d['hand'][i]['id']
            if card != a['CardId'] or cards_allowed[card] > d['energy']:
                raise ValueError('Native card identity/energy mismatch')
            if card == 'DEFEND_IRONCLAD':
                if a['TargetCombatId'] is not None:
                    raise ValueError('Defense cannot target an enemy')
                target = 'player'
            else:
                if a['TargetCombatId'] != enemy['combatId']:
                    raise ValueError('Unknown attack target')
                target = 'enemy/0'
            key = f'play:hand/{i}:{target}'
            action = ActionCandidate(key, 'play', f'hand/{i}', (target,))
        mapping[a['Key']] = key
        actions.append(action)
    # Native legal actions merge semantically identical copies. Require complete
    # equivalence-class coverage, not one action per physical duplicate card.
    expected = {('end_turn',)} | {(c['id'], c['stateKey'], 'player' if c['id']=='DEFEND_IRONCLAD' else 'enemy/0')
        for c in d['hand'] if cards_allowed[c['id']] <= d['energy']}
    actual = set()
    for action in actions:
        if action.action_type == 'end_turn':
            actual.add(('end_turn',))
        else:
            card = d['hand'][int(action.source_ref.split('/')[1])]
            actual.add((card['id'], card['stateKey'], action.target_refs[0]))
    if actual != expected or len(set(mapping.values())) != len(mapping):
        raise ValueError('Incomplete/nonbijective native action classes')
    obs = EntityObservation(tuple(entities), tuple(actions), content_version=ALL_CONTENT, reward_version=V7).validate()
    return obs, mapping


def validate_raw(raw):
    v2 = raw['format'] == EXPANDED_FORMAT
    if (raw['format'] not in (FORMAT, EXPANDED_FORMAT) or raw['teacherInformation'] != TEACHER or raw['complete'] is not True
            or raw['encounter'] not in (ENCOUNTERS if v2 else ('BYRDONIS_ELITE',)) or raw['arm'] not in ('policy', 'uct', 'puct')
            or raw['split'] not in ('train', 'validation') or not raw['steps']):
        raise ValueError('Native collection contract mismatch')
    for name in ('identity', 'modelSha256'):
        if len(raw[name]) != 64 or any(c not in '0123456789abcdef' for c in raw[name]):
            raise ValueError('Missing native provenance')
    integer(raw['seed'], 0, 1_999_999_999)
    integer(raw['budgetMs'], 50, 1000)
    if not math.isfinite(raw['wallSeconds']) or raw['wallSeconds'] < 0:
        raise ValueError('Invalid native wall time')
    end = raw['outcome']
    integer(end['maxHp'], 1, 80)
    integer(end['finalHp'], 0, end['maxHp'])
    if end['won'] != (end['finalHp'] > 0):
        raise ValueError('Inconsistent native terminal HP')
    if v2:
        from .native_backend import validate_recipe
        recipe = validate_recipe(raw['recipe'])
        if not math.isfinite(end['searchReward']) or abs(end['searchReward'] - end['reward']) > 1e-15:
            raise ValueError('Native rollout/canonical reward mismatch')
        if any(recipe[k] != raw[k] for k in ('seed', 'encounter', 'split')) or recipe['hp'] != raw['initialHp']:
            raise ValueError('Native recipe mismatch')
    if type(end['won']) is not bool or end['decisions'] != len(raw['steps']):
        raise ValueError('Native endpoint mismatch')
    z = utility('win' if end['won'] else 'death', end['finalHp'], raw['initialHp'], end['maxHp'], 1., 0.)
    if z != end['reward']:
        raise ValueError('Native/Python terminal reward mismatch')
    converted, inventory = [], None
    for index, step in enumerate(raw['steps']):
        d = step['observation']
        if v2 and (d['version'] != 'native-collection-observation-v2'
                   or [e['id'] for e in d['enemies']] != [ENCOUNTERS[raw['encounter']]]):
            raise ValueError('Native observation/encounter mismatch')
        if (step['featureParity'] is not True or step['successorParity'] is not True
                or d['initialHp'] != raw['initialHp'] or d['maxHp'] != end['maxHp']
                or d['decisions'] != index
                or step['terminalAfter'] != (index == len(raw['steps'])-1)):
            raise ValueError('Missing native state parity evidence')
        if index == 0 and d['hp'] != raw['initialHp']:
            raise ValueError('Wrong initial native HP')
        expected_hp = end['finalHp'] if step['terminalAfter'] else raw['steps'][index+1]['observation']['hp']
        if step['hpAfter'] != expected_hp:
            raise ValueError('Broken native trajectory')
        cards = Counter(c['id'] for zone in ('hand', 'draw', 'discard') for c in d[zone])
        if v2 and cards != Counter(recipe['deck']):
            raise ValueError('Native recipe deck mismatch')
        if inventory is not None and cards != inventory:
            raise ValueError('Native card inventory changed')
        inventory = cards
        obs, mapping = encode_native(d)
        counts = step['visits']
        if (set(counts) != set(mapping) or step['action'] not in mapping
                or type(step['forced']) is not bool or step['forced'] != (len(mapping) == 1)
                or not math.isfinite(step['seconds']) or step['seconds'] < 0):
            raise ValueError('Native action/search metadata mismatch')
        for count in counts.values():
            integer(count)
        integer(step['simulations'])
        if sum(counts.values()) != step['simulations']:
            raise ValueError('Native visit sum mismatch')
        if raw['arm'] == 'policy' or step['forced']:
            if step['simulations']:
                raise ValueError('Policy/forced decisions must not claim simulations')
        elif step['simulations'] <= 0:
            raise ValueError('Missing native search labels')
        converted.append((obs, mapping))
    return converted


def to_episode(raw):
    converted = validate_raw(raw)
    if raw['split'] != 'train' or raw['arm'] == 'policy':
        raise ValueError('Only native search training fights may enter replay')
    v2 = raw['format'] == EXPANDED_FORMAT
    identity = content_hash([raw['identity'], raw['arm'], raw['seed'], raw['initialHp'], raw['recipe']]) if v2 else content_hash([raw['identity'], raw['arm'], raw['seed'], raw['initialHp']])
    rows = []
    for i, (step, (obs, mapping)) in enumerate(zip(raw['steps'], converted)):
        visits = {mapping[k]: v for k, v in step['visits'].items()}
        pi = ({k: 1. for k in visits} if step['forced'] else
              {k: v / step['simulations'] for k, v in visits.items()})
        rows.append(dict(episode_id=identity, step_index=i, family_id='native-six-cards-v2' if v2 else 'native-starter-pilot',
            encounter_id=raw['encounter'], scenario_id=raw['recipe']['scenario_id'] if v2 else f"native-{raw['seed']}-{raw['initialHp']}",
            model_version=raw['modelSha256'], observation=pack_observation(obs), policy_target=pi,
            root_visits=visits, chosen_action=mapping[step['action']], z=raw['outcome']['reward'],
            search_simulations=step['simulations'], search_seconds=step['seconds'], forced_action=step['forced']))
    return dict(episode_id=identity, complete=True, split='train', rows=rows, native_audit=raw,
                compatibility=(NativeExpandedReplayBuffer if v2 else NativeReplayBuffer).compatibility_for(),
                outcome={**raw['outcome'], 'termination_reason': 'win' if raw['outcome']['won'] else 'death'} if v2 else raw['outcome'])


class NativeReplayBuffer(EntityReplayBuffer):
    """Reuse atomic whole-episode storage/sampling, with a distinct strict audit codec."""
    @staticmethod
    def compatibility_for(content_version=ALL_CONTENT, reward_version=V7, leaf_mode='heuristic', value_mix=.5):
        if (content_version, reward_version, leaf_mode) != (ALL_CONTENT, V7, 'heuristic'):
            raise ValueError('Unsupported native replay configuration')
        return {**EntityReplayBuffer.compatibility_for(ALL_CONTENT, V7),
                'native_adapter': FORMAT, 'teacher_information': TEACHER,
                'action_contract': 'native-equivalent-card-classes-v1',
                'native_scope': 'byrdonis-starter-v1', 'search_version': 'native-rollout-visits-v1'}

    def __init__(self, directory, capacity=50000):
        super().__init__(directory, capacity, content_version=ALL_CONTENT, reward_version=V7)

    def validate(self, episode):
        if episode['compatibility'] != self.compatibility or episode != to_episode(episode['native_audit']):
            raise ValueError('Native replay differs from its audited source')


class NativeExpandedReplayBuffer(NativeReplayBuffer):
    @staticmethod
    def compatibility_for(content_version=ALL_CONTENT, reward_version=V7, leaf_mode='heuristic', value_mix=.5):
        return {**NativeReplayBuffer.compatibility_for(content_version, reward_version, leaf_mode, value_mix),
                'native_adapter': EXPANDED_FORMAT, 'native_scope': 'six-cards-two-encounters-v2'}
