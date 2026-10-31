from pathlib import Path
import subprocess,concurrent.futures,json,time
root=Path(__file__).resolve().parents[2]
out=Path(__file__).resolve().parent
obj=out/'relic-objects';obj.mkdir(exist_ok=True)
names=[p.name for p in (out/'source-before/simulator/src').glob('*.cpp')]+['relic_lifecycle.cpp','relic_persistent.cpp','relic_card_rewards.cpp']
def compile(name):
 source=root/'simulator/src'/name; target=obj/(source.stem+'.o')
 subprocess.run(['clang++','-std=c++17','-O1','-I'+str(root/'simulator/include'),'-c',str(source),'-o',str(target)],check=True,capture_output=True)
 return str(target)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool: objects=list(pool.map(compile,names))
results=[]
for name in ['native_step2_card_rewards','native_step2_relic_lifecycle','native_step2_persistent']:
 binary=out/name
 subprocess.run(['clang++','-std=c++17','-O1','-UNDEBUG','-I'+str(root/'simulator/include'),'-I'+str(root/'simulator/json/include'),str(root/'simulator/tests'/(name+'.cpp')),*objects,'-o',str(binary)],check=True)
 p=subprocess.run([str(binary)],cwd=root,capture_output=True,text=True)
 results.append(dict(name=name,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr));print(name,p.returncode,p.stdout,p.stderr,flush=True)
(out/'relic-integration-initial.json').write_text(json.dumps(results,indent=2)+'\n')
