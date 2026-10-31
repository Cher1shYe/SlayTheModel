"""Local, line-oriented, *approximate* ArmG inference for live observations.

The live protocol does not contain every simulator feature. This worker never
executes game actions and reports the approximation list with every modeled
response. The caller chooses whether to apply approximate predictions. Unknown
IDs or action semantics are rejected rather than mapped to another item.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from armg_live_events import UnsupportedEvent, encode_live_event


class Unsupported(ValueError):
    pass


def _enum_members(path: Path, marker: str) -> dict[str, int]:
    source = path.read_text(encoding='utf-8')
    body = source.split(marker, 1)[1].split('};', 1)[0]
    result = {}
    for item in body.split(','):
        name = item.strip().split('=', 1)[0].strip()
        if name and name != 'COUNT':
            result[name] = len(result)
    return result


def _key(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix + '.'):
        raise Unsupported(f'expected {prefix} model ID, got {value!r}')
    return value[len(prefix) + 1:].split('+', 1)[0]


def _id(value, prefix, mapping):
    key = _key(value, prefix)
    if key not in mapping and key + '_CARD' in mapping:
        key += '_CARD'
    # Potion bindings use CamelCase while native model IDs use SCREAMING_SNAKE.
    # Canonicalization is accepted only when it identifies exactly one entry.
    if key not in mapping and prefix == 'POTION':
        norm = re.sub(r'[^A-Z0-9]', '', key.upper())
        matches = [name for name in mapping
                   if re.sub(r'[^A-Z0-9]', '', name.upper()) == norm]
        if len(matches) == 1:
            key = matches[0]
    if key not in mapping or mapping[key] == 0:
        raise Unsupported(f'unknown {prefix} ID {value!r}')
    return mapping[key]


def _one(index, count):
    a = [0.0] * count
    if 0 <= index < count:
        a[index] = 1.0
    return a


def _coordinate(value):
    if not isinstance(value, dict):
        raise Unsupported('missing map coordinate')
    return int(value['row']), int(value['column'])


class Encoder:
    # Simulator public-observation v10, action schema v9, ArmG feature v1.
    def __init__(self, root, sim, armg):
        self.sim, self.armg = sim, armg
        self.cards = _enum_members(Path(root) / 'simulator/include/sts2/cards_generated.inc',
                                   'enum class CardId : std::uint16_t {')
        self.relics = {k: int(v) for k, v in sim.RelicId.__members__.items()}
        self.potions = {k: int(v) for k, v in sim.PotionId.__members__.items()}
        self.encounters = max(int(x) for x in sim.Encounter.__members__.values()) + 1
        self.relic_count = max(self.relics.values()) + 1
        self.potion_count = max(self.potions.values()) + 1
        self.card_count = sim.CARD_COUNT
        self.card_dim = armg.CARD_FEAT_DIM
        if len(self.cards) != self.card_count:
            raise RuntimeError('card enum source does not match simulator extension')

    def _card(self, obj, *, candidate=False):
        key = obj.get('target_id') if candidate else obj.get('model_id')
        ident = _id(key, 'CARD', self.cards)
        level = obj.get('target_upgrade_level') if candidate else obj.get('upgrade_level')
        if level not in (0, 1):
            raise Unsupported(f'card upgrade level is missing or unsupported: {key}')
        if not candidate and (obj.get('enchantment_id') or obj.get('affliction_id')):
            raise Unsupported('enchanted or afflicted deck card needs additional state')
        return ident, int(level)

    def encode(self, decision):
        build = decision.get('build') or {}
        if (build.get('game_version') != 'v0.111.0' or
                str(build.get('assembly_sha256', '')).lower() !=
                '0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9'):
            raise Unsupported('game version or assembly does not match v0.111.0')
        observation = decision.get('observation') or {}
        surface = observation.get('surface')
        actions = decision.get('legal_actions')
        if surface not in ('card_reward', 'map', 'merchant', 'event') or not isinstance(actions, list) or not actions:
            raise Unsupported(f'unsupported surface {surface!r}')
        action_ids = [a.get('action_id') for a in actions]
        if any(not isinstance(x, str) or not x for x in action_ids) or len(set(action_ids)) != len(action_ids):
            raise Unsupported('missing or duplicate action ID')
        players = observation.get('players') or []
        if len(players) != 1 or players[0].get('character_id') != 'CHARACTER.IRONCLAD':
            raise Unsupported('requires single-player Ironclad')
        player = players[0]
        cards = [self._card(x) for x in player.get('deck', [])]
        if len(cards) > 128 or any(x.get('deck_index') != i for i, x in enumerate(player.get('deck', []))):
            raise Unsupported('deck ordering or size is not supported')
        relics = [_id(x.get('model_id'), 'RELIC', self.relics) for x in player.get('relics', [])]
        pots = [_id(x.get('model_id'), 'POTION', self.potions) for x in sorted(
            player.get('potions', []), key=lambda p: p['slot_index'])]
        if len(pots) > 12:
            raise Unsupported('too many potions')
        map_points = observation.get('map_points') or []
        coords = [_coordinate(x.get('coordinate')) for x in map_points]
        if len(coords) > 119 or len(set(coords)) != len(coords):
            raise Unsupported('map shape is unsupported')
        # Live protocol lacks the simulator's internal node allocation order.
        order = sorted(range(len(coords)), key=lambda i: coords[i])
        nodes = [map_points[i] for i in order]
        coords = [coords[i] for i in order]
        by_coord = {coord: i for i, coord in enumerate(coords)}
        current = observation.get('current_map_coordinate')
        current = _coordinate(current) if current is not None else None
        reachable = set()
        if current in by_coord:
            reachable = {_coordinate(x) for x in nodes[by_coord[current]].get('children', [])}
        type_names = {'unknown': 1, 'shop': 2, 'treasure': 3, 'restsite': 4,
                      'monster': 5, 'elite': 6, 'boss': 7, 'ancient': 8,
                      'unassigned': 0}
        types, children = [], []
        for node in nodes:
            key = re.sub(r'[^a-z]', '', str(node.get('point_type', '')).lower())
            if key not in type_names:
                raise Unsupported(f'unknown map point type {key!r}')
            types.append(type_names[key])
            child = [_coordinate(x) for x in node.get('children', [])]
            if any(x not in by_coord for x in child):
                raise Unsupported('map references an absent child')
            children.append(child)

        event = None
        if surface == 'event':
            try:
                event = encode_live_event(observation, actions, self.sim)
            except UnsupportedEvent as exc:
                raise Unsupported(str(exc)) from exc

        shop = observation.get('shop') if surface == 'merchant' else None
        shop_items = {}
        if surface == 'merchant':
            if not isinstance(shop, dict):
                raise Unsupported('merchant inventory is missing')
            for category, limit, prefix, mapping in (
                ('cards', 7, 'CARD', self.cards), ('relics', 3, 'RELIC', self.relics),
                ('potions', 3, 'POTION', self.potions)):
                items = shop.get(category)
                if not isinstance(items, list) or len(items) > limit:
                    raise Unsupported(f'unsupported shop {category} inventory')
                indexed = {}
                for item in items:
                    slot = item.get('slot_index')
                    if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < limit or slot in indexed:
                        raise Unsupported(f'invalid shop {category} slot')
                    cost = item.get('cost')
                    if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0 or not isinstance(item.get('sold'), bool):
                        raise Unsupported(f'invalid shop {category} cost or sold flag')
                    # Once sold, the native UI may discard its product model.
                    # Retain the sold slot with the simulator's neutral ID;
                    # never permit it as a purchase action. This lets the
                    # policy evaluate other items after an earlier purchase.
                    ident = (0 if item['sold'] and not item.get('model_id')
                             else _id(item.get('model_id'), prefix, mapping))
                    level = item.get('upgrade_level', 0)
                    if category == 'cards' and level not in (0, 1):
                        raise Unsupported('unsupported shop card upgrade')
                    indexed[slot] = (item, ident, int(level))
                shop_items[category] = indexed
            if not isinstance(shop.get('removal_available'), bool) or not isinstance(shop.get('removal_cost'), int) or shop['removal_cost'] < 0:
                raise Unsupported('invalid shop card removal state')

        offered = []
        for a in actions:
            if surface == 'card_reward' and a.get('kind') == 'choose_card':
                offered.append(self._card(a, candidate=True))
            elif surface == 'card_reward' and a.get('kind') == 'skip':
                pass
            elif surface == 'card_reward' and a.get('kind') == 'choose_reward_alternative':
                # The simulator action schema has no equivalent for this UI
                # alternative. It remains in the original legal-action order,
                # but is never considered by the scorer's argmax.
                pass
            elif surface == 'map' and a.get('kind') == 'travel' and _coordinate(a.get('map_coordinate')) in by_coord:
                pass
            elif surface == 'merchant' and a.get('kind') in ('buy_card', 'buy_relic', 'buy_potion'):
                category = {'buy_card': 'cards', 'buy_relic': 'relics', 'buy_potion': 'potions'}[a['kind']]
                slot = a.get('target_shop_index')
                item = shop_items[category].get(slot)
                if (item is None or item[0]['sold'] or item[0]['model_id'] != a.get('target_id')
                        or item[0]['cost'] != a.get('cost') or item[0]['cost'] > player['gold']):
                    raise Unsupported('shop action does not match an affordable unsold item')
            elif surface == 'merchant' and a.get('kind') == 'open_card_removal':
                idx = a.get('target_deck_index')
                if (not shop['removal_available'] or a.get('cost') != shop['removal_cost']
                        or shop['removal_cost'] > player['gold'] or not isinstance(idx, int)
                        or isinstance(idx, bool) or not 0 <= idx < len(cards)
                        or player['deck'][idx]['model_id'] != a.get('target_id')):
                    raise Unsupported('shop removal action does not match the deck')
            elif surface == 'merchant' and a.get('kind') == 'leave_merchant':
                pass
            elif surface == 'event' and a.get('kind') == 'choose_event_option':
                pass  # all identities and simulator indices were validated above
            else:
                raise Unsupported(f"unsupported candidate {a.get('kind')!r}")
        if surface == 'card_reward' and (not offered or len(offered) > 3 or
                sum(a.get('kind') == 'skip' for a in actions) > 1):
            raise Unsupported('requires one to three cards and at most one skip')

        hp, max_hp = int(player['current_hp']), int(player['max_hp'])
        if max_hp <= 0 or hp < 0 or hp > max_hp:
            raise Unsupported('invalid HP')
        floor, act = int(observation['total_floor']), int(observation['act_index'])
        act_floor = int(observation['act_floor'])
        slots = int(player['max_potion_count'])
        v = [0.0] * 38
        v[0:7] = [hp / max_hp, max_hp / 100, int(player['gold']) / 300,
                  floor / 49, (act + 1) / 3, len(cards) / 40,
                  sum(up for _, up in cards) / len(cards) if cards else 0]
        v[11] = act_floor / 15
        v[12] = len(pots) / slots if slots else 0
        v[13] = len(relics) / 20
        if event is not None:
            v[14] = (event.event_id + 1) / 48
            v[15] = event.page / 4
        v[21] = slots / 12
        v += _one({'map': 0, 'card_reward': 2, 'merchant': 4, 'event': 5}[surface], 9)
        bag = [0.0] * self.card_count
        for cid, _ in cards: bag[cid] += 1
        v += bag
        for i in range(128):
            v += ([cards[i][0] / self.card_count, float(cards[i][1]), 0, 0, 0, 0]
                  if i < len(cards) else [0.0] * 6)
        # No selector active. The grid's default slots have no card features.
        v += [0.0] * (8 + 16 + 8 * self.card_dim + 128)
        relic_bag = [0.0] * self.relic_count
        for rid in relics: relic_bag[rid] += 1
        v += relic_bag + [0.0] * self.relic_count
        potion_bag = [0.0] * self.potion_count
        for pid in pots: potion_bag[pid] += 1
        v += potion_bag + [pots[i] / self.potion_count if i < len(pots) else 0.0 for i in range(12)]
        v += [0.0] * (2 * self.encounters)  # Boss IDs unavailable.
        for i in range(119):
            if i < len(nodes):
                row, col = coords[i]
                v += [1.0] + _one(types[i], 9) + [row / 16, col / 6,
                     float(coords[i] in reachable), float(bool(nodes[i].get('visited'))), len(children[i]) / 8]
            else:
                v += [0.0] + _one(0, 9) + [-1 / 16, -1 / 6, 0.0, 0.0, 0.0]
        # eventId=-1; eventPage defaults to zero even when no event is active.
        if event is not None:
            v += event.observation_block(self.relic_count)
        else:
            v += [0.0] * 64
            for i in range(4): v += [0, 0, 0, 0, 0, float(i == 0)] + _one(0, self.relic_count)
            v += [0.0] * 4
        # Unknown reward context is represented with simulator neutral defaults.
        v += [0.0] * 4 + _one(0, self.potion_count)
        for _ in range(8): v += [0.0, 0.0] + _one(0, self.relic_count)
        v += [0.0] * (12 + 8 + 1 + 9 + 1 + 1 + 160 * 18)
        default_card = list(self.sim.card_features(0, False, -1))
        for i in range(3):
            v += list(self.sim.card_features(*offered[i], -1)) if i < len(offered) else default_card
        for i in range(7):
            item = shop_items.get('cards', {}).get(i)
            v += (list(self.sim.card_features(item[1], bool(item[2]), -1)) +
                  [item[0]['cost'] / 200, float(item[0]['sold'])]) if item else default_card + [0.0, 0.0]
        for category, count in (('relics', self.relic_count), ('potions', self.potion_count)):
            for i in range(3):
                item = shop_items.get(category, {}).get(i)
                divisor = 300 if category == 'relics' else 150
                v += (_one(item[1], count) + [item[0]['cost'] / divisor, float(item[0]['sold'])]) if item else _one(0, count) + [0.0, 0.0]
        v += ([shop['removal_cost'] / 200, float(not shop['removal_available']), 0, 0]
              if shop else [75 / 200, 0, 0, 0])
        if len(v) != self.armg.ARMG_OBS_DIM:
            raise RuntimeError(f'wrong state feature count: {len(v)}')

        features = np.zeros((len(actions), self.armg.ARMG_ACTION_DIM), dtype=np.float32)
        card_idx = 0
        for row_index, (row, action) in enumerate(zip(features, actions)):
            kind = action['kind']
            if kind == 'choose_reward_alternative':
                # Preserve the response's one-score-per-native-action shape;
                # this dummy row is masked before returning the scores.
                continue
            elif kind == 'choose_card':
                action_type, index = 1, card_idx
                cid, upgraded = offered[card_idx]; card_idx += 1
                row[self.armg._CARD_OFF:self.armg._CARD_OFF + self.card_dim] = self.sim.card_features(cid, bool(upgraded), -1)
            elif kind == 'skip': action_type, index = 2, 0
            elif kind in ('buy_card', 'buy_relic', 'buy_potion'):
                category, action_type = {'buy_card': ('cards', 7), 'buy_relic': ('relics', 8), 'buy_potion': ('potions', 9)}[kind]
                index = action['target_shop_index']
                item, ident, upgraded = shop_items[category][index]
                if kind == 'buy_card':
                    row[self.armg._CARD_OFF:self.armg._CARD_OFF + self.card_dim] = self.sim.card_features(ident, bool(upgraded), item['cost'])
                elif kind == 'buy_relic': row[self.armg._RELIC_OFF + ident] = 1
                else: row[self.armg._POTION_OFF + ident] = 1
                row[self.armg._META_OFF + 4] = item['cost'] / 300
            elif kind == 'open_card_removal':
                action_type, index = 10, action['target_deck_index']
                cid, upgraded = cards[index]
                row[self.armg._CARD_OFF:self.armg._CARD_OFF + self.card_dim] = self.sim.card_features(cid, bool(upgraded), -1)
                row[self.armg._META_OFF + 4] = shop['removal_cost'] / 300
            elif kind == 'leave_merchant': action_type, index = 11, 0
            elif kind == 'choose_event_option':
                action_type, index = 12, event.option_indices[row_index]
                if event.relic_indices:
                    row[self.armg._RELIC_OFF + event.relic_indices[index]] = 1
            else:
                action_type, index = 0, by_coord[_coordinate(action['map_coordinate'])]
                row[self.armg._MAP_OFF + types[index]] = 1
                for child in children[index]:
                    ci = by_coord[child]
                    row[self.armg._MAP_OFF + 9 + types[ci]] += 1
                    for grandchild in children[ci]:
                        row[self.armg._MAP_OFF + 18 + types[by_coord[grandchild]]] += 1
                row[self.armg._META_OFF + 2] = coords[index][1] / 6
                row[self.armg._META_OFF + 3] = coords[index][0] / 16
            row[self.armg._ACTION_OFF + action_type] = 1
            row[self.armg._SLOT_OFF + index] = 1
            row[self.armg._META_OFF] = index / 127
        return np.asarray(v, dtype=np.float32), features


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--sts2-root', required=True)
    p.add_argument('--simulator', required=True)
    args = p.parse_args()
    import os
    os.environ['STS2_PRIOR_PYD'] = str(Path(args.simulator).resolve(strict=True))
    sys.path.insert(0, str(Path(args.sts2_root).resolve(strict=True)))
    from deployment import evaluate_battle_root_prior
    from agent import armg
    from agent.common import sim
    import torch
    from deployment.evaluate_armg import load_armg_checkpoint
    torch.set_num_threads(1)
    if (sim.PUBLIC_OBS_VERSION, sim.ACTION_SCHEMA_VERSION, armg.ARMG_FEATURE_VERSION) != (10, 9, 1):
        raise RuntimeError('incompatible simulator feature/action schema')
    model = armg.ArmGScorer().eval()
    payload = load_armg_checkpoint(args.checkpoint, model)
    with open(args.simulator, 'rb') as file:
        actual_hash = hashlib.file_digest(file, 'sha256').hexdigest()
    expected_hash = payload.get('settings', {}).get('simulator_sha256')
    if expected_hash != actual_hash:
        raise RuntimeError('checkpoint and simulator extension hashes differ')
    encoder = Encoder(args.sts2_root, sim, armg)
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id, fingerprint = None, None
        try:
            request = json.loads(line)
            request_id = request['request_id']
            decision = request['decision']
            fingerprint = decision['state_fingerprint']
            if not isinstance(fingerprint, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', fingerprint):
                raise Unsupported('invalid state fingerprint')
            # A single legal choice needs no policy approximation. Validate the
            # engine and identity before accepting the native action.
            build = decision.get('build') or {}
            if (build.get('game_version') != 'v0.111.0' or
                    str(build.get('assembly_sha256', '')).lower() !=
                    '0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9'):
                raise Unsupported('game version or assembly does not match v0.111.0')
            actions = decision.get('legal_actions')
            if isinstance(actions, list) and len(actions) == 1:
                action_id = actions[0].get('action_id') if isinstance(actions[0], dict) else None
                if not isinstance(action_id, str) or not action_id:
                    raise Unsupported('missing or duplicate action ID')
                print(json.dumps({'request_id': request_id, 'status': 'ok',
                    'state_fingerprint': fingerprint, 'action_id': action_id,
                    'scores': [0.0], 'approximate': False,
                    'missing_features': ['single_legal_action_no_model']},
                    ensure_ascii=False, allow_nan=False), flush=True)
                continue
            obs, candidates = encoder.encode(decision)
            with torch.inference_mode():
                scores = model(torch.from_numpy(obs)[None], torch.from_numpy(candidates)[None])[0]
            if not torch.isfinite(scores).all():
                raise RuntimeError('model returned nonfinite scores')
            ignored = [i for i, action in enumerate(actions)
                       if decision['observation']['surface'] == 'card_reward'
                       and action.get('kind') == 'choose_reward_alternative']
            supported = [i for i in range(len(actions)) if i not in ignored]
            if not supported:
                raise Unsupported('no card reward actions can be scored')
            index = max(supported, key=lambda i: float(scores[i]))
            values = scores.tolist()
            for i in ignored:
                values[i] = -1e30  # finite sentinel; not a model logit
            missing = ['simulator_map_node_order', 'boss_encounters',
                       'event_state', 'run_and_relic_counters', 'pending_rewards_and_shop',
                       'deck_card_special_state']
            shop = decision['observation'].get('shop') or {}
            if any(item.get('sold') and not item.get('model_id')
                   for category in ('cards', 'relics', 'potions')
                   for item in shop.get(category, [])):
                missing.append('sold_shop_item_identity')
            missing += [f"ignored_unscored_action:{actions[i]['action_id']}" for i in ignored]
            result = {'request_id': request_id, 'status': 'ok', 'state_fingerprint': fingerprint,
                      'action_id': actions[index]['action_id'],
                      'scores': values, 'approximate': True, 'missing_features': missing}
        except Unsupported as exc:
            result = {'request_id': request_id, 'status': 'unsupported',
                      'state_fingerprint': fingerprint, 'reason': str(exc)}
        except Exception as exc:
            result = {'request_id': request_id, 'status': 'error',
                      'state_fingerprint': fingerprint, 'reason': f'{type(exc).__name__}: {exc}'}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
