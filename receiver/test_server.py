import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import uuid
import wave
from http.server import ThreadingHTTPServer
from server import Archive, handler_for, RETENTION


def audio():
    data = io.BytesIO()
    with wave.open(data, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b'\x00\x00' * 1600)
    return data.getvalue()


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Archive(self.temp.name)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.archive, 'test-token'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def send(self, clip_id, data=None, token='test-token'):
        request = urllib.request.Request(self.url + '/recordings', data=audio() if data is None else data,
            headers={'Authorization': 'Bearer ' + token, 'X-Recording-Id': clip_id,
                     'X-Started-At': str(time.time())})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_retry_after_ack_loss_is_idempotent(self):
        clip_id = str(uuid.uuid4())
        self.assertEqual(self.send(clip_id)[0], 201)
        self.assertEqual(self.send(clip_id)[0], 200)
        self.assertEqual(len(self.archive.search('')), 1)
        self.assertEqual(len(list(self.archive.raw.glob('*.wav'))), 1)

    def test_authentication_prevents_ingestion(self):
        self.assertEqual(self.send(str(uuid.uuid4()), token='wrong')[0], 401)
        self.assertFalse(self.archive.search(''))

    def test_speech_requires_auth_and_returns_audio_without_archiving(self):
        def request(token, body):
            return urllib.request.Request(self.url + '/speak', data=body,
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with patch('voice_output.synthesize', return_value=audio()) as synthesize:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request('wrong', b'{"text":"Hello"}'))
            self.assertEqual(error.exception.code, 401)
            synthesize.assert_not_called()
            with urllib.request.urlopen(request('test-token', b'{"text":"Hello"}')) as response:
                self.assertEqual(response.headers['Content-Type'], 'audio/wav')
                self.assertEqual(response.read(), audio())
            synthesize.assert_called_once_with('Hello', self.archive.root)
        self.assertFalse(self.archive.search(''))

    def test_rejects_corrupt_audio_and_traversal(self):
        self.assertEqual(self.send('../escape')[0], 400)
        self.assertEqual(self.send(str(uuid.uuid4()), b'x' * 100)[0], 400)
        self.assertEqual(self.send(str(uuid.uuid4()), audio()[:-10])[0], 400)

    def test_conflicting_retry_does_not_overwrite(self):
        clip_id = str(uuid.uuid4())
        self.send(clip_id)
        changed = audio()[:-2] + b'\x01\x00'
        self.assertEqual(self.send(clip_id, changed)[0], 400)
        self.assertEqual((self.archive.raw / (clip_id + '.wav')).read_bytes(), audio())

    def test_retention_preserves_transcript_and_expires_pending(self):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        for clip_id in ids: self.send(clip_id)
        with self.archive.connect() as db:
            db.execute('UPDATE recordings SET started=?', (time.time() - RETENTION - 1,))
            db.execute("UPDATE recordings SET transcript='明天 meeting',state='done' WHERE id=?", (ids[0],))
        self.archive.expire()
        self.assertFalse(list(self.archive.raw.glob('*.wav')))
        self.assertEqual(self.archive.search('明天')[0]['state'], 'done')
        self.assertIn('expired', [row['state'] for row in self.archive.search('')])

    def test_archive_survives_restart(self):
        self.send(str(uuid.uuid4()))
        self.assertEqual(len(Archive(self.temp.name).search('')), 1)

    def test_rejects_old_and_nonfinite_timestamp(self):
        for started in [time.time() - RETENTION - 1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): self.archive.ingest(str(uuid.uuid4()), started, audio())

    def test_dashboard_public_but_history_and_audio_authenticated(self):
        with urllib.request.urlopen(self.url + '/') as response:
            self.assertIn(b'Daily history', response.read())
        for path in ['/timeline', '/audio/' + str(uuid.uuid4())]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(error.exception.code, 401)

    def test_audio_playback_and_expiration(self):
        clip_id = str(uuid.uuid4())
        self.send(clip_id)
        request = urllib.request.Request(self.url + '/audio/' + clip_id, headers={'Authorization': 'Bearer test-token'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.read(), audio())
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.archive.connect() as db:
            db.execute('UPDATE recordings SET started=?', (time.time()-RETENTION-1,))
        with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 404)

    def test_ask_endpoint_auth_validation_and_no_evidence(self):
        def post(payload,token='test-token'):
            request=urllib.request.Request(self.url+'/ask',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as error:return error.code,json.load(error)
        self.assertEqual(post({'question':'Hello','day':'2026-09-25'},'bad')[0],401)
        self.assertEqual(post({'question':'Hello','day':'invalid'})[0],400)
        # Keep HTTP/empty-archive validation independent of a running local model.
        # Ambiguous 'What happened?' can now correctly ask a conversational clarification.
        from dialogue import answer as dialogue_answer, FIELDS
        intent = {field: '' for field in FIELDS}
        intent.update(action='archive',day='2000-01-01',query='What was recorded on this day?',shift_minutes=0)
        with patch('dialogue.answer', side_effect=lambda archive,day,question,session: dialogue_answer(archive,day,question,session,planner=lambda *args:intent)):
            status,result=post({'question':'What was recorded on this day?','day':'2000-01-01'})
        self.assertEqual(status,200);self.assertTrue(result['insufficient_evidence'])

    def test_command_audio_requires_auth_and_never_creates_archive_entries(self):
        def send(token,content_type='audio/pcm;rate=16000;channels=1;format=s16le'):
            req=urllib.request.Request(self.url+'/transcribe-command',data=bytes(3200),headers={'Authorization':'Bearer '+token,'Content-Type':content_type})
            try:
                with urllib.request.urlopen(req) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
        self.assertEqual(send('bad')[0],401)
        self.assertEqual(send('test-token','audio/wav')[0],400)
        status,body=send('test-token')
        self.assertEqual(status,200);self.assertEqual(body['text'],'')
        self.assertFalse(self.archive.search(''))


if __name__ == '__main__':
    unittest.main()
