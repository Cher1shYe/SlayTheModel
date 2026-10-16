"""OS-owned single writer lock; process exit releases it even after a crash."""
import os
from pathlib import Path


class RunLock:
    def __init__(self, directory):
        directory = Path(directory).resolve()
        directory.parent.mkdir(parents=True, exist_ok=True)
        self.stream = open(directory.parent / (directory.name + ".writer.lock"), "a+b")
        self.stream.seek(0, 2)
        if not self.stream.tell():
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError(f"Run already has a coordinator: {directory}") from exc

    def close(self):
        if not self.stream.closed:
            self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        if hasattr(self, "stream"):
            self.close()
