from datetime import date
import tempfile
import unittest
from google_calendar import parse, execute, answer, CalendarUnavailable
from server import Archive

class Fake:
    def __init__(self, events=()): self.items=list(events);self.calls=[];self.conflict=False;self.fail=False
    def events(self, day): return self.items
    def request(self, method, path='', **kwargs):
        self.calls.append((method,path,kwargs))
        if self.fail: raise OSError('network interrupted')
        if method=='POST' and self.conflict:return {'conflict':True}
        if method=='GET':return self.items[0]
        return {}

class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name);self.today=date(2026,9,25)
    def tearDown(self):self.temp.cleanup()
    def command(self,text):return parse(text,self.today)
    def event(self,**kw):return dict(id='event1',summary='dentist',etag='tag1',organizer={'self':True},**kw)
    def test_archive_question_does_not_route(self):self.assertIsNone(answer(self.archive,'What did I say today?'))
    def test_parse_english_voice_time_and_tomorrow(self):
        c=self.command('Add dentist to my calendar tomorrow from three pm to four pm.')
        self.assertEqual(c['start'],'2026-09-26T15:00:00+08:00')
    def test_ambiguous_or_reversed_time_does_not_execute(self):
        for question in ['Add dentist to my calendar tomorrow from 3 to 4', 'Add dentist to my calendar tomorrow from 4 pm to 3 pm','Add dentist to my calendar']:
            with self.assertRaises(ValueError):self.command(question)
    def test_no_auth_gives_clear_answer(self):
        self.assertIn('not connected',answer(self.archive,'Show my calendar tomorrow')['answer'])
    def test_create_retry_reuses_id_after_unknown_network_result(self):
        c=self.command('Add dentist to my calendar tomorrow from 3 pm to 4 pm');f=Fake();f.fail=True
        with self.assertRaises(OSError):execute(self.archive,c,f)
        event_id=f.calls[-1][2]['body']['id'];f.fail=False
        execute(self.archive,c,f)
        self.assertEqual(event_id,f.calls[-1][2]['body']['id'])
        self.assertEqual(f.calls[-1][2]['params']['sendUpdates'],'none')
    def test_duplicate_title_never_deletes(self):
        f=Fake([self.event(),self.event()]);result=execute(self.archive,self.command('Cancel dentist on my calendar tomorrow'),f)
        self.assertIn('2 exact matches',result);self.assertEqual(f.calls,[])
    def test_guests_and_recurring_never_mutate(self):
        for event in [self.event(attendees=[{'email':'someone@example.com'}]),self.event(recurringEventId='series')]:
            f=Fake([event]);execute(self.archive,self.command('Cancel dentist on my calendar tomorrow'),f);self.assertEqual(f.calls,[])
    def test_move_preserves_other_fields_and_uses_etag(self):
        f=Fake([self.event()]);execute(self.archive,self.command('Move dentist on my calendar tomorrow to 5 pm until 6 pm'),f)
        method,path,kwargs=f.calls[-1]
        self.assertEqual(method,'PATCH');self.assertEqual(kwargs['etag'],'tag1');self.assertEqual(set(kwargs['body']),{'start','end'})
    def test_delete_unique_owned_event(self):
        f=Fake([self.event()]);execute(self.archive,self.command('Cancel dentist on my calendar tomorrow'),f)
        self.assertEqual(f.calls[-1][0],'DELETE')
    def test_empty_calendar(self):
        self.assertIn('no events',execute(self.archive,self.command('Show my calendar today'),Fake()))
    def test_deleted_creation_is_not_reported_as_existing(self):
        f=Fake([{'status':'cancelled'}]);f.conflict=True
        result=execute(self.archive,self.command('Add dentist to my calendar tomorrow from 3 pm to 4 pm'),f)
        self.assertIn('did not create a duplicate',result)

if __name__=='__main__':unittest.main()
