"""Compact typed entity rows using the existing whole-episode Replay lifecycle."""
import base64
import gzip
import json
import os
from pathlib import Path
import struct
import tempfile
import numpy as np

from .config import atomic_replace, canonical_json, content_hash, CONTENT_VERSION, REWARD_VERSION
from .entity_encoder import Entity, ActionCandidate, EntityObservation, SCHEMA, SCHEMA_HASH, NUMERIC_FIELDS, KINDS, ZONES, SUPPORTED, supported_reward
from .mechanic_registry import Operation, OPS, TARGETS, TIMINGS, CONDITIONS
from .replay_buffer import ReplayBuffer, episode_digest
from .dynamic_search import VERSION
from .search_config import DYNAMIC_RISK
from .rewards import V7
from .risk_reward import public_risk

REPLAY_VERSION = 'typed-entity-replay-v2'


def pack_observation(obs):
    obs.validate()
    refs = {e.ref: i for i, e in enumerate(obs.entities)}
    return {'schema_hash': obs.schema_hash, 'content_version':obs.content_version,'reward_version':obs.reward_version,
        'numbers_f64le': base64.b64encode(struct.pack('<' + 'd'*len(NUMERIC_FIELDS)*len(obs.entities),
            *(x for e in obs.entities for x in e.numbers))).decode('ascii'),
        'entities': [[e.ref, KINDS.index(e.kind), ZONES.index(e.zone), refs[e.owner] if e.owner else -1,
            [[OPS.index(o.kind), TARGETS.index(o.target), TIMINGS.index(o.timing), o.amount, o.hits,CONDITIONS.index(o.condition),o.coefficient] for o in e.effects]] for e in obs.entities],
        'actions': [[a.action_key, a.action_type, refs[a.source_ref] if a.source_ref else -1,
                     [refs[r] for r in a.target_refs], a.legal,[refs[r] for r in a.choice_refs]] for a in obs.actions]}


def unpack_observation(data):
    if set(data) != {'schema_hash', 'numbers_f64le', 'entities', 'actions','content_version','reward_version'} or data['schema_hash'] != SCHEMA_HASH:
        raise ValueError('Packed entity schema mismatch')
    rows = data['entities']
    if not 1 <= len(rows) <= SCHEMA['max_entities']:
        raise ValueError('Packed entity length overflow')
    try:
        values = struct.unpack('<' + 'd'*len(NUMERIC_FIELDS)*len(rows), base64.b64decode(data['numbers_f64le'], validate=True))
        def ref(index):
            if type(index) is not int or index < -1 or index >= len(rows):
                raise ValueError('Invalid packed reference')
            return None if index == -1 else rows[index][0]
        entities = tuple(Entity(row[0], KINDS[row[1]], ZONES[row[2]], ref(row[3]),
            tuple(values[i*len(NUMERIC_FIELDS):(i+1)*len(NUMERIC_FIELDS)]),
            tuple(Operation(OPS[o[0]], TARGETS[o[1]], TIMINGS[o[2]], o[3], o[4],CONDITIONS[o[5]],o[6]) for o in row[4])) for i, row in enumerate(rows))
        actions = tuple(ActionCandidate(row[0], row[1], ref(row[2]), tuple(ref(i) for i in row[3]),tuple(ref(i) for i in row[5]), legal=row[4]) for row in data['actions'])
        obs = EntityObservation(entities, actions, data['schema_hash'],data['content_version'],data['reward_version']).validate()
        if pack_observation(obs) != data:
            raise ValueError('Noncanonical packed observation')
        return obs
    except (IndexError, KeyError, TypeError, struct.error) as exc:
        raise ValueError('Malformed packed entity row') from exc


class EntityReplayBuffer(ReplayBuffer):
    @staticmethod
    def compatibility_for(content_version=CONTENT_VERSION,reward_version=REWARD_VERSION,
                          leaf_mode='heuristic', value_mix=.5):
        from .search_config import leaf_settings
        settings = leaf_settings(leaf_mode, value_mix)
        if reward_version != V7 and leaf_mode != 'heuristic':
            raise ValueError('Leaf evaluation modes require V7')
        result = dict(format_version=REPLAY_VERSION, schema_hash=SCHEMA_HASH, search_version=DYNAMIC_RISK if reward_version == V7 else VERSION,
                    information_mode='observable', reward_version=reward_version, content_version=content_version)
        # Retain the exact legacy compatibility for default heuristic datasets.
        if leaf_mode != 'heuristic':
            result['leaf_mode'] = leaf_mode
            if leaf_mode == 'mixed':
                result['value_mix'] = settings['value_mix']
        return result

    def __init__(self, directory, capacity=200_000, **kwargs):
        content=kwargs.get('content_version',CONTENT_VERSION)
        reward=kwargs.get('reward_version',SUPPORTED.get(content))
        if not supported_reward(content, reward):
            raise ValueError('Unsupported entity replay content/reward')
        search = DYNAMIC_RISK if reward == V7 else VERSION
        if kwargs.get('search_version', search) != search or kwargs.get('information_mode', 'observable') != 'observable':
            raise ValueError('Entity replay requires dynamic observable search')
        if type(capacity) is not int or capacity < 1:
            raise ValueError('Positive replay capacity required')
        self.directory, self.capacity = Path(directory), capacity
        self.content_version, self.search_version = content, search
        self.compatibility = self.compatibility_for(content, reward,
            kwargs.get('leaf_mode', 'heuristic'), kwargs.get('value_mix', .5))
        self.episodes, self.committed = [], {}
        path = self.directory / 'manifest.json'
        if path.exists():
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if manifest['compatibility'] != self.compatibility or manifest['capacity'] != capacity:
                raise ValueError('Entity replay version/capacity mismatch; legacy replay cannot auto-upgrade')
            self.committed = manifest['committed']
            for identity in manifest['active']:
                episode = self.read_episode(identity)
                self.validate(episode)
                if self.digest(episode) != self.committed[identity]:
                    raise ValueError('Replay episode checksum mismatch')
                self.episodes.append(episode)

    def read_episode(self, identity):
        if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid episode identity')
        return json.loads(gzip.decompress((self.directory / 'episodes' / f'{identity}.json.gz').read_bytes()))

    def write_episode(self, identity, payload):
        path = self.directory / 'episodes' / f'{identity}.json.gz'
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(gzip.compress(canonical_json(payload).encode(), mtime=0))
                stream.flush()
                os.fsync(stream.fileno())
            atomic_replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def validate(self, episode):
        rows = episode.get('rows', [])
        identity = episode.get('episode_id', '')
        if (episode.get('complete') is not True or episode.get('split') != 'train' or not rows
                or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity)
                or episode.get('compatibility') != self.compatibility):
            raise ValueError('Invalid complete entity episode')
        outcome = episode['outcome']
        if outcome['decisions'] != len(rows) or outcome['termination_reason'] not in ('win', 'death', 'time_limit'):
            raise ValueError('Incomplete episode outcome')
        from .entity_transition import public_from_dict
        final = public_from_dict(episode['final_public'])
        z = final.terminal_value()
        from .rewards import terminal_reward
        settled = terminal_reward(outcome['termination_reason'],outcome['final_hp'],outcome['initial_hp'],
            outcome['enemy_final_hp'],outcome['enemy_max_hp'],final.reward_version,
            enemy_initial_hp=outcome.get('enemy_initial_hp'),enemy_roster=outcome.get('enemy_roster'),
            player_max_hp=outcome.get('player_max_hp'),incoming_risk=outcome.get('incoming_risk'))
        if (z is None or final.content_version!=self.content_version or final.reward_version!=self.compatibility['reward_version']
                or outcome['reward'] != z or settled != z or final.history.decisions != len(rows)
                or final.termination_reason != outcome['termination_reason'] or final.player_hp != outcome['final_hp']
                or (final.reward_version == 'risk-terminal-v7' and (outcome.get('player_max_hp') != final.player_max_hp
                    or outcome.get('incoming_risk') != public_risk(final)))
                # Public turn is the actual boundary (max_turns + 1 after
                # ending the last playable turn); outcome counts playable turns.
                or min(final.turn, final.limits.max_turns) != outcome['turns']):
            raise ValueError('Final public state/outcome mismatch')
        for i, row in enumerate(rows):
            obs = unpack_observation(row['observation'])
            if (obs.content_version,obs.reward_version)!=(self.content_version,self.compatibility['reward_version']):
                raise ValueError('Replay observation content/reward mismatch')
            keys = {a.action_key for a in obs.actions}
            legal = {a.action_key for a in obs.actions if a.legal}
            pi, visits = row['policy_target'], row['root_visits']
            if (row['step_index'] != i or row['episode_id'] != identity or row['z'] != z
                    or set(pi) != keys or set(visits) != keys or row['chosen_action'] not in legal
                    or not np.isfinite(list(pi.values())).all() or any(p < 0 for p in pi.values())
                    or not np.isclose(sum(pi.values()), 1) or any(pi[k] or visits[k] for k in keys-legal)
                    or any(type(v) is not int or v < 0 for v in visits.values())
                    or type(row['search_simulations']) is not int or type(row['forced_action']) is not bool
                    or not np.isfinite(row['search_seconds']) or row['search_seconds'] < 0
                    or any(row[k] != rows[0][k] for k in ('family_id', 'scenario_id', 'model_version'))
                    or row['public_digest'] != content_hash(row['public_information'])):
                raise ValueError('Invalid keyed replay labels/audit digest')
            if row['forced_action']:
                if len(legal) != 1 or sum(visits.values()) or row['search_simulations'] != 0:
                    raise ValueError('Invalid forced action')
            elif (sum(visits.values()) != row['search_simulations'] or row['search_simulations'] <= 0
                  or any(not np.isclose(pi[k], visits[k]/row['search_simulations']) for k in keys)):
                raise ValueError('Dynamic labels must equal normalized visits')
            # Rebuild from the public audit projection, not the simulator or recipe.
            from .entity_encoder import encode_entities
            public = public_from_dict(row['public_information'])
            if public.history.decisions != i or public.limits != final.limits or pack_observation(encode_entities(public)) != row['observation']:
                raise ValueError('Replay features disagree with public audit')
