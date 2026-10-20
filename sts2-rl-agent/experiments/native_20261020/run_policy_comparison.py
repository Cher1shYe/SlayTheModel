"""Two pure-network argmax evaluations; no MCTS, strict and resumable."""
from pathlib import Path
import sys,json,hashlib,threading,traceback,os,statistics
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
B=Path(__file__).resolve().parent
SOURCE=B.parent
sys.path.insert(0,str(SOURCE/'python'))
from sts2_env.az.config import atomic_json,content_hash
from sts2_env.az.native_generic_backend import NativeBackend
from sts2_env.az.native_generic import validate_raw,raw_leaf_settings
from sts2_env.az.all_runner import paired_gain

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
class Backend(NativeBackend):
    def raw_validator(self,r):
        if r['arm']!='policy' or raw_leaf_settings(r)!=('learned',1.):
            raise ValueError('Expected pure-network policy evaluation')
        validate_raw(r,allow_validation_cutoff=True)
        if any(s['simulations']!=0 or s['leafDiagnostics']['nodePolicyCalls']!=0 for s in r['steps']):
            raise ValueError('Pure-network evaluation unexpectedly used search')

def summarize(raws):
    steps=[s for r in raws for s in r['steps']]
    return dict(fights=len(raws),wins=sum(r['outcome']['won'] for r in raws),
        win_rate=sum(r['outcome']['won'] for r in raws)/len(raws),
        mean_utility=statistics.mean(r['outcome']['reward'] for r in raws),
        deaths=sum(r['outcome'].get('terminationReason')=='death' for r in raws),
        truncated=sum(not r['complete'] for r in raws),decisions=len(steps),
        forced_decisions=sum(s['forced'] for s in steps),
        simulations=sum(s['simulations'] for s in steps),
        mean_episode_wall_seconds=statistics.mean(r['wallSeconds'] for r in raws))


def main():
    import msvcrt
    run_lock=(B/'runner.lock').open('a+b')
    if run_lock.tell()==0: run_lock.write(b'0');run_lock.flush()
    run_lock.seek(0);msvcrt.locking(run_lock.fileno(),msvcrt.LK_NBLCK,1)
    config=json.loads((B/'config.json').read_text())
    protocol=json.loads((B/'protocol.json').read_text())
    assert sha(B/'models/champion.pt')=='b95195162750e188ecfad53d9eadcf730b18c097f60c6bc438ba5331a119d034'
    assert sha(B/'models/candidate.pt')=='9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13'
    proof=json.loads((SOURCE/'verification/report.json').read_text())
    assert proof['fatal_boundary']=='passed' and len(proof['replays'])==12
    backends={}
    for label in ['champion','candidate']:
        n=Backend(config['backend'],protocol,B/label)
        n.configure_workers(2);n.configure_search('learned',1.);n.built=True
        backends[label]=n
    runtime=SOURCE/'native/artifacts/native-host'
    manifest=dict(config=config,protocol=protocol['manifest_sha256'],
        models={label:sha(B/'models'/f'{label}.pt') for label in backends},
        provenance=backends['champion'].provenance,runner=sha(Path(__file__)),
        runtime={str(p.relative_to(runtime)):sha(p) for p in sorted(runtime.rglob('*'))
                 if p.is_file() and p.suffix.lower() in ('.dll','.exe')})
    prior_manifest=json.loads((SOURCE/'experiment.json').read_text())
    if manifest['runtime']!=prior_manifest['runtime'] or manifest['provenance']!=prior_manifest['provenance']:
        raise ValueError('Frozen isolated runtime/source changed since AlphaZero comparison')
    manifest['decision_mode']='network-policy-argmax-no-search'
    path=B/'experiment.json'
    if path.exists() and json.loads(path.read_text())!=manifest:
        raise ValueError('Experiment source/runtime/model identity changed')
    atomic_json(path,manifest)
    lock=threading.Lock();stop=threading.Event()
    progress=dict(status='running',pid=os.getpid(),search_budget_ms=None,protocol_budget_ms_unused=500,total_per_arm=296,
                  workers_per_arm=2,search='none-policy-argmax',arms={})
    def publish():
        progress['updated_at']=datetime.now(timezone.utc).isoformat()
        atomic_json(B/'progress.json',progress)
    def monitor():
        while not stop.wait(5):
            with lock:
                for label in backends:
                    p=B/label/'fights/progress.json'
                    if p.exists(): progress['arms'][label]=json.loads(p.read_text())
                publish()
    publish();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    def run(label):
        n=backends[label]
        raws=n.fights(B/'models'/f'{label}.pt',protocol['validation'],B/label/'fights','policy')
        result=summarize(raws)
        atomic_json(B/label/'summary.json',result)
        return raws,result
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures={label:pool.submit(run,label) for label in backends}
            results={label:f.result() for label,f in futures.items()}
        a={r['recipe']['scenario_id']:r for r in results['champion'][0]}
        c={r['recipe']['scenario_id']:r for r in results['candidate'][0]}
        assert a.keys()==c.keys() and all(a[k]['recipe']==c[k]['recipe'] for k in a)
        paired=paired_gain([dict(scenario_id=k,reward=a[k]['outcome']['reward']) for k in a],
                           [dict(scenario_id=k,reward=c[k]['outcome']['reward']) for k in c])
        report=dict(arms={k:v[1] for k,v in results.items()},paired=paired,
            gained_wins=sum(not a[k]['outcome']['won'] and c[k]['outcome']['won'] for k in a),
            lost_wins=sum(a[k]['outcome']['won'] and not c[k]['outcome']['won'] for k in a),
            caveat='Pure network argmax, no search. Value projections are checked for parity but do not select actions. Protocol budgetMs=500 is unused. Episode wall time includes engine and strict validation overhead.')
        atomic_json(B/'report.json',report)
        with lock:
            progress['arms']={label:json.loads((B/label/'fights/progress.json').read_text()) for label in backends}
            progress.update(status='completed',report=report);publish()
    except BaseException:
        with lock: progress.update(status='failed',error=traceback.format_exc());publish()
        raise
    finally:
        stop.set();thread.join()
if __name__=='__main__':main()
