import json
import subprocess
import sys
import unittest

from voice_process import VoiceProcess


class VoiceProcessTests(unittest.TestCase):
    def worker(self, code):
        worker = VoiceProcess([sys.executable, '-u', '-c', code])
        self.addCleanup(worker.close)
        return worker

    def test_reuses_worker_and_preserves_json_text(self):
        worker = self.worker('''import sys,json
for line in sys.stdin:
 request=json.loads(line)
 print(json.dumps({'ok':True,'metrics':{'text':request['text']}}),flush=True)
''')
        text = 'Quoted "words"\n中文'
        self.assertEqual(worker.render(text, 'reference', 'output')['text'], text)
        process = worker.process
        worker.render('Again.', 'reference', 'output')
        self.assertIs(worker.process, process)

    def test_timeout_kills_worker_and_next_request_restarts(self):
        worker = self.worker('''import sys,json,time
for line in sys.stdin:
 if json.loads(line)['text']=='stall':time.sleep(30)
 print('{"ok":true,"metrics":{}}',flush=True)
''')
        worker.render('ready', 'reference', 'output')
        process = worker.process
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            worker.render('stall', 'reference', 'output', timeout=0.1)
        self.assertIsNotNone(process.poll())
        self.assertIsNone(worker.process)
        worker.render('restarted', 'reference', 'output')
        self.assertNotEqual(worker.process.pid, process.pid)

    def test_bad_protocol_or_exit_disposes_process(self):
        for response in ['not json', '{"ok":false}', 'x'*17000, None]:
            with self.subTest(response=str(response)[:30]):
                code = 'import sys;sys.stdin.readline();'
                if response is not None:code += 'print('+repr(response)+',flush=True)'
                worker = self.worker(code)
                with self.assertRaises((RuntimeError, json.JSONDecodeError)):
                    worker.render('hello', 'reference', 'output', timeout=5)
                self.assertIsNone(worker.process)


if __name__ == '__main__':unittest.main()
