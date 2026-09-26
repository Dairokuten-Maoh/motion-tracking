"""Generate bounded local speech, releasing GPU memory when rendering ends.

Only fixed interface phrases are cached on disk. Personal replies use temporary
files, deleted after delivery or failure. Rendering has no action/tool capability.
"""
import hashlib
import io
import json
import re
from pathlib import Path
import tempfile
import threading
import urllib.request
import wave
from gpu_slot import inference_slot, interactive_activity
from voice_process import WORKER

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.Lock()
CANNED = {"I'm listening.", "Okay. I'll wait for Hey Jarvis.",
          "I didn't hear a question. Please try again."}
MAX_WAV = 16_000_000


def synthesize_stream(text, data):
    """Yield complete sentence WAVs; closing the iterator releases priority.

    A completed chunk can play while the next renders. The caller must signal
    successful end explicitly; a truncated connection is not successful speech.
    """
    if not isinstance(text,str) or not 1 <= len(text.strip()) <= 1200:
        raise ValueError('Speech text must contain 1 to 1200 characters')
    pieces=[]
    for sentence in re.split(r'(?<=[.!?])\s+|(?<=[。！？])',text.strip()):
        while len(sentence)>240:
            cut=sentence.rfind(' ',0,241)
            if cut<1:cut=240
            pieces.append(sentence[:cut])
            sentence=sentence[cut:].strip()
        if sentence:
            if pieces and len(pieces[-1])<12 and len(pieces[-1])+len(sentence)<239:
                pieces[-1]+=' '+sentence
            else:pieces.append(sentence)
    total=0
    with interactive_activity():
        for piece in pieces:
            body=synthesize(piece,data)
            total+=len(body)
            if total>MAX_WAV:raise RuntimeError('Speech stream is too large')
            yield body


def checked_wav(body):
    if not 44 <= len(body) <= MAX_WAV:
        raise RuntimeError('Invalid synthesized audio size')
    with wave.open(io.BytesIO(body), 'rb') as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or not 16000 <= wav.getframerate() <= 48000:
            raise RuntimeError('Invalid synthesized audio format')
        frames = wav.getnframes()
        if not 0 < frames <= wav.getframerate() * 180 or len(wav.readframes(frames)) != frames * 2:
            raise RuntimeError('Invalid synthesized audio duration')
    return body


def synthesize(text, data):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
        raise ValueError('Speech text must contain 1 to 1200 characters')
    text = text.strip()
    voice = Path(data) / 'voice'
    if not (voice / 'enabled').exists():
        raise RuntimeError('Custom voice is not enabled')
    reference = voice / 'reference.wav'
    if not reference.is_file():
        raise RuntimeError('Voice reference is missing')
    if not LOCK.acquire(blocking=False):
        raise RuntimeError('Voice synthesis is busy')
    try:
        # Reference changes automatically invalidate the small fixed-phrase cache.
        key = hashlib.sha256(reference.read_bytes() + text.encode() + b'voxcpm-v1').hexdigest()
        cache = voice / (key + '.wav')
        if text in CANNED and cache.exists():
            return checked_wav(cache.read_bytes())
        with inference_slot(), tempfile.TemporaryDirectory(prefix='render-', dir=voice) as temporary:
            # Other Jarvis model requests hold the same cross-process lock.
            request = urllib.request.Request('http://127.0.0.1:11434/api/generate',
                data=json.dumps({'model': 'qwen2.5:14b', 'keep_alive': 0}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            output = Path(temporary) / 'speech.wav'
            WORKER.render(text, reference.resolve(), output.resolve())
            if not output.exists():
                raise RuntimeError('Voice synthesis failed')
            body = checked_wav(output.read_bytes())
        if text in CANNED:
            cache.write_bytes(body)
        return body
    finally:
        LOCK.release()
