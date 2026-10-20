"""Two fresh 500ms all-node policy/pure-value evaluations, strict and resumable."""
from pathlib import Path
import sys,json,hashlib,threading,traceback,os,statistics
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
B=Path(__file__).resolve().parent
sys.path.insert(0,str(B/'python'))
from sts2_env.az.config import atomic_json,content_hash
from sts2_env.az.native_generic_backend import NativeBackend
from sts2_env.az.native_generic import validate_raw,raw_leaf_settings
from sts2_env.az.all_runner import paired_gain

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
class Backend(NativeBackend):
    def raw_validator(self,r):
        if raw_leaf_settings(r)!=('learned',1.) or r.get('searchMode')!='all-node-policy-pure-value-v1':
            raise ValueError('Not pure-value all-node AlphaZero search')
        return validate_raw(r,allow_search_validation_cutoff=True)

def summarize(raws):
    s=[s for r in raws for s in r['steps'] if not s['forced']]
    d=[s['leafDiagnostics'] for s in s]
    sims=sum(s['simulations'] for s in s)
    return dict(fights=len(raws),wins=sum(r['outcome']['won'] for r in raws),
        win_rate=sum(r['outcome']['won'] for r in raws)/len(raws),
        mean_utility=statistics.mean(r['outcome']['reward'] for r in raws),
        truncated=sum(not r['complete'] for r in raws),searched_decisions=len(s),
        mean_simulations=statistics.mean(s['simulations'] for s in s),
        median_simulations=statistics.median(s['simulations'] for s in s),
        mean_backup_depth=statistics.mean(x['meanBackupDepth'] for x in d),
        mean_node_policy_calls=statistics.mean(x['nodePolicyCalls'] for x in d),
        terminal_backup_fraction=sum(x['terminalBackups'] for x in d)/sims,
        mean_search_ms=1000*statistics.mean(s['seconds'] for s in s))

def main():
    import msvcrt
    run_lock=(B/'runner.lock').open('a+b')
    if run_lock.tell()==0: run_lock.write(b'0');run_lock.flush()
    run_lock.seek(0);msvcrt.locking(run_lock.fileno(),msvcrt.LK_NBLCK,1)
    config=json.loads((B/'config.json').read_text())
    protocol=json.loads((B/'protocol.json').read_text())
    assert sha(B/'models/champion.pt')=='b95195162750e188ecfad53d9eadcf730b18c097f60c6bc438ba5331a119d034'
    assert sha(B/'models/candidate.pt')=='9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13'
    proof=json.loads((B/'verification/report.json').read_text())
    assert proof['fatal_boundary']=='passed' and len(proof['replays'])==12
    backends={}
    for label in ['champion','candidate']:
        n=Backend(config['backend'],protocol,B/label)
        n.configure_workers(2);n.configure_search('learned',1.);n.built=True
        backends[label]=n
    runtime=B/'native/artifacts/native-host'
    manifest=dict(config=config,protocol=protocol['manifest_sha256'],
        models={label:sha(B/'models'/f'{label}.pt') for label in backends},
        provenance=backends['champion'].provenance,runner=sha(Path(__file__)),
        runtime={str(p.relative_to(runtime)):sha(p) for p in sorted(runtime.rglob('*'))
                 if p.is_file() and p.suffix.lower() in ('.dll','.exe')})
    path=B/'experiment.json'
    if path.exists() and json.loads(path.read_text())!=manifest:
        raise ValueError('Experiment source/runtime/model identity changed')
    atomic_json(path,manifest)
    lock=threading.Lock();stop=threading.Event()
    progress=dict(status='running',pid=os.getpid(),budget_ms=500,total_per_arm=296,
                  workers_per_arm=2,search='all-node-policy-pure-value-v1',arms={})
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
        raws=n.fights(B/'models'/f'{label}.pt',protocol['validation'],B/label/'fights','puct')
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
            caveat='Single paired frozen-recipe run; same-host timed search. Simulations include terminal revisits; depth is meanBackupDepth, not maximum.')
        atomic_json(B/'report.json',report)
        with lock: progress.update(status='completed',report=report);publish()
    except BaseException:
        with lock: progress.update(status='failed',error=traceback.format_exc());publish()
        raise
    finally:
        stop.set();thread.join()
if __name__=='__main__':main()
