import copy
import tempfile
import unittest
from dialogue import answer,calendar,validate
from server import Archive
from test_google_calendar import Fake

def intent(action='clarify',**kwargs):
    result=dict(action=action,title='',day='',start='',end='',query='',reply='Which date?',shift_minutes=0,start_evidence='',end_evidence='',date_evidence='tomorrow')
    result.update(kwargs);return result

class DialogueTests(unittest.TestCase):
    def test_literal_repeat_bypasses_planner_and_tools(self):
        for text,expected in [('Repeat the word Jarvis test.','Jarvis test'),('Please repeat the words cancel my calendar event.','cancel my calendar event')]:
            r=answer(self.archive,'2026-09-25',text,planner=lambda *args:self.fail('Literal repetition needs no model'),calendar_factory=lambda *args:self.fail('Do not execute repeated words'))
            self.assertEqual(r['answer'],expected)
            self.assertEqual(r['source'],'conversation')
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def event(self):return {'id':'e1','summary':'Dentist visit','etag':'tag','organizer':{'self':True},'start':{'dateTime':'2026-09-26T15:00:00+08:00'},'end':{'dateTime':'2026-09-26T16:00:00+08:00'}}
    def test_recent_context_is_passed_to_followup(self):
        answer(self.archive,'2026-09-25','Book lunch tomorrow',planner=lambda *a:intent(reply='At what time?'))
        def follow(q,h,d):
            self.assertEqual(h[0]['user'],'Book lunch tomorrow')
            self.assertEqual(h[0]['result']['answer'],'At what time?')
            return intent(reply='For how long?')
        answer(self.archive,'2026-09-25','At noon',planner=follow)
    def test_sessions_do_not_share_history(self):
        answer(self.archive,'2026-09-25','Hello',session='phone',planner=lambda *a:intent('chat',reply='Hello'))
        def other(q,h,d):self.assertEqual(h,[]);return intent()
        answer(self.archive,'2026-09-25','Hello',session='web-1',planner=other)
    def test_new_conversation_clears_active_context(self):
        answer(self.archive,'2026-09-25','Hello',planner=lambda *a:intent())
        answer(self.archive,'2026-09-25','New conversation')
        def check(q,h,d):self.assertEqual(h,[]);return intent()
        answer(self.archive,'2026-09-25','Hello',planner=check)
    def test_shift_uses_actual_duration(self):
        f=Fake([self.event()]);r=calendar(self.archive,intent('calendar_move',day='2026-09-26',title='dentist',shift_minutes=60),lambda p:f)
        self.assertEqual(f.calls[-1][2]['body']['start']['dateTime'],'2026-09-26T16:00:00+08:00')
        self.assertEqual(f.calls[-1][2]['body']['end']['dateTime'],'2026-09-26T17:00:00+08:00')
        self.assertEqual(r['focus']['title'],'Dentist visit')
    def test_move_to_another_day_preserves_duration_and_updates_focus(self):
        f=Fake([self.event()]);r=calendar(self.archive,intent('calendar_move',day='2026-09-26',title='dentist',start='2026-09-28T10:00:00+08:00'),lambda p:f)
        self.assertEqual(r['focus']['day'],'2026-09-28')
        self.assertEqual(f.calls[-1][2]['body']['end']['dateTime'],'2026-09-28T11:00:00+08:00')
    def test_close_match_asks_without_editing(self):
        event=self.event();event['summary']='Jarvis tear';f=Fake([event])
        r=calendar(self.archive,intent('calendar_delete',day='2026-09-26',title='Jarvis test'),lambda p:f)
        self.assertIn('Jarvis tear',r['answer']);self.assertEqual(f.calls,[])
    def test_multiple_matches_ask_without_editing(self):
        second=self.event();second['id']='e2';second['summary']='Dentist checkup'
        f=Fake([self.event(),second]);r=calendar(self.archive,intent('calendar_delete',day='2026-09-26',title='dentist'),lambda p:f)
        self.assertIn('Which event',r['answer']);self.assertEqual(f.calls,[])
    def test_missing_create_duration_does_not_access_google(self):
        r=calendar(self.archive,intent('calendar_create',day='2026-09-26',title='Lunch',start='2026-09-26T12:00:00+08:00'),lambda p:self.fail('No access needed'))
        self.assertIn('start and end',r['answer'])
    def test_invalid_plan_cannot_invoke_tools(self):
        r=answer(self.archive,'2026-09-25','hello',planner=lambda *a:intent('shell'))
        self.assertIn('rephrase',r['answer'])
    def test_wrong_timezone_rejected(self):
        with self.assertRaises(ValueError):validate(intent('calendar_create',start='2026-09-26T12:00:00'))
    def test_invented_time_blocked_even_when_plan_has_valid_dates(self):
        r=answer(self.archive,'2026-09-25','Book dentist tomorrow',planner=lambda *a:intent('calendar_create',title='dentist',day='2026-09-26',start='2026-09-26T00:00:00+08:00',end='2026-09-26T01:00:00+08:00'),calendar_factory=lambda p:self.fail('Must not contact Google'))
        self.assertIn('What time',r['answer'])
    def test_negated_edit_blocked_even_when_model_proposes_delete(self):
        r=answer(self.archive,'2026-09-25','Do not cancel dentist',planner=lambda *a:intent('calendar_delete',title='dentist',day='2026-09-26'),calendar_factory=lambda p:self.fail('Must not contact Google'))
        self.assertIn('not changed',r['answer'])
    def test_invented_date_blocked(self):
        r=answer(self.archive,'2026-09-25','Cancel dentist',planner=lambda *a:intent('calendar_delete',title='dentist',day='2026-09-26',date_evidence='tomorrow'),calendar_factory=lambda p:self.fail('Must not contact Google'))
        self.assertIn('Which date',r['answer'])
    def test_yes_resolves_only_the_last_suggested_candidate(self):
        event=self.event();event['summary']='Jarvis tear';f=Fake([event])
        answer(self.archive,'2026-09-25','Cancel Jarvis test tomorrow',planner=lambda *a:intent('calendar_delete',title='Jarvis test',day='2026-09-26'),calendar_factory=lambda p:f)
        r=answer(self.archive,'2026-09-25','Yes, that one',planner=lambda *a:self.fail('Selection must be deterministic'),calendar_factory=lambda p:f)
        self.assertEqual(f.calls[-1][0],'DELETE');self.assertIn('Cancelled Jarvis tear',r['answer'])
    def test_concurrent_event_change_rejected(self):
        class Changed(Fake):
            def events(self,day):
                result=copy.deepcopy(self.items);self.items[0]['etag']='new';return result
        f=Changed([self.event()]);r=calendar(self.archive,intent('calendar_move',day='2026-09-26',title='dentist',shift_minutes=60),lambda p:f)
        self.assertIn('changed',r['answer']);self.assertEqual(f.calls,[])

if __name__=='__main__':unittest.main()
