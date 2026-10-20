"""Host-only portability helpers; no combat or search semantics."""
import os
from pathlib import Path
import signal
import subprocess


def lock_run(path):
    stream = Path(path).open('a+b')
    if stream.tell() == 0:
        stream.write(b'0')
        stream.flush()
    stream.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def worker_executable(repo, platform=None):
    platform = platform or os.name
    return Path(repo)/'artifacts/native-host'/('NativeWorker.exe' if platform == 'nt' else 'NativeWorker.x86_64')


def stop_process_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()
