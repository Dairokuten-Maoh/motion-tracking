import types
import unittest
from command_speech import transcribe, LOCK, MAX_PCM, SpeechBusy

class SpeechTests(unittest.TestCase):
    def test_invalid_audio_never_loads_model(self):
        for data in (b'',b'x'*3201,b'x'*(MAX_PCM+2)):
            with self.assertRaises(ValueError):transcribe(data)
    def test_silence_returns_empty(self):self.assertEqual(transcribe(bytes(32000)),'')
    def test_filters_uncertain_segments_and_passes_normalized_audio(self):
        class Model:
            def transcribe(self,samples,**kwargs):
                assert len(samples)==1600
                assert kwargs['vad_filter'] and not kwargs['condition_on_previous_text']
                return iter([types.SimpleNamespace(text='Jarvis test',no_speech_prob=.01,avg_logprob=-.1),types.SimpleNamespace(text='invented',no_speech_prob=.9,avg_logprob=-2)]),None
        self.assertEqual(transcribe(b'\x00\x10'*1600,Model()),'Jarvis test')
    def test_busy_fails_without_parallel_model_load(self):
        LOCK.acquire()
        try:
            with self.assertRaises(SpeechBusy):transcribe(bytes(3200))
        finally:LOCK.release()
    def test_failure_releases_lock(self):
        class Model:
            def transcribe(self,*args,**kwargs):raise RuntimeError('Failed')
        with self.assertRaises(RuntimeError):transcribe(b'\x00\x10'*1600,Model())
        self.assertTrue(LOCK.acquire(blocking=False));LOCK.release()

if __name__=='__main__':unittest.main()
