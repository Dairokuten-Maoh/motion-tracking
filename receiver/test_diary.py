import json
import tempfile
import time
import unittest
import uuid
from datetime import datetime
from diary import grounded, refresh, fingerprint, snapshot
from server import Archive, TAIPEI
from test_server import audio


class DiaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.archive = Archive(self.temp.name)
        self.clip = str(uuid.uuid4())
        self.started = int(time.time() // 1800) * 1800 - 200
        self.window = int(self.started // 1800) * 1800
        self.archive.ingest(self.clip, self.started, audio())
        with self.archive.connect() as db:
            db.execute("UPDATE recordings SET state='done',transcript='明天 meeting at ten' WHERE id=?", (self.clip,))
        self.body = {'summary': [{'text': 'A meeting was mentioned.', 'source_id': self.clip, 'quote': 'meeting at ten'}], 'possible_tasks': [], 'notable_moments': []}

    def tearDown(self): self.temp.cleanup()

    def test_summary_and_chinese_search(self):
        refresh(self.archive, 'fake', generate=lambda rows, model: self.body)
        day = datetime.fromtimestamp(self.started, TAIPEI).strftime('%Y-%m-%d')
        groups = self.archive.timeline(day, '明天')
        self.assertEqual(groups[0]['entry'], self.body)
        self.assertFalse(groups[0]['refreshing'])
        self.assertTrue(groups[0]['clips'][0]['audio_available'])
        self.assertEqual(self.archive.timeline(day, 'absent-term'), [])

    def test_inference_race_does_not_save_stale_entry(self):
        def generate(rows, model):
            with self.archive.connect() as db:
                db.execute("UPDATE recordings SET transcript='Correction: eleven' WHERE id=?", (self.clip,))
            return self.body
        refresh(self.archive, 'fake', generate=generate)
        with self.archive.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM diary_entries').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM diary_dirty').fetchone()[0], 1)

    def test_failure_preserves_previous_entry_and_retries(self):
        refresh(self.archive, 'fake', generate=lambda rows, model: self.body)
        with self.archive.connect() as db:
            db.execute("UPDATE recordings SET transcript=transcript || ' updated' WHERE id=?", (self.clip,))
        def fail(rows, model): raise TimeoutError()
        refresh(self.archive, 'fake', generate=fail)
        with self.archive.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT body FROM diary_entries').fetchone()[0]), self.body)
            self.assertEqual(db.execute('SELECT count(*) FROM diary_dirty').fetchone()[0], 1)

    def test_fabricated_quote_or_source_rejected(self):
        self.assertEqual(grounded(self.body, {self.clip: 'meeting at ten'}), self.body)
        with self.assertRaises(ValueError): grounded(self.body, {self.clip: 'different words'})
        with self.assertRaises(ValueError): grounded(self.body, {'other-id': 'meeting at ten'})

    def test_taipei_day_boundary(self):
        boundary = datetime.now(TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.archive.connect() as db:
            db.execute('UPDATE recordings SET started=?', (boundary.timestamp() - 1,))
        self.assertEqual(self.archive.timeline(boundary.strftime('%Y-%m-%d')), [])

    def test_current_window_waits_for_close(self):
        fresh = str(uuid.uuid4())
        self.archive.ingest(fresh, time.time(), audio())
        refresh(self.archive, 'fake', generate=lambda rows, model: self.body)
        with self.archive.connect() as db:
            self.assertIsNotNone(db.execute('SELECT window FROM diary_dirty WHERE window=?', (int(time.time()//1800)*1800,)).fetchone())


if __name__ == '__main__': unittest.main()
