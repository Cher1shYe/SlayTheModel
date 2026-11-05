"""Strictly reload and inspect artifacts; does not collect games or train."""
from pathlib import Path
import hashlib
import json
import sys
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from agent.armg import ArmGScorer, ARMG_OBS_DIM, ARMG_ACTION_DIM
from agent.engine_identity import current_engine_contract, sha256_file
from agent.nets import read_checkpoint
from deployment.evaluate_armg import load_armg_checkpoint
from agent.combat_dagger import CombatPolicy, load_combat_checkpoint

out = ROOT/'validation/round2/puct-training-smoke-fixed'
initial_path = ROOT/'validation/weights/armg-native-port-v2-init.pt'
original_path = ROOT/'validation/weights/armg-native-port-init.pt'
initial = read_checkpoint(initial_path)
model = ArmGScorer().eval()
final = load_armg_checkpoint(out/'latest.pt',model)
combat = load_combat_checkpoint(out/'combat_policy.pt',CombatPolicy().eval())
progress = json.loads((out/'progress.json').read_text())
metrics = [json.loads(line) for line in (out/'metrics.jsonl').read_text().splitlines()]
assert progress['state']=='completed' and final['progress']['games']==2
assert final['progress']['completed']==2 and final['progress']['training_games_in_target_environment']==2
assert metrics[-1]['validation']['completed']==1
assert all(metrics[-1][kind]['truncated']==metrics[-1][kind]['errors']==0 for kind in ('train','validation'))
assert final['settings']['simulator_sha256']==current_engine_contract()['simulator_sha256']
assert final['settings']['combat_prior_mode']=='random' and final['settings']['site_prior_mode']=='disabled'
assert combat['progress']['total_games']==0
assert initial['migration']['training_games_in_target_environment']==0
assert sha256_file(original_path)=='63c487f5bdef291cf11f06c93dd7b3f8497c1e712da2c71dbc95e944c7bd8f95'
changes = {k:float((value-initial['state_dict'][k]).abs().max()) for k,value in final['state_dict'].items()}
assert any(value>0 for value in changes.values())
steps = [float(state['step']) for state in final['optimizer_state_dict']['state'].values()]
assert steps and all(value==1 for value in steps)
assert all(torch.isfinite(value).all().item() for value in final['state_dict'].values())
with torch.inference_mode():
    assert torch.isfinite(model(torch.zeros(1,ARMG_OBS_DIM),torch.zeros(1,2,ARMG_ACTION_DIM))).all()
report = {'status':'passed','engine_contract':current_engine_contract(),
    'initial_checkpoint':str(initial_path),'initial_sha256':sha256_file(initial_path),
    'final_checkpoint':str(out/'latest.pt'),'final_sha256':sha256_file(out/'latest.pt'),
    'strict_model_reload':True,'strict_combat_prior_reload':True,'source_weight_unchanged':True,
    'training_games':2,'validation_games_not_training':1,
    'training_seed_base':final['settings']['training_seed_base'],
    'validation_seed_base':final['settings']['validation_seed_base'],
    'max_abs_parameter_change':changes,'optimizer_steps':steps,
    'initial_target_environment_games':0,'final_target_environment_games':2,
    'metrics':metrics[-1],
    'conditions':{'simulations_per_nonforced_root':8,'floor_increment':0,
        'combat_prior':'frozen random untrained network','website_prior':'disabled',
        'information':'oracle','reproduces_colleague_training_configuration':False},
    'prior_failure':{'directory':'validation/round2/puct-training-smoke','training_games':0,
        'cause':'old combat classification guard required observation schema 10',
        'fix':'schema11 public native combat prefix validated, elite/boss mutual exclusion checked'},
    'limits':['A pipeline smoke test, not a strength estimate or native parity proof.',
        'Two training games ended in death; validation reached first boss floor and died.',
        'The real original trained combat prior and website snapshot remain unavailable.']}
(ROOT/'validation/round2/puct-training-smoke-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ('status','training_games','validation_games_not_training','strict_model_reload','optimizer_steps','max_abs_parameter_change')},indent=2))
