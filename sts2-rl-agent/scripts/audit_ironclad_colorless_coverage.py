"""Inventory only. Never loads a model, experiment split or heldout manifest."""
import ast
import inspect
import json
from pathlib import Path
import re
import sys
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sts2_env.core.card_pools import CardPoolId, CHARACTER_CARD_POOLS_BY_ID, COLORLESS_CARD_POOL
from sts2_env.cards.factory import _factory_registry, create_card
from sts2_env.cards.registry import _CARD_EFFECTS
from sts2_env.cards import registry as card_registry
from sts2_env.az.simple_cards import FACTORIES as SIMPLE_FACTORIES
from sts2_env.az.content_expansion import FACTORIES, POWER_FACTORIES, CODEC
from sts2_env.az.all_cards import ALLY_ONLY, ALLY_REQUIRED, FACTORIES as ALL_FACTORIES, OUT_OF_COMBAT
from sts2_env.az.boss_cards import CODEC as OLD_CODEC
from sts2_env.az.expanded_mechanics import describe_card
from sts2_env.az.config import content_hash, atomic_json
from sts2_env.az.content import EXPANSION_CONTENT
from sts2_env.az.foundation import FACTORIES as FOUNDATION_FACTORIES
from sts2_env.az.extended_choices import FACTORIES as CHOICE_FACTORIES
from sts2_env.az.execution import FACTORIES as EXECUTION_FACTORIES
from sts2_env.az.generation_contract import DEFERRED

# Batch-5 deferred tokens and the documented single-player reason.  These stay
# outside FACTORIES so the admission path refuses them.
BATCH5_DEFERRED = {
    'ALCHEMIZE': 'potions are outside the combat scope (in-combat potion inventory)',
    'HIDDEN_GEM': 'random hidden draw-pile card identity mutation has no public face contract',
}
BATCH5_NOTES = {
    'ALLY_REQUIRED': 'native ANY_ALLY effect needs another player; unplayable in single-player',
    'ALLY_ONLY': 'native ALL_ALLIES effect targets teammates only; playable no-op in single-player',
    'OUT_OF_COMBAT': 'in-combat damage only; gold/potion reward is run state outside this scope',
    'RETURN': 'returns to hand before the next hand draw',
}


def inventory():
    registry = _factory_registry()
    rows = []
    for pool, ids in [('Ironclad', CHARACTER_CARD_POOLS_BY_ID[CardPoolId.IRONCLAD]),
                      ('Colorless', COLORLESS_CARD_POOL)]:
        for cid in ids:
            c = create_card(cid)
            effect = _CARD_EFFECTS.get(cid)
            source = inspect.getsource(effect) if effect else ''
            supported = cid.name in CODEC.factories
            hooks = {name: content_hash(inspect.getsource(table[cid]))
                for name, table in vars(card_registry).items()
                if name.startswith('_CARD_') and name != '_CARD_EFFECTS'
                and isinstance(table, dict) and cid in table and callable(table[cid])}
            dependencies = sorted(set(re.findall(r'PowerId\.([A-Z_]+)', source)))
            calls = sorted({n.func.attr for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == 'combat'}) if source else []
            # Hints are direct source symbols, not an inferred semantic description.
            blockers = [] if supported else [f'mechanic_descriptor/cards/{cid.name}',
                'public_state_and_action_admission', 'particle_reconstruction_and_interaction_parity']
            if not supported and hooks: blockers += ['registered_hooks/' + ','.join(sorted(hooks))]
            if cid.name in DEFERRED:blockers.insert(0,'scope_deferred/'+DEFERRED[cid.name])
            if cid.name in BATCH5_DEFERRED:blockers.insert(0,'scope_deferred/'+BATCH5_DEFERRED[cid.name])
            if not supported and dependencies: blockers += ['power_dependencies/' + ','.join(dependencies)]
            if not supported and (c.star_cost or c.has_star_cost_x): blockers += ['star_resource']
            if not supported and c.target_type.name in ('ANY_ALLY', 'ANY_PLAYER', 'ALL_ALLIES'):
                blockers += ['multiplayer_target_contract']
            notes = []
            if cid.name in ALLY_REQUIRED: notes.append('single-player-unplayable/' + BATCH5_NOTES['ALLY_REQUIRED'])
            if cid.name in ALLY_ONLY: notes.append('single-player-noop/' + BATCH5_NOTES['ALLY_ONLY'])
            if cid.name in OUT_OF_COMBAT: notes.append('out-of-combat-reward/' + BATCH5_NOTES['OUT_OF_COMBAT'])
            if cid.name in ('BOLAS', 'THRUMMING_HATCHET'): notes.append('return-to-hand/' + BATCH5_NOTES['RETURN'])
            variants = {}
            for suffix in ('', '+'):
                token = cid.name + suffix
                if token in CODEC.factories:
                    d = describe_card(token)
                    variants[token] = content_hash(asdict(d))
            rows.append(dict(id=cid.name, pool=pool,
                engine='registered' if cid in registry and effect else 'missing',
                observation='admitted' if supported else 'blocked',
                action='admitted' if supported else 'blocked',
                network='admitted' if supported else 'blocked',
                belief_search='admitted' if supported else 'blocked',
                tests='new-batch-parity' if cid.name in FACTORIES else 'existing-g23e' if supported else 'native-only-unreviewed',
                batch='batch5-v5' if cid.name in ALL_FACTORIES else 'foundation-v4' if cid.name in (*FOUNDATION_FACTORIES,*CHOICE_FACTORIES,*EXECUTION_FACTORIES) else 'simple-v3' if cid.name in SIMPLE_FACTORIES else 'powers-v2' if cid.name in POWER_FACTORIES else 'batch1-v1' if cid.name in FACTORIES else 'existing' if supported else 'pending',
                native_source=f'{Path(inspect.getsourcefile(effect)).relative_to(ROOT).as_posix()}:{inspect.getsourcelines(effect)[1]}' if effect else None,
                registered_hook_source_hashes=hooks, effect_source_sha256=content_hash(source), keywords=sorted(c.keywords),
                direct_power_symbols=dependencies, direct_combat_calls=calls,
                effect_variables=sorted(c.effect_vars), descriptor_hashes=variants, blockers=blockers, notes=notes))
    return dict(version='ironclad-colorless-coverage-v5', content=EXPANSION_CONTENT,
        scope='87 Ironclad + 64 Colorless IDs from native card pools; upgrades listed separately',
        status_meaning='registered is not engine parity; admitted is limited to documented single-player dependencies',
        original_admitted=sum(r['id'] in OLD_CODEC.factories for r in rows),
        admitted=sum(r['network']=='admitted' for r in rows), total=len(rows),
        pending=sum(r['network']=='blocked' for r in rows), rows=rows)


def main():
    result = inventory()
    atomic_json(ROOT/'docs/ironclad_colorless_coverage.json', result)
    lines = ['# 战士与无色牌覆盖清单', '',
        f"范围：151 个 ID（战士 87、无色 64）。当前接通 {result['admitted']}，待接通 {result['pending']}。", '',
        'engine 的 registered 仅表示原生工厂及效果函数存在，不等于完整机制正确性。',
        '接通仅限单人 Ironclad、无遗物药水、既有十个遭遇；本次未运行训练或最终留出。',
        'batch5-v5 中：多人牌在单人无合法目标（ALLY 目标牌不可出，ALL_ALLIES 牌可出但无队友效果）；',
        '`notes` 列写明每张牌的单人语义，不允许用“已接通”掩盖无效果。',
        '逐层状态、升级版描述摘要与源码依赖提示见同名 JSON；依赖提示不是机制实现。', '',
        '| 牌池 | ID | 批次 | 六链路状态 | 单人语义提示 | 阻塞路径／直接能力依赖 |',
        '|---|---|---|---|---|---|']
    for r in result['rows']:
        state = 'engine 注册；其余已接通' if r['network']=='admitted' else 'engine 注册；其余待审计'
        lines.append(f"| {r['pool']} | {r['id']} | {r['batch']} | {state} | {'; '.join(r['notes']) or '—'} | {'; '.join(r['blockers']) or '—'} |")
    (ROOT/'docs/IRONCLAD_COLORLESS_COVERAGE.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}, ensure_ascii=False))


if __name__ == '__main__': main()
