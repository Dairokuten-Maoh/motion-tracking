"""Serialize local model work across the receiver and diary worker.

The voice model and Ollama do not fit together on this PC's GPU. Callers hold
one slot through inference; the voice renderer can then unload Ollama safely.
The operating system releases the file lock even if a worker crashes.
"""
from contextlib import contextmanager
from contextlib import nullcontext
from pathlib import Path
import os
import threading
import time
import uuid

LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parent.parent / 'jarvis-data'


class BackgroundDeferred(RuntimeError):
    """Background work stays queued without counting as a generation failure."""


@contextmanager
def interactive_activity():
    """Reserve priority through a voice turn/stream, with crash-expiring markers."""
    ROOT.mkdir(exist_ok=True)
    waiting = ROOT / 'interactive'
    waiting.mkdir(exist_ok=True)
    marker = waiting / uuid.uuid4().hex
    marker.touch()
    try:
        yield
    finally:
        marker.unlink(missing_ok=True)
        (ROOT / 'last-interaction').touch()


def interactive_pending():
    now = time.time()
    for marker in (ROOT / 'interactive').glob('*'):
        try:
            if now - marker.stat().st_mtime < 600:
                return True
            marker.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    try:
        return now - (ROOT / 'last-interaction').stat().st_mtime < 30
    except FileNotFoundError:
        return False


@contextmanager
def inference_slot(timeout=30, background=False):
    # Priority is cooperative between bounded batches; never interrupt a GPU
    # kernel or release a live generation's lock to force another model to load.
    with (nullcontext() if background else interactive_activity()):
        if background and interactive_pending():
            raise BackgroundDeferred('Interactive request has priority')
        with _locked_slot(timeout, background):
            yield


@contextmanager
def _locked_slot(timeout, background):
    deadline = time.monotonic() + timeout
    if not LOCK.acquire(timeout=timeout):
        raise (BackgroundDeferred if background else RuntimeError)('Local model is busy')
    try:
        ROOT.mkdir(exist_ok=True)
        with (ROOT / 'inference.lock').open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'0'); stream.flush()
            while True:
                if background and interactive_pending():
                    raise BackgroundDeferred('Interactive request has priority')
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
                        raise (BackgroundDeferred if background else RuntimeError)('Local model is busy')
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
