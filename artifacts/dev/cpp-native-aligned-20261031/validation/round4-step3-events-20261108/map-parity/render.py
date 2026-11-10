import sys, glob
src=open('validation/round4-step3-events-20261108/map-parity/compare_maps.py').read().split('total = same = 0')[0]
exec(src)
tag, act = sys.argv[1], int(sys.argv[2])
path=[p for p in glob.glob('/Users/yebohou/Workspace/SlayTheModel/artifacts/headless/**/*.decisions.jsonl', recursive=True) if tag in open(p.replace('.decisions.jsonl','')).read()][0]
seed, asc, maps = native_maps(path)
rc=sim.RunContext(); rc.init_seed(seed, asc)
cpp=cpp_map(rc.seed,act,asc); nat=maps[act]
for r in range(0,17):
    ln=''.join(('.' if (r,c) not in nat else nat[(r,c)][0][0]) for c in range(7))
    lc=''.join(('.' if (r,c) not in cpp else cpp[(r,c)][0][0]) for c in range(7))
    ed=[(k, nat.get(k,(0,[]))[1], cpp.get(k,(0,[]))[1]) for k in sorted(set(nat)|set(cpp)) if k[0]==r and nat.get(k,(0,[]))[1]!=cpp.get(k,(0,[]))[1]]
    print(f"{r:2} native {ln}  cpp {lc}", '' if ln==lc else ' <types', ' edges:'+str(ed) if ed else '')
