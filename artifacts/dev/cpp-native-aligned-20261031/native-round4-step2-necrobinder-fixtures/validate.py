from pathlib import Path
import hashlib,json,collections
p=Path(__file__).resolve().parent;r=json.loads((p/'results.json').read_text());inv=json.loads((p/'invocation.json').read_text())
def h(x):return hashlib.sha256(x.read_bytes()).hexdigest()
assert r['status']=='completed'
assert r['gameAssemblySha256']=='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'
assert r['userDirectory'].endswith('SlayTheModelNativeRound4Step2NecrobinderAudit20261031')
assert inv['exit_code']==0 and not inv['timed_out'] and inv['harness_sha256']==h(p/'AuditWorker.cs')
assert collections.Counter(x['test']for x in r['results'])=={'card':184,'no_single_player_target':2,'mechanism':12}
assert all(x['id']=='SOULBOUND'for x in r['results']if x['test']=='no_single_player_target')
host=p/'.godot/mono/temp/bin/ExportRelease/SimulatorAudit.dll'
assert h(host)==h(p/'SimulatorAudit.app/Contents/Resources/data_SimulatorAudit_macos_arm64/SimulatorAudit.dll')
s={'status':'native-fixtures-validated','fixtures':198,'executed_card_fixtures':184,'single_player_no_ally_target':2,'mechanisms':12,'game_assembly_sha256':r['gameAssemblySha256'],'harness_sha256':h(p/'AuditWorker.cs'),'host_assembly_sha256':h(host),'results_sha256':h(p/'results.json'),'scope':'Controlled native base/upgraded cards and Osty/Doom/Soul. C++ differential result is separately recorded; no full-run claim.'}
(p/'validation.json').write_text(json.dumps(s,indent=2)+'\n');print(json.dumps(s,indent=2))
