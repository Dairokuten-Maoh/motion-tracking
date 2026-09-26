"""Own one bounded speech worker, its protocol, timeout and process-tree cleanup."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

ROOT = Path(__file__).resolve().parent.parent


class VoiceProcess:
    def __init__(self, command=None):
        self.command = command or [str(ROOT / '.tools/tts-env/Scripts/python.exe'),
                                   '-u', str(ROOT / 'receiver/voice_worker.py')]
        self.process = None
        self.responses = None
        atexit.register(self.close)

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                process.kill()
        process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()

    def _start(self):
        self.close()
        self.responses = responses = queue.Queue(maxsize=1)
        self.process = process = subprocess.Popen(self.command, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            bufsize=1, cwd=ROOT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def read():
            while True:
                try:
                    line = process.stdout.readline(16385)
                except (OSError, ValueError):
                    line = ''
                try:
                    responses.put_nowait(line)
                except queue.Full:
                    return
                if not line:
                    return
        threading.Thread(target=read,daemon=True,name='voice-worker-output').start()

    def render(self, text, reference, output, timeout=120):
        """Called serially under the voice/GPU locks; failure kills before returning."""
        try:
            if self.process is None or self.process.poll() is not None:
                self._start()
            self.process.stdin.write(json.dumps(dict(text=text,reference=str(reference),output=str(output)))+'\n')
            self.process.stdin.flush()
            try:
                line = self.responses.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError('Voice synthesis timed out') from exc
            if not line or len(line) > 16384:
                raise RuntimeError('Voice worker disconnected')
            response = json.loads(line)
            if not isinstance(response, dict) or response.get('ok') is not True:
                raise RuntimeError('Voice synthesis failed')
            return response['metrics']
        except Exception:
            self.close()
            raise


WORKER = VoiceProcess()
