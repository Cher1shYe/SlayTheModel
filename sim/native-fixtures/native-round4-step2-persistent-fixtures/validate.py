from pathlib import Path
import hashlib,json
p=Path(__file__).resolve().parent;r=json.loads((p/'results.json').read_text());inv=json.loads((p/'invocation.json').read_text())
def h(path):return hashlib.sha256(path.read_bytes()).hexdigest()
assert r['status']=='completed' and len(r['results'])==18
assert r['gameAssemblySha256']=='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
assert r['userDirectory'].endswith('SlayTheModelNativeRound4Step2PersistentAudit20261031')
assert inv['exit_code']==0 and not inv['timed_out'] and inv['harness_sha256']==h(p/'AuditWorker.cs')
host=p/'.godot/mono/temp/bin/ExportRelease/SimulatorAudit.dll';assert h(host)==h(p/'SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64/SimulatorAudit.dll')
for f in r['results']:
 t=f['test']
 if t=='bone_tea':
  assert f['left']==0 and f['second'][-1]['upgraded'] is False
  assert all(c['upgraded']==(not f['startsUsed'] and c['id'] not in ('WOUND','BYRDONIS_EGG')) for c in f['first'])
 elif t=='bone_initial':
  assert f['left']==0 and all(not c['upgraded'] for c in f['deck'])
 elif t=='fake_tea':assert (f['first'],f['second'],f['armed'],f['consumed'])==(3+int(f['rests']>0),3,f['rests']>0,True)
 elif t=='byrd_transform':
  assert f['petCount']==1 and f['petIds']==['BYRDPIP'] and f['hasEventPet']
  assert f['nicheDelta']==0 and f['transformDelta']==0
  assert [c['id'] for c in f['deck']]==['BASH','DEFEND_IRONCLAD']+['BYRD_SWOOP']*(4 if f['hooks']=='bing' else 2)
  assert all(c['originalIndex']==-1 for c in f['deck'][2:])
  assert all(c['upgraded']==(f['hooks']=='molten') for c in f['deck'][2:])
  assert all(c['id']=='BYRD_SWOOP' and c['originalIndex']==-1 and not c['upgraded'] for pile in ('draw','discard','exhaust') for c in f[pile])
  if f['hooks']=='fresnel_lucky_book':assert (f['hp'],f['goldDelta'],f['bookCount'])==(50,30,5)
 elif t=='byrd_attack':assert sum(f['damage'])==(21 if f['upgraded'] else 17) and f['petCount']==int(f['pet'])
 else:raise AssertionError(t)
summary={'status':'passed','fixtures':18,'game_assembly_sha256':r['gameAssemblySha256'],'harness_sha256':h(p/'AuditWorker.cs'),'host_assembly_sha256':h(host),'results_sha256':h(p/'results.json'),'scope':'Controlled BoneTea initial hand and saved uses; FakeTea rest arming and one-time energy; Byrdpip full deck/combat egg transforms, card acquisition hooks, skin private RNG, summoned pet and ByrdSwoop player attack. Not whole-run or all turn-start hook-order parity.'}
(p/'validation.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
