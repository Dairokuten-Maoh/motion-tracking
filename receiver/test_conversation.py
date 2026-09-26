import copy
from datetime import datetime
import tempfile
import time
import unittest
import uuid
from conversation import ask,select_sources,validate,INFERENCE,BusyError
from server import Archive,TAIPEI
from test_server import audio


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name)
        self.clip=str(uuid.uuid4());self.started=time.time()
        self.archive.ingest(self.clip,self.started,audio())
        with self.archive.connect() as db:db.execute("UPDATE recordings SET state='done',transcript='Testing English. 明天三點開會。' WHERE id=?",(self.clip,))
        self.day=datetime.fromtimestamp(self.started,TAIPEI).strftime('%Y-%m-%d')
        self.result={'answer':'A recording contains an English test phrase.','insufficient_evidence':False,'citations':[{'source_id':self.clip,'quote':'Testing English.'}]}
    def tearDown(self):self.temp.cleanup()
    def test_answer_has_source_time_and_coverage(self):
        result=ask(self.archive,self.day,'What English phrase?',lambda *args:copy.deepcopy(self.result))
        self.assertEqual(result['citations'][0]['started'],self.started)
        self.assertEqual(result['coverage']['total_clips'],1)
        self.assertFalse(result['coverage']['partial'])
    def test_fabricated_evidence_is_replaced_by_uncertainty(self):
        self.result['citations'][0]['quote']='Invented promise'
        result=ask(self.archive,self.day,'What was promised?',lambda *args:self.result)
        self.assertTrue(result['insufficient_evidence']);self.assertEqual(result['citations'],[])
        self.assertNotIn('Invented promise',result['answer'])
    def test_unsupported_confident_answer_rejected(self):
        self.result['citations']=[]
        result=ask(self.archive,self.day,'Who spoke?',lambda *args:self.result)
        self.assertTrue(result['insufficient_evidence'])
    def test_empty_date_does_not_invoke_model(self):
        def unexpected(*args):raise AssertionError('Model should not be called')
        result=ask(self.archive,'2000-01-01','What happened?',unexpected)
        self.assertTrue(result['insufficient_evidence']);self.assertEqual(result['coverage']['total_clips'],0)
    def test_partial_context_is_explicit(self):
        with self.archive.connect() as db:db.execute('UPDATE recordings SET transcript=?',('meeting '*2000,))
        sources,coverage=select_sources(self.archive,self.day,'meeting',budget=2400)
        self.assertTrue(coverage['partial']);self.assertLessEqual(sum(len(s['transcript']) for s in sources),2400)
    def test_only_selected_date_and_source_excerpt_can_be_cited(self):
        sources,_=select_sources(self.archive,self.day,'English')
        self.result['citations'][0]['source_id']='nonexistent'
        with self.assertRaises(ValueError):validate(self.result,sources)
    def test_concurrent_question_fails_without_invoking_model(self):
        INFERENCE.acquire()
        try:
            with self.assertRaises(BusyError):ask(self.archive,self.day,'Hello')
        finally:INFERENCE.release()
    def test_bad_question_and_date_rejected(self):
        for question in [None,'','x'*1001]:
            with self.assertRaises(ValueError):ask(self.archive,self.day,question)
        with self.assertRaises(ValueError):ask(self.archive,'not a date','Hello')
