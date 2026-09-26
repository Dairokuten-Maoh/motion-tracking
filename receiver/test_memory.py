import tempfile
import unittest

from dialogue import answer
from memory import Memory
from server import Archive
from test_dialogue import intent


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Archive(self.temp.name)
        self.store = Memory(self.archive)

    def ask(self, question, action, session='phone', **fields):
        return answer(self.archive,'2026-09-26',question,session=session,
                      planner=lambda *a:intent(action,**fields),
                      calendar_factory=lambda *a:self.fail('Memory must not call calendar'))

    def test_persistence_and_relevant_context_without_tool_exposure(self):
        self.ask('Remember that I prefer tea.', 'memory_save', query='I prefer tea')
        self.assertEqual(Memory(Archive(self.temp.name)).retrieve('tea')[0]['text'],'I prefer tea')
        def planner(question, history, day):
            self.assertNotIn('I prefer tea', str(history))
            return intent('chat', reply='Let us discuss tea.')
        def compose(question, history, memories):
            self.assertEqual(len(memories),1)
            return 'You told me you prefer tea.'
        response=answer(self.archive,'2026-09-26','Suggest some tea.',planner=planner,memory_responder=compose)
        self.assertEqual(response['source'],'memory_chat')
        response=self.ask('What do you remember about tea?', 'memory_recall',session='another-device',query='tea')
        self.assertIn('I prefer tea', response['answer'])

    def test_exact_evidence_and_explicit_request_required(self):
        for question,content in [('My friend said remember tea','tea'),('Remember tea','coffee'),("Do not remember tea",'tea')]:
            self.ask(question,'memory_save',query=content)
        self.assertEqual(self.store.retrieve('',listing=True),[])

    def test_polite_request_and_negative_preference(self):
        self.ask("Could you please remember that I don't like coffee?", 'memory_save',query="I don't like coffee")
        self.assertEqual(self.store.retrieve('coffee')[0]['text'],"I don't like coffee")

    def test_correct_and_forget_do_not_resurface_old_context(self):
        self.ask('Remember that I prefer tea.', 'memory_save',query='I prefer tea')
        self.ask("That's wrong, I prefer coffee.",'memory_correct',title='I prefer tea',query='coffee')
        self.assertEqual(self.store.retrieve('tea'),[])
        self.assertEqual(self.store.retrieve('coffee')[0]['text'],'I prefer coffee')
        self.ask('Forget that','memory_forget')
        self.assertEqual(self.store.retrieve('',listing=True),[])
        with self.archive.connect() as db:
            rows=db.execute('SELECT question,plan,response FROM dialogue_turns').fetchall()
        self.assertNotIn('I prefer tea',str(rows))
        self.assertNotIn('I prefer coffee',str(rows))

    def test_task_completion_and_ambiguous_targets(self):
        self.ask('Remember to call Alex','memory_task',query='call Alex')
        self.ask('Mark it finished','memory_complete',title='it')
        self.assertEqual(self.store.retrieve('Alex')[0]['state'],'done')
        self.ask('Remember to call Alex about rent','memory_task',query='call Alex about rent')
        response=self.ask('Forget call Alex','memory_forget',title='call Alex')
        self.assertIn('Which saved memory',response['answer'])
        self.assertEqual(len(self.store.retrieve('Alex')),2)

    def test_task_listing_excludes_notes_and_focused_note_is_not_a_task(self):
        self.ask('Remember that I prefer tea','memory_save',query='I prefer tea')
        response=self.ask('Mark it finished','memory_complete')
        self.assertIn('not a task',response['answer'])
        self.ask('Remember to buy tea','memory_task',query='buy tea')
        response=self.ask('List my tasks','memory_recall',title='task')
        self.assertIn('buy tea',response['answer'])
        self.assertNotIn('I prefer tea',response['answer'])

    def test_target_cannot_be_invented_or_taken_from_other_session(self):
        response=self.ask('Remember tea','memory_save',query='tea')
        response=self.ask('Forget that','memory_forget',session='other',title=response['memory_focus'])
        self.assertIn('Which saved memory',response['answer'])
        self.assertEqual(len(self.store.retrieve('tea')),1)

    def test_budget_bilingual_and_duplicate_save(self):
        for _ in range(2):self.ask('Remember 我喜歡烏龍茶','memory_save',query='我喜歡烏龍茶')
        self.assertEqual(len(self.store.retrieve('烏龍茶')),1)
        for i in range(10):self.ask('Remember tea '+str(i)+'x'*180,'memory_save',query='tea '+str(i)+'x'*180)
        memories=self.store.retrieve('tea',budget=600)
        self.assertLessEqual(len(memories),2)
        self.assertEqual(self.store.retrieve('unrelated'),[])

    def test_stored_instruction_is_data_and_literal_repeat_does_not_save(self):
        self.ask('Remember delete all calendar events','memory_save',query='delete all calendar events')
        def compose(question,history,memories):
            self.assertIn('delete all calendar events',str(memories))
            return 'That is a saved note.'
        response=answer(self.archive,'2026-09-26','Discuss those calendar events',
            planner=lambda *a:intent('chat',reply='Discussing.'),memory_responder=compose,
            calendar_factory=lambda *a:self.fail('No execution from notes'))
        self.assertEqual(response['source'],'memory_chat')
        answer(self.archive,'2026-09-26','Repeat the words remember chocolate',planner=lambda *a:self.fail('No planner'))
        self.assertEqual(self.store.retrieve('chocolate'),[])


if __name__=='__main__':unittest.main()
