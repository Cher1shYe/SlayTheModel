"""Build the C++ simulator: the Python extension ``sts2_sim``, the C++ test programs and the
benchmark. Run from anywhere:

    python sim/build.py              # build (incremental: unchanged sources are not recompiled)
    python sim/build.py --test       # build, then run every C++ test program
    CXX=g++ python sim/build.py      # choose the compiler (default clang++)

Outputs go to sim/build/ (ignored by git): obj/, tests/<name> (+ <name>.log after --test),
bench, sts2_sim<ext>, build.json. Python finds the extension there (train/spire_rl/sim.py).
Tests keep their assertions (-UNDEBUG) and locate their fixtures through tests/port_root.h;
they are run with the working directory sim/.
"""
from pathlib import Path
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import time

src = Path(__file__).resolve().parent
out = src / 'build'
obj = out / 'obj'
test_dir = out / 'tests'
compiler = os.environ.get('CXX', 'clang++')
commands = []


def invoke(cmd):
    commands.append(cmd)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(' '.join(cmd) + '\n' + p.stdout + p.stderr)
    return p.stdout + p.stderr


def fingerprint(*parts: bytes) -> str:
    return hashlib.sha256(b''.join(parts)).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--test', action='store_true', help='run every C++ test program after building')
    ap.add_argument('--jobs', type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    ap.add_argument('--no-tests', action='store_true', help='build only the Python extension')
    args = ap.parse_args()
    started = time.monotonic()

    def roomy_test_stack():
        # Test programs keep many 640 KB RunContext objects in one stack frame. How many
        # slots share memory depends on the compiler: clang fits 8 MB, g++ can overflow it
        # (native_step3_events exited -11 on the Linux training machine).
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        for want in (256 << 20, 128 << 20, 64 << 20, 32 << 20, 16 << 20):   # macOS refuses its nominal maximum
            limit = want if hard == resource.RLIM_INFINITY else min(want, hard)
            if soft == resource.RLIM_INFINITY or soft >= limit:
                return
            try:
                resource.setrlimit(resource.RLIMIT_STACK, (limit, hard))
                return
            except (ValueError, OSError):
                continue

    for d in (obj, test_dir):
        d.mkdir(parents=True, exist_ok=True)
    def source_revision():
        inputs = sorted(p for directory in ('include', 'src', 'bindings', 'tests', 'apps')
                        for p in (src / directory).rglob('*') if p.is_file())
        return fingerprint(*(str(p.relative_to(src)).encode() + b'\0' + p.read_bytes()
                             for p in inputs))

    initial_revision = source_revision()
    headers = sorted(p for p in (src / 'include').rglob('*') if p.is_file())
    header_hash = hashlib.sha256(b''.join(p.read_bytes() for p in headers)).digest()

    def compile_one(p):
        target = obj / (p.stem + '.o')
        stamp = target.with_suffix('.sha256')
        fp = fingerprint(header_hash, p.read_bytes(), compiler.encode())
        if not target.exists() or not stamp.exists() or stamp.read_text() != fp:
            invoke([compiler, '-std=c++17', '-O3', '-DNDEBUG', '-fPIC', '-Wno-shift-count-overflow',
                    '-I' + str(src / 'include'), '-c', str(p), '-o', str(target)])
            stamp.write_text(fp)
        return str(target)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        objects = list(pool.map(compile_one, sorted((src / 'src').glob('*.cpp'))))
    obj_hash = hashlib.sha256(b''.join(Path(o).read_bytes() for o in objects)).digest()

    def link_program(source: Path, target: Path):
        stamp = target.with_name(target.name + '.sha256')
        fp = fingerprint(obj_hash, header_hash, source.read_bytes(), compiler.encode(),
                         *(p.read_bytes() for p in sorted((src / 'tests').glob('*.[hi]*'))))
        if target.exists() and stamp.exists() and stamp.read_text() == fp:
            return
        invoke([compiler, '-std=c++17', '-O3', '-UNDEBUG', '-I' + str(src / 'include'),
                '-I' + str(src / 'json/include'), str(source), *objects, '-o', str(target)])
        stamp.write_text(fp)
        print('built', target.name, flush=True)

    tests = sorted((src / 'tests').glob('*.cpp'))
    if not args.no_tests:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            jobs = [pool.submit(link_program, t, test_dir / t.stem) for t in tests]
            jobs.append(pool.submit(link_program, src / 'apps/bench.cpp', out / 'bench'))
            for j in jobs:
                j.result()
    module = out / ('sts2_sim' + sysconfig.get_config_var('EXT_SUFFIX'))
    tmp = module.with_name(module.name + '.tmp')        # running processes keep the old file
    link = ['-bundle', '-undefined', 'dynamic_lookup'] if sys.platform == 'darwin' else ['-shared']
    invoke([compiler, '-std=c++17', '-O3', '-DNDEBUG', '-fPIC', *link,
            '-I' + str(src / 'include'), '-I' + str(src / 'pybind11/include'),
            '-I' + sysconfig.get_paths()['include'], str(src / 'bindings/bindings.cpp'),
            *objects, '-o', str(tmp)])
    if source_revision() != initial_revision:
        # A shared-workspace header edit can otherwise publish an extension
        # combining incompatible layouts. Force recompilation on the retry.
        for directory in (obj, test_dir, out):
            for stamp in directory.glob('*.sha256'):
                stamp.unlink()
        raise RuntimeError('Simulator inputs changed during the build; no extension was published. '
                           'Wait for source edits to finish and rebuild.')
    os.replace(tmp, module)
    print('built', module, flush=True)
    record = {'compiler': compiler, 'commands': commands, 'wall_seconds': round(time.monotonic() - started, 1),
              'module': str(module), 'module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
              'python': sys.executable}

    if args.test:
        failed = []
        for t in tests:
            exe = test_dir / t.stem
            t0 = time.monotonic()
            p = subprocess.run([str(exe)], cwd=src, capture_output=True, text=True,
                               preexec_fn=roomy_test_stack if os.name == 'posix' else None)
            (test_dir / (t.stem + '.log')).write_text(p.stdout + p.stderr)
            status = 'ok' if p.returncode == 0 else f'FAILED ({p.returncode})'
            print(f'{status:12s} {t.stem}  [{time.monotonic() - t0:.1f}s]', flush=True)
            if p.returncode:
                failed.append(t.stem)
        record['tests'] = {'total': len(tests), 'failed': failed}
        print(f'{len(tests) - len(failed)}/{len(tests)} test programs passed', flush=True)
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    if args.test and record['tests']['failed']:
        sys.exit(1)


if __name__ == '__main__':
    main()
