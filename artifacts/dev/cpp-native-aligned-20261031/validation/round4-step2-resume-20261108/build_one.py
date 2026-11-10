"""Compile core objects (cached, same flags as build_local.py) and link named tests."""
import sys, runpy, types
from pathlib import Path
root = Path(__file__).resolve().parents[1]
code = (root/'build_local.py').read_text()
cut = code.index("tests = sorted(")
ns = {'__file__': str(root/'build_local.py'), '__name__': 'b'}
exec(compile(code[:cut], 'build_local_head', 'exec'), ns)
src, objects, invoke = ns['src'], ns['objects'], ns['invoke']
for name in sys.argv[1:]:
    source = src/'tests'/(name+'.cpp')
    invoke([ns['compiler'], '-std=c++17', '-O3', '-UNDEBUG', '-I'+str(src/'include'), '-I'+str(src/'json/include'),
            str(source), *objects, '-o', str(root/name)])
    print('built', name, flush=True)
