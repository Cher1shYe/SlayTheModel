"""Append the target DLL's missing card vocabulary, preserving all old IDs.
Run before gen_cards.py; source oracle is pinned and kept as immutable evidence.
"""
from pathlib import Path
import json, re
root=Path(__file__).resolve().parents[1]
metadata=root.parent/'native-round4-step2-card-reward-fixtures/content-metadata.json'
source=json.loads(metadata.read_text())
assert source['gameAssemblySha256']=='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
cards=json.loads((root/'content/cards.json').read_text())
aliases={'SLOTH_STATUS':'SLOTH'}
existing={aliases.get(c['id'],c['id'].removesuffix('_CARD')):c for c in cards}
def snake(s):
 return re.sub(r'([a-z0-9])([A-Z])',r'\1_\2',re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1_\2',s)).lower()
# Freeze the current legacy variable layout before adding any new keys.
varfile=root/'content/card_var_ids.json'
if not varfile.exists():
 text=(root/'include/sts2/cards_generated.inc').read_text()
 body=text.split('enum class VarId : std::uint8_t {',1)[1].split('};',1)[0]
 varfile.write_text(json.dumps([v.strip().lower() for v in body.split(',') if v.strip()!='COUNT' and v.strip()],indent=2)+'\n')
rank={};pool_by_id={}
for group, pool in enumerate(source['pools']):
 for order,cid in enumerate(pool['cards']):rank[cid]=group*1000+order;pool_by_id[cid]=pool['id'].removesuffix('_CARD_POOL').lower()
added=[]
for record in source['results']:
 native=record['id']
 if record['pool']=='DEPRECATED_CARD_POOL' or record['type']=='None':continue
 current=existing.get(native)
 if current is None:
  current={'id':('NULL_CARD' if native=='NULL' else native),'pool':pool_by_id[native],'title':re.sub(r'(?<!^)(?=[A-Z][a-z])',' ',record['className']),
           'description':'','variants':{},'flags':{},'effect_vars':{}}
  cards.append(current);existing[native]=current;added.append(native)
 # Preserve old values/legacy variable aliases and merge exact canonical vars.
 current['native_id']=native;current['native_class']=record['className']
 current['native_pool_order']=rank[native]
 current['pool']=pool_by_id[native]
 current['max_upgrade_level']=record['maxUpgradeLevel']
 current['multiplayer_only']=record['multiplayerConstraint']=='MultiplayerOnly'
 current['can_be_generated_in_combat']=record['generated']
 current['type']=record['type'].upper();current['rarity']=record['rarity'].upper()
 current['target']={'AnyEnemy':'ANY_ENEMY','AllEnemies':'ALL_ENEMIES','AnyAlly':'ANY_ALLY','AllAllies':'ALL_ALLIES','RandomEnemy':'RANDOM_ENEMY','None':'NONE','Self':'SELF'}[record['target']]
 current['tags']=[s.upper() for s in record['tags']]
 for index,key in enumerate(('base','upgraded')):
  variant=record['variants'][index];v=current['variants'].setdefault(key,{})
  v.update(cost=variant['cost'],x_cost=variant['xCost'],star_cost=variant['starCost'],star_cost_x=variant['starCostX'],keywords=[s.lower() for s in variant['keywords']],
           base_damage=variant['vars'].get('Damage'),base_block=variant['vars'].get('Block'))
  for flag,word in [('exhausts','exhaust'),('ethereal','ethereal'),('retain','retain'),('innate','innate'),('unplayable','unplayable')]:v[flag]=word in v['keywords']
  effects=v.setdefault('effect_vars',{})
  for name,value in variant['vars'].items():effects[snake(name)]=value
 base=current['variants']['base']
 for key in ('cost','x_cost','star_cost','star_cost_x','keywords','base_damage','base_block','effect_vars'):current[key]=base[key]
 current['flags']={flag:base[flag] for flag in ('exhausts','ethereal','retain','innate','unplayable')}
# Grapple is retained for ID compatibility, but is absent from native pools.
(root/'content/cards.json').write_text(json.dumps(cards,indent=2,ensure_ascii=False)+'\n')
ids=json.loads(varfile.read_text());extras=sorted({k for c in cards for v in c['variants'].values() for k in v['effect_vars']}-set(ids));ids+=extras
varfile.write_text(json.dumps(ids,indent=2)+'\n')
(root/'content/native_card_pools.json').write_text(json.dumps(source['pools'],indent=2)+'\n')
print(json.dumps({'added_cards':len(added),'cards':len(cards),'vars':len(ids),'new_ids':added}))
