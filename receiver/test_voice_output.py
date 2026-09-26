import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
import voice_output
from gpu_slot import inference_slot


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x01\x00' * 2400)
    return output.getvalue()


class VoiceTests(unittest.TestCase):
    def test_stream_yields_first_sentence_before_rendering_rest_and_cleans_on_close(self):
        with patch('voice_output.synthesize',return_value=wav_bytes()) as render:
            stream=voice_output.synthesize_stream('The workshop is ready. Your appointment is at 3.5 hours from now.',self.root)
            self.assertEqual(next(stream),wav_bytes())
            self.assertEqual(render.call_count,1)
            self.assertEqual(render.call_args.args[0],'The workshop is ready.')
            self.assertEqual(next(stream),wav_bytes())
            self.assertIn('3.5',render.call_args.args[0])
            stream.close()
            self.assertFalse(list((self.root/'interactive').iterdir()))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.voice = self.root / 'voice'; self.voice.mkdir()
        (self.voice / 'enabled').touch()
        (self.voice / 'reference.wav').write_bytes(wav_bytes())
        # Unit tests must not contend with the running receiver's GPU lock file.
        slot_root = patch('gpu_slot.ROOT', self.root)
        slot_root.start()
        self.addCleanup(slot_root.stop)

    def tearDown(self):
        self.temp.cleanup()

    def render(self, text, reference, output):
        Path(output).write_bytes(wav_bytes())
        return {}

    def test_canned_cache_but_personal_replies_are_temporary(self):
        with patch('voice_output.WORKER.render', side_effect=self.render) as render, \
                patch('voice_output.urllib.request.urlopen', side_effect=lambda *a, **k: io.BytesIO(b'{}')):
            for _ in range(2): voice_output.synthesize("I'm listening.", self.root)
            self.assertEqual(render.call_count, 1)
            for _ in range(2): voice_output.synthesize('Private reply.', self.root)
            self.assertEqual(render.call_count, 3)
            self.assertEqual(len(list(self.voice.glob('*.wav'))), 2)
            self.assertFalse(list(self.voice.glob('render-*')))
            (self.voice / 'reference.wav').write_bytes(wav_bytes() + b'new')
            voice_output.synthesize("I'm listening.", self.root)
            self.assertEqual(render.call_count, 4)

    def test_timeout_cleans_files_and_releases_lock(self):
        with patch('voice_output.WORKER.render', side_effect=RuntimeError('Voice synthesis timed out')), \
                patch('voice_output.urllib.request.urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                voice_output.synthesize('Hello.', self.root)
        self.assertFalse(voice_output.LOCK.locked())
        self.assertFalse(list(self.voice.glob('render-*')))
        with inference_slot(timeout=0.1): pass

    def test_invalid_text_disabled_voice_and_corrupt_output(self):
        for text in [None, '', 'x' * 1201]:
            with self.assertRaises(ValueError): voice_output.synthesize(text, self.root)
        (self.voice / 'enabled').unlink()
        with self.assertRaisesRegex(RuntimeError, 'not enabled'):
            voice_output.synthesize('Hello.', self.root)
        with self.assertRaises((RuntimeError, wave.Error, EOFError)):
            voice_output.checked_wav(b'x' * 100)
        with self.assertRaises(RuntimeError):
            voice_output.checked_wav(wav_bytes()[:-2])

    def test_model_slot_times_out_without_releasing_owner(self):
        with inference_slot():
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with inference_slot(timeout=0.01): pass
        with inference_slot(timeout=0.1): pass

    def test_model_slot_excludes_another_process(self):
        code = '''import sys
from pathlib import Path
import gpu_slot
gpu_slot.ROOT=Path(sys.argv[1])
try:
 with gpu_slot.inference_slot(timeout=0.15): print('acquired')
except RuntimeError: print('busy')
'''
        def attempt():
            return subprocess.check_output([sys.executable, '-c', code, str(self.root)],
                cwd=Path(__file__).parent, text=True, timeout=5).strip()
        with patch('gpu_slot.ROOT', self.root):
            with inference_slot(): self.assertEqual(attempt(), 'busy')
            self.assertEqual(attempt(), 'acquired')


if __name__ == '__main__': unittest.main()
