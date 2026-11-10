"""Compile audit probes without replacing the loaded simulator or old evidence."""
from pathlib import Path
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time

here = Path(__file__).resolve().parent
port = here.parent.parent
src = port / 'simulator'
compiler = os.environ.get('CXX', 'clang++')
extra_flags = shlex.split(os.environ.get('AUDIT_CXXFLAGS', ''))
header_hash = hashlib.sha256(b''.join(p.read_bytes() for p in sorted((src / 'include').rglob('*')) if p.is_file())).digest()
objects = []
commands = []
sources = {}
started = time.monotonic()
for p in sorted((src / 'src').glob('*.cpp')):
    sources[str(p.relative_to(port))] = hashlib.sha256(p.read_bytes()).hexdigest()
    fingerprint = hashlib.sha256(header_hash + p.read_bytes()).hexdigest()
    cached = port / 'validation/obj' / (p.stem + '.o')
    stamp = cached.with_suffix('.sha256')
    # Reuse matching native objects only on this audited macOS/arm64 host.
    native = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    if native and cached.exists() and stamp.exists() and stamp.read_text() == fingerprint:
        objects.append(str(cached))
    else:
        local = here / 'obj' / (p.stem + '.o')
        local.parent.mkdir(exist_ok=True)
        cmd = [compiler, *extra_flags, '-std=c++17', '-O3', '-DNDEBUG', '-fPIC', '-I' + str(src / 'include'), '-c', str(p), '-o', str(local)]
        commands.append(cmd)
        subprocess.run(cmd, check=True)
        objects.append(str(local))
results = []
for name, source in [('hidden_resampling_control', src / 'tests/hidden_resampling.cpp'),
                     ('probe', here / 'probe.cpp')]:
    binary = here / name
    cmd = [compiler, *extra_flags, '-std=c++17', '-O3', '-UNDEBUG', '-I' + str(src / 'include'), str(source), *objects, '-o', str(binary)]
    commands.append(cmd)
    subprocess.run(cmd, check=True)
    p = subprocess.run([str(binary)], capture_output=True, text=True, cwd=port)
    (here / (name + '.txt')).write_text(p.stdout + p.stderr)
    results.append({'name': name, 'exit_code': p.returncode, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    print(name, 'exit', p.returncode, flush=True)
    print(p.stdout, end='', flush=True)
(here / 'results.json').write_text(json.dumps({'audit_only': True, 'production_sources_modified': False,
    'host': platform.platform(), 'header_sha256': header_hash.hex(), 'source_sha256': sources,
    'commands': commands, 'tests': results, 'wall_seconds': time.monotonic() - started}, indent=2) + '\n')
sys.exit(1 if any(r['exit_code'] != 0 for r in results) else 0)
