"""Validate the target DLL identity, complete fixture coverage, and key outcomes."""
from pathlib import Path
import hashlib
import json
here=Path(__file__).resolve().parent
r=json.loads((here/'results.json').read_text())
invocation=json.loads((here/'invocation.json').read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert r['status']=='completed' and len(r['results'])==56
assert r['gameAssemblySha256']=='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
assert r['userDirectory'].endswith('SlayTheModelNativeRound4Step1CardAudit20261031')
assert invocation['exit_code']==0 and not invocation['timed_out']
assert invocation['harness_sha256']==digest(here/'AuditWorker.cs')
host='.godot/mono/temp/bin/ExportRelease/SimulatorAudit.dll'
assert digest(here/host)==digest(here/'SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64/SimulatorAudit.dll')
for f in r['results']:
 t=f['test']
 if t=='stack':
  crimson=f['id']=='CRIMSON_MANTLE';n=f['count'];up=f['upgraded']
  amount=((10 if up else 7) if crimson else (9 if up else 6))*n
  key='crimson' if crimson else 'inferno'
  assert (f['before'][key+'Self'],f['before'][key+'Amount'])==(n,amount)
  assert (f['first']['hp'],f['second']['hp'])==(80-n,80-2*n)
  assert (f['first']['strength'],f['second']['strength'])==(2,4)
 elif t=='modifier':
  s=f['after'];n=f['count'];m=f['modifier']
  if m=='tungsten_buffer' and n==1: assert (s['hp'],s['buffer'],s['strength'])==(80,1,0)
  if m=='revive':assert s['hp']==40 and s['lizardUsed'] and s['strength']==0 and s['damage']==[0,0]
  if m=='lethal':assert s['hp']==0 and s['block']==0 and s['damage']==[0,0]
 elif t=='order':
  s=f['after']
  if f['modifier']=='buffer':assert s['hp']==(79 if f['infernoFirst'] else 77)
  if f['modifier']=='tungsten_buffer':assert (s['hp'],s['buffer'],s['damage'])==(80,0,[0,0])
  if f['modifier']=='revive':assert s['hp']==(39 if f['infernoFirst'] else 37) and s['strength']==2 and s['damage']==[18,18]
 elif t=='damage_trigger':
  triggered=f['mode']=='own_damage'
  assert f['after']['strength']==(2 if triggered else 0)
  assert f['after']['damage']==([12,12] if triggered else [0,0])
 elif t in ('direct_apply','remove_reapply'):
  key='crimson' if f['id']=='CRIMSON_MANTLE' else 'inferno'
  assert (f['after'][key+'Self'],f['after'][key+'Amount'])==(0,13)
 else:raise AssertionError(t)
summary={'status':'passed','fixtures':len(r['results']),'game_assembly_sha256':r['gameAssemblySha256'],
 'harness_sha256':digest(here/'AuditWorker.cs'),'host_assembly_sha256':digest(here/host),'results_sha256':digest(here/'results.json'),
 'scope':'Controlled two-power OnPlay/replay, turn hooks, side gating, damage reduction and Lizard Tail fixtures. Not full-run or general hook-order parity.',
 'known_boundary':'Native final death clears all powers; C++ retains its existing terminal state representation. C++ comparisons check lethal effects/outcome and skip terminal power teardown.'}
(here/'validation.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
