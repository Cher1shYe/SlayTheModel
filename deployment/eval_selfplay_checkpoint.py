import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import selfplay_compare as E

def main():
    root=E.ROOT/'deployment/selfplay_6x40_s64'
    out=root/'round4_evaluation'; out.mkdir(exist_ok=True)
    config=json.loads((root/'config.json').read_text())
    wp=str(root/'round4_policy.pt'); wv=str(root/'round4_value.pt')
    results={}
    with ProcessPoolExecutor(max_workers=4,initializer=E.init_worker,initargs=(str(root/'source'),)) as pool:
        def run(label,mode,budget):
            path=out/(label+'.json')
            if path.exists():
                results[label]=json.loads(path.read_text())['summary']; return
            rows=[]
            fs=[pool.submit(E.play,(s,mode,wp,wv,budget)) for s in config['eval_seeds']]
            for f in as_completed(fs):
                r=f.result(); r.pop('samples'); rows.append(r)
                E.dump(out/'progress.json',dict(stage=label,done=len(rows),total=50))
                if r['status']=='error': E.dump(out/'error.json',r); raise RuntimeError(r['error'])
            rows.sort(key=lambda r:r['seed'])
            results[label]=E.summarize(rows)
            E.dump(path,dict(summary=results[label],runs=rows))
            print(label,json.dumps(results[label]),flush=True)
        run('after_pure','pure',64)
        run('after_puct','puct',64)
        run('native_equal_count','native',64)
        run('native_time_pure','timed',results['after_pure']['mean_decision_ms'])
        run('native_time_puct','timed',results['after_puct']['mean_decision_ms'])
    E.dump(out/'results.json',results)
    E.dump(out/'progress.json',dict(stage='complete'))

if __name__=='__main__': main()
