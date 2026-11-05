"""Portable local audit build. Core compiled once; tests retain assertions."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import time

root = Path(__file__).resolve().parent
src = root.parent / 'simulator'
obj = root / 'obj'
obj.mkdir(exist_ok=True)
compiler = os.environ.get('CXX', 'clang++')
commands = []
started = time.monotonic()

def invoke(cmd):
    commands.append(cmd)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(' '.join(cmd) + '\n' + p.stdout + p.stderr)
    return p.stdout + p.stderr

headers = sorted((src / 'include').rglob('*'))
header_hash = hashlib.sha256(b''.join(p.read_bytes() for p in headers if p.is_file())).digest()

def compile_one(p):
    target = obj / (p.stem + '.o')
    stamp = target.with_suffix('.sha256')
    fingerprint = hashlib.sha256(header_hash + p.read_bytes()).hexdigest()
    if not target.exists() or not stamp.exists() or stamp.read_text() != fingerprint:
        invoke([compiler, '-std=c++17', '-O3', '-DNDEBUG', '-fPIC', '-Wno-shift-count-overflow',
                '-I' + str(src / 'include'), '-c', str(p), '-o', str(target)])
        stamp.write_text(fingerprint)
    return str(target)

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    objects = list(pool.map(compile_one, sorted((src / 'src').glob('*.cpp'))))
tests = sorted((src / 'tests').glob('*.cpp'))
for source in tests + [src / 'apps/bench.cpp']:
    target = root / source.stem
    invoke([compiler, '-std=c++17', '-O3', '-UNDEBUG', '-I' + str(src / 'include'), '-I' + str(src / 'json/include'),
            str(source), *objects, '-o', str(target)])
    print('built', source.stem, flush=True)
module = src / ('sts2_sim' + sysconfig.get_config_var('EXT_SUFFIX'))
link = ['-bundle', '-undefined', 'dynamic_lookup'] if sys.platform == 'darwin' else ['-shared']
invoke([compiler, '-std=c++17', '-O3', '-DNDEBUG', '-fPIC', *link,
        '-I' + str(src / 'include'), '-I' + str(src / 'pybind11/include'),
        '-I' + sysconfig.get_paths()['include'], str(src / 'bindings/bindings.cpp'),
        *objects, '-o', str(module)])
(root / 'build.json').write_text(json.dumps({
    'commands': commands, 'wall_seconds': time.monotonic() - started,
    'module': str(module), 'module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
    'tests_assertions_enabled': True, 'python': sys.executable,
}, indent=2) + '\n')
print('built', module, flush=True)
