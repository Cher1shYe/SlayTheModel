import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import cProfile
import pstats
import io
import json
from pathlib import Path
import time
import statistics
import selfplay_compare as E

def main():
    root=E.ROOT/'deployment/selfplay_stable_s512_r1'
    out=E.ROOT/'deployment/puct_speed'; out.mkdir(exist_ok=True)
    E.init_worker(str(root/'source'))
    import benchmark_speed as fixture
    import fast_puct
    policy,value=E.SP._load(str(root/'round1_policy.pt'),str(root/'round1_value.pt'))
    states=fixture.collect(E.SP._load_armg())
    print('states',len(states),flush=True)
    mc=E.MC; original=mc.expand; original_sanitize=E.B.sanitize_state
    probe=[-1e30,-100.000001,-100.,-0.,0.,1.,99.999999,100.000001,1e30]
    assert fast_puct.sanitize_state(probe)==original_sanitize(probe)
    for bad in (float('nan'),float('inf'),-float('inf')):
        try: fast_puct.sanitize_state([bad])
        except ValueError: pass
        else: raise AssertionError('Nonfinite observation accepted')
    def search(bc):
        node=mc.Node(bc.clone())
        for _ in range(512): mc.simulate(node,policy,value)
        return dict(N=node.N,W=node.W,P=node.P,action=node.cands[max(range(len(node.N)),key=lambda i:node.N[i])].bits)
    results=[]
    for idx,(meta,bc) in enumerate(states):
        mc.expand=original; E.B.sanitize_state=original_sanitize; search(bc)
        times={'original':[],'fast':[]}; outputs={}
        for repeat in range(3):
            for mode in (('original','fast') if repeat%2==0 else ('fast','original')):
                if mode=='original': mc.expand=original; E.B.sanitize_state=original_sanitize
                else: fast_puct.install(mc)
                start=time.perf_counter(); outputs[mode]=search(bc); times[mode].append(time.perf_counter()-start)
        match=outputs['original']==outputs['fast']
        results.append(dict(meta=meta,seconds=times,exact_root_match=match))
        print(idx,match,{k:round(statistics.median(v)*1000,2) for k,v in times.items()},flush=True)
        if not match:
            E.dump(out/'mismatch.json',outputs); raise RuntimeError('Search changed')
    for mode in ('original','fast'):
        if mode=='original': mc.expand=original; E.B.sanitize_state=original_sanitize
        else: fast_puct.install(mc)
        profiler=cProfile.Profile(); profiler.enable()
        for _,bc in states: search(bc)
        profiler.disable(); profiler.dump_stats(str(out/(mode+'.prof')))
        stream=io.StringIO(); pstats.Stats(profiler,stream=stream).sort_stats('tottime').print_stats(35)
        (out/(mode+'_profile.txt')).write_text(stream.getvalue(),encoding='utf-8')
    # Low-overhead timed categories, separate from cProfile's substantial
    # per-Python-call overhead on the elementwise sanitizer.
    mc.expand=original; E.B.sanitize_state=original_sanitize
    measured={k:0. for k in ('sanitize','tensor_creation','network','state_encoding','candidate_encoding')}
    def timed(fn,key,subtract_sanitize=False):
        def wrapper(*args,**kwargs):
            initial=measured['sanitize']; start=time.perf_counter()
            try: return fn(*args,**kwargs)
            finally:
                elapsed=time.perf_counter()-start
                measured[key]+=elapsed-(measured['sanitize']-initial if subtract_sanitize else 0.)
        return wrapper
    E.B.sanitize_state=timed(original_sanitize,'sanitize')
    encode=E.B.encode_battle; candidate=E.B.cand_desc; tensor=E.torch.tensor
    E.B.encode_battle=timed(encode,'state_encoding',True)
    E.B.cand_desc=timed(candidate,'candidate_encoding')
    E.torch.tensor=timed(tensor,'tensor_creation')
    pf=policy.net.forward; vf=value.net.forward
    policy.net.forward=timed(pf,'network'); value.net.forward=timed(vf,'network')
    start=time.perf_counter()
    for _,bc in states: search(bc)
    total=time.perf_counter()-start
    measured['other_search_and_overhead']=total-sum(measured.values())
    E.dump(out/'breakdown.json',dict(seconds=measured,total_seconds=total,percent={k:100*v/total for k,v in measured.items()}))
    summary={mode:1000*statistics.mean(statistics.median(r['seconds'][mode]) for r in results) for mode in ('original','fast')}
    E.dump(out/'results.json',dict(states=len(states),simulations=512,repeats=3,torch_threads=1,mean_state_median_ms=summary,speedup=summary['original']/summary['fast'],all_exact_root_match=all(r['exact_root_match'] for r in results),runs=results))
    print(summary,flush=True)

if __name__=='__main__': main()
