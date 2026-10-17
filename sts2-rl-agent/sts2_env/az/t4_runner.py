"""Serial T4 state machine. No work on import; production CLI requires opt-in."""
from pathlib import Path
from dataclasses import asdict
import json
import platform
import numpy as np
import torch
from .config import atomic_json,content_hash,derive_seed,EpisodeLimits
from .network import code_digest
from .self_play import file_digest,CollectionJob
from .t4_run_plan import plan,jobs
from .t4_replay import MixedReplay
from .t4_protocol import network_gate,validate_protocol
from .natural_course import collect_suffix,validate_course
from .entity_transition import collect_entity_episode
from .dynamic_search import plan_dynamic
from .model_factory import create_transformer,save_transformer_checkpoint,load_transformer_checkpoint
from .content import BOSS_CONTENT
from .rewards import V7
from .learner import Learner
from .scenarios import CombatScenario
from .evaluation import evaluate


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def binding(p):
    return dict(plan=p,code_digest=code_digest(),runtime=dict(python=platform.python_version(),
        torch=str(torch.__version__),numpy=np.__version__))


def check_disk(root,required):
    import shutil
    path=Path(root).resolve()
    while not path.exists():path=path.parent
    if shutil.disk_usage(path).free<required:raise RuntimeError('T4 disk reserve exhausted; stopped without changing budgets')


def drive(root,p,backend):
    """Small persistent coordinator; backend methods must be retry-idempotent."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    path=root/'state.json';bound=backend.binding
    if path.exists():
        state=read(path)
        if state['binding']!=bound:raise ValueError('T4 resume binding drift')
        backend.check(state)
    else:
        initial=backend.initialize()
        state=dict(binding=bound,phase='collect',iteration=0,next_job=0,updates_done=0,
            champion=initial,candidate=None,rounds=[],artifacts={initial:backend.digest(initial)})
        atomic_json(path,state)
    while state['phase']!='done':
        if hasattr(backend,'check_space'):backend.check_space()
        iteration=state['iteration']
        if state['phase']=='collect':
            count=p['full_episodes']+p['late_episodes']
            if state['next_job']<count:
                backend.collect(iteration,state['next_job'],state['champion'])
                state['next_job']+=1
            else:state['phase']='train'
        elif state['phase']=='train':
            if state['updates_done']<p['updates']:
                candidate=backend.update(iteration,state['updates_done'],state['champion'],state['candidate'])
                state['candidate']=candidate;state['updates_done']+=1
                state['artifacts'][candidate]=backend.digest(candidate)
            else:state['phase']='evaluate'
        elif state['phase']=='evaluate':
            result,artifact=backend.compare(iteration,state['champion'],state['candidate'])
            state['artifacts'][artifact]=backend.digest(artifact)
            state['rounds'].append(dict(iteration=iteration,champion=state['champion'],
                candidate=state['candidate'],evaluation=artifact,gate=result))
            if result['promote']:state['champion']=state['candidate']
            state['iteration']+=1;state['next_job']=0;state['updates_done']=0;state['candidate']=None
            state['phase']='done' if state['iteration']==p['rounds'] else 'collect'
        else:raise ValueError('Unknown T4 phase')
        atomic_json(path,state)
    backend.check(state)
    return state


class Backend:
    def __init__(self,root,p,protocol,course):
        self.root=Path(root);self.p=p;self.protocol=protocol;self.course=course
        self.binding=binding(p)
        self.replay=MixedReplay(self.root/'replay',self.binding,protocol,course,
                               {'full':p['replay_full_rows'],'late':p['replay_late_rows']})
        self.schedules=[list(jobs(p,protocol,course,i)) for i in range(p['rounds'])]

    def digest(self,path):return file_digest(self.root/path)

    def check_space(self):check_disk(self.root,self.p['disk_reserve_bytes'])

    def check(self,state):
        for path,digest in state['artifacts'].items():
            if self.digest(path)!=digest:raise ValueError('Committed run artifact changed')
        expected={j['identity'] for i,rows in enumerate(self.schedules) for j in rows
                  if i<state['iteration'] or i==state['iteration'] and j['index']<state['next_job']}
        if not expected<=self.replay.manifest['committed'].keys():raise ValueError('State ahead of Replay commit')

    def load(self,path):
        model,payload=load_transformer_checkpoint(self.root/path,self.p['tier'],BOSS_CONTENT,V7)
        if payload['run_config']!=self.p or payload['code_digest']!=self.binding['code_digest']:
            raise ValueError('T4 checkpoint binding mismatch')
        return model,payload

    def initialize(self):
        torch.manual_seed(self.p['seed'])
        model=create_transformer(self.p['tier'],BOSS_CONTENT,V7)
        save_transformer_checkpoint(self.root/'initial.pt',model,'t4-initial',config=self.p)
        return 'initial.pt'

    def collect(self,iteration,index,champion):
        job=self.schedules[iteration][index];identity=job['identity']
        if identity in self.replay.manifest['committed']:
            item=self.replay.read(identity);self.replay.validate(item)
            if item['kind']!=job['kind'] or (job['kind']=='full' and item['recipe']!=job['recipe']):
                # JSON canonical comparison handles tuples from recipe construction.
                if item['kind']!=job['kind'] or content_hash(item['recipe'])!=content_hash(job.get('recipe')):
                    raise ValueError('Retry recipe mismatch')
            if job['kind']=='late' and item['record']['start']!=job['start']:raise ValueError('Retry start mismatch')
            return
        model,payload=self.load(champion)
        if job['kind']=='full':
            spec=CollectionJob(str(index),iteration,self.p['seed'],job['recipe'],str(self.root/champion),
                self.digest(champion),payload['model_version'],str(self.root/'errors'),self.p['simulations'],
                EpisodeLimits(max_turns=self.p['max_turns'],max_decisions=self.p['max_decisions']),V7,self.p['search'])
            record=collect_entity_episode(spec,model)
        else:
            def decide(info):
                return plan_dynamic(info,model,model_version=payload['model_version'],budget=self.p['simulations'],
                    search_version=self.p['search'],max_depth=self.p['max_depth'],training=True,
                    c_puct=self.p['c_puct'],epsilon=self.p['training_epsilon'],alpha=self.p['training_alpha'],
                    temperature=1 if info.history.decisions-len(job['start']['prefix'])<self.p['temperature_steps'] else 0,
                    search_seed=derive_seed(self.p['seed'],iteration,index,f'late-{info.history.decisions}'))
            record=collect_suffix(job['start'],decide,payload['model_version'])
        self.replay.commit(identity,job['kind'],record,job.get('recipe'))

    def update(self,iteration,index,champion,previous):
        model,payload=self.load(previous or champion)
        learner=Learner(model,self.p['learning_rate'],self.p['weight_decay'])
        if previous:
            saved=payload['training_state']
            if saved['updates']!=index:raise ValueError('Optimizer update boundary mismatch')
            learner.optimizer.load_state_dict(saved['optimizer']);learner.updates=index
        rng=np.random.default_rng(derive_seed(self.p['seed'],iteration,index,'mixed-batch'))
        samples=self.replay.sample(rng,self.p['batch_full'],self.p['batch_late'])
        torch.manual_seed(derive_seed(self.p['seed'],iteration,index,'update-torch'))
        metrics=learner.update(samples,self.p['microbatch'])
        path=f'round-{iteration}/update-{index+1}.pt'
        save_transformer_checkpoint(self.root/path,learner.model,f't4-{iteration}-{index+1}',config=self.p,
            statistics=metrics,iteration=iteration,
            training_state=dict(optimizer=learner.optimizer.state_dict(),updates=learner.updates))
        return path

    def evaluate_rows(self,checkpoint,records):
        model,payload=self.load(checkpoint);rows=[]
        for index,record in enumerate(records):
            recipe=CombatScenario.from_dict(record)
            key=content_hash([self.binding,self.digest(checkpoint),record,index])
            path=self.root/'evaluation-cache'/f'{key}.json'
            if path.exists():
                saved=read(path)
                if saved['key']!=key or saved['sha256']!=content_hash(saved['row']):raise ValueError('Evaluation cache corruption')
                row=saved['row']
            else:
                row=evaluate(model,payload['model_version'],[recipe],simulations=0,
                    start_index=index,seed=1729,error_dir=str(self.root/'errors'),
                    reward_version=V7,search_version=self.p['search'])[0]
                atomic_json(path,dict(key=key,row=row,sha256=content_hash(row)))
            if (row['scenario_id']!=recipe.scenario_id or row['initial_hp']!=recipe.player_hp
                    or row['family_id']!=recipe.family_id or row['encounter_id']!=recipe.encounter_id):
                raise ValueError('Evaluation recipe mismatch')
            rows.append(row)
        return rows

    def compare(self,iteration,champion,candidate):
        paired=[self.evaluate_rows(checkpoint,self.protocol['groups']['validation'])
                for checkpoint in (champion,candidate)]
        gate=network_gate(self.protocol,*paired,mode='network')
        artifact=f'round-{iteration}/evaluation.json'
        atomic_json(self.root/artifact,dict(initial=paired[0],final=paired[1],gate=gate,
            initial_checkpoint=champion,final_checkpoint=candidate,scope='original-battle-network'))
        return gate,artifact


def audit(root,p,protocol,course):
    backend=Backend(root,p,protocol,course);state=read(Path(root)/'state.json')
    if state['binding']!=backend.binding or state['phase']!='done' or state['iteration']!=p['rounds']:
        raise ValueError('Incomplete or incompatible T4 run')
    backend.check(state)
    expected={j['identity'] for rows in backend.schedules for j in rows}
    if set(backend.replay.manifest['committed'])!=expected:raise ValueError('Wrong committed episode population')
    if len(state['rounds'])!=p['rounds']:raise ValueError('Missing round report')
    counts={'full':0,'late':0};timeouts={'full':0,'late':0};rows={'full':0,'late':0}
    for identity in sorted(expected):
        item=backend.replay.read(identity);backend.replay.validate(item)
        kind=item['kind'];counts[kind]+=1;rows[kind]+=len(item['record']['rows'])
        timeouts[kind]+=item['record']['outcome']['termination_reason']=='time_limit'
    for schedule in backend.schedules:
        for job in schedule:
            item=backend.replay.read(job['identity'])
            if item['kind']!=job['kind'] or (job['kind']=='full' and content_hash(item['recipe'])!=content_hash(job['recipe'])):
                raise ValueError('Committed recipe differs from frozen schedule')
            if job['kind']=='late' and item['record']['start']!=job['start']:raise ValueError('Committed late start differs')
    evaluations={};champion='initial.pt'
    for iteration,record in enumerate(state['rounds']):
        expected_candidate=f"round-{iteration}/update-{p['updates']}.pt"
        if record['iteration']!=iteration or record['champion']!=champion or record['candidate']!=expected_candidate:
            raise ValueError('Broken champion/candidate chain')
        for update in range(1,p['updates']+1):
            path=f'round-{iteration}/update-{update}.pt'
            if path not in state['artifacts']:raise ValueError('Missing committed optimizer checkpoint')
            payload=torch.load(Path(root)/path,map_location='cpu',weights_only=True)
            if (payload['training_state']['updates']!=update or payload['run_config']!=p
                    or payload['code_digest']!=backend.binding['code_digest']):
                raise ValueError('Optimizer checkpoint evidence mismatch')
        result=read(Path(root)/record['evaluation'])
        if result['initial_checkpoint']!=champion or result['final_checkpoint']!=expected_candidate:
            raise ValueError('Evaluation checkpoint pair mismatch')
        gate=network_gate(protocol,result['initial'],result['final'],mode='network')
        if gate!=record['gate'] or gate!=result['gate']:raise ValueError('Gate mismatch')
        evaluations[champion]=result['initial'];evaluations[expected_candidate]=result['final']
        if gate['promote']:champion=expected_candidate
    if state['champion']!=champion:raise ValueError('Final champion mismatch')
    final_gate=network_gate(protocol,evaluations['initial.pt'],evaluations[champion],mode='network')
    if any((Path(root)/'errors').rglob('*.json')):raise ValueError('Run contains error evidence')
    return dict(engineering_passed=True,episodes=counts,decisions=rows,timeouts=timeouts,
                updates=p['updates']*p['rounds'],network_gates=[r['gate'] for r in state['rounds']],
                all_network_gates_passed=all(r['gate']['promote'] for r in state['rounds']),
                final_network_gate=final_gate,network_utility_accepted=final_gate['promote'],
                heldout_evaluated=False,binding=backend.binding)


def finalize_holdouts(root,plans,protocol,course):
    """All champions freeze together before any heldout combat; restart uses cache."""
    from .evaluation import promotion_gate,summarize
    root=Path(root);frozen={}
    for seed in (42,43):
        folder=root/f'seed-{seed}';p=plans[str(seed)]
        audit(folder,p,protocol,course)
        state=read(folder/'state.json')
        frozen[str(seed)]=dict(champion=state['champion'],champion_sha256=file_digest(folder/state['champion']),
            initial_sha256=file_digest(folder/'initial.pt'),binding=binding(p))
    path=root/'frozen_champions.json'
    if path.exists() and read(path)!=frozen:raise ValueError('Frozen final champions changed')
    atomic_json(path,frozen)
    artifacts={}
    for seed in (42,43):
        folder=root/f'seed-{seed}';backend=Backend(folder,plans[str(seed)],protocol,course)
        for group in ('unseen_combination','unseen_id'):
            records=protocol['groups'][group]
            initial=backend.evaluate_rows('initial.pt',records)
            final=backend.evaluate_rows(frozen[str(seed)]['champion'],records)
            # Reuse strict V7 fact checking, but these 24-row groups cannot promote.
            checked=promotion_gate(initial,final,required_count=256,reward_version=V7,criterion='utility-only-v1')
            if not checked['clean']:raise ValueError('Heldout execution errors; raw cases retained in cache')
            artifact=folder/f'heldout-{group}.json'
            atomic_json(artifact,dict(scope='frozen-final-network-diagnostic',initial=initial,final=final,
                initial_summary=summarize(initial),final_summary=summarize(final),
                mean_utility_difference=checked['mean_utility_difference'],quality_claim=False,
                frozen_champions_sha256=content_hash(frozen),protocol_sha256=protocol['sha256']))
            artifacts[str(artifact.relative_to(root))]=file_digest(artifact)
    evidence=dict(frozen_champions_sha256=content_hash(frozen),artifacts=artifacts,
                  network_battles=192,quality_claim=False,used_for_promotion=False)
    atomic_json(root/'heldout_evidence.json',evidence)
    return evidence


def audit_holdouts(root,plans,protocol,course):
    from .evaluation import promotion_gate,summarize
    root=Path(root);frozen=read(root/'frozen_champions.json');evidence=read(root/'heldout_evidence.json')
    expected_files={f'seed-{s}/heldout-{g}.json' for s in (42,43) for g in ('unseen_combination','unseen_id')}
    if ({p.replace('\\','/') for p in evidence['artifacts']}!=expected_files
            or evidence['frozen_champions_sha256']!=content_hash(frozen)
            or evidence['quality_claim'] or evidence['used_for_promotion'] or evidence['network_battles']!=192):
        raise ValueError('Incomplete final heldout evidence')
    for path,digest in evidence['artifacts'].items():
        if file_digest(root/path)!=digest:raise ValueError('Heldout artifact changed')
    gates={}
    for seed in (42,43):
        folder=root/f'seed-{seed}';p=plans[str(seed)];result=audit(folder,p,protocol,course)
        state=read(folder/'state.json');f=frozen[str(seed)]
        if (f['binding']!=binding(p) or f['champion']!=state['champion']
                or f['champion_sha256']!=file_digest(folder/state['champion'])
                or f['initial_sha256']!=file_digest(folder/'initial.pt')):
            raise ValueError('Final checkpoint freeze mismatch')
        gates[str(seed)]=result['final_network_gate']
        for group in ('unseen_combination','unseen_id'):
            data=read(folder/f'heldout-{group}.json');ids=[r['scenario_id'] for r in protocol['groups'][group]]
            if (data['frozen_champions_sha256']!=content_hash(frozen) or data['protocol_sha256']!=protocol['sha256']
                    or data['quality_claim'] or any([r['scenario_id'] for r in data[role]]!=ids for role in ('initial','final'))):
                raise ValueError('Heldout population/binding mismatch')
            check=promotion_gate(data['initial'],data['final'],required_count=256,reward_version=V7,criterion='utility-only-v1')
            if (not check['clean'] or data['mean_utility_difference']!=check['mean_utility_difference']
                    or data['initial_summary']!=summarize(data['initial']) or data['final_summary']!=summarize(data['final'])):
                raise ValueError('Heldout facts/summary mismatch')
    return dict(engineering_passed=True,heldout_network_battles=192,final_network_gates=gates,
                network_utility_accepted=all(g['promote'] for g in gates.values()),quality_claim=False)
