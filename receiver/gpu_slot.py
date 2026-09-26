"""Serialize local model work across the receiver and diary worker.

The voice model and Ollama do not fit together on this PC's GPU. Callers hold
one slot through inference; the voice renderer can then unload Ollama safely.
The operating system releases the file lock even if a worker crashes.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import threading
import time

LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parent.parent / 'jarvis-data'


@contextmanager
def inference_slot(timeout=30):
    deadline = time.monotonic() + timeout
    if not LOCK.acquire(timeout=timeout):
        raise RuntimeError('Local model is busy')
    try:
        ROOT.mkdir(exist_ok=True)
        with (ROOT / 'inference.lock').open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            while True:
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Local model is busy')
                    time.sleep(0.1)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        LOCK.release()
