"""Transcribe bounded in-memory command audio locally; never execute or persist it here."""
import threading

MAX_PCM = 16000 * 2 * 21
LOCK = threading.Lock()
MODEL = None


class SpeechBusy(Exception): pass


def transcribe(pcm, model=None):
    if not isinstance(pcm, bytes) or not 3200 <= len(pcm) <= MAX_PCM or len(pcm) % 2:
        raise ValueError('Expected 0.1 to 21 seconds of mono 16 kHz signed PCM16 little-endian audio')
    if not LOCK.acquire(blocking=False):raise SpeechBusy('Command transcription is busy; please repeat shortly.')
    try:
        import numpy as np
        samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.0
        if not np.any(samples):return ''
        if model is None:
            global MODEL
            if MODEL is None:
                from faster_whisper import WhisperModel
                # The archive worker already installed this model. A request must not
                # trigger a model download or require an external speech provider.
                MODEL=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
            model=MODEL
        segments,_=model.transcribe(samples,language='en',beam_size=5,vad_filter=True,
            condition_on_previous_text=False,temperature=0,
            vad_parameters={'min_silence_duration_ms':500})
        text=' '.join(s.text.strip() for s in segments if s.no_speech_prob<.6 and s.avg_logprob> -1.0).strip()
        if len(text)>1000:raise ValueError('Command is too long; please use a shorter request')
        return text
    finally:LOCK.release()
