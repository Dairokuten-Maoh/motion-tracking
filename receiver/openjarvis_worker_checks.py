"""Run in the isolated OpenJarvis environment; engine replies are deterministic."""
import json
import unittest
from unittest.mock import patch
import openjarvis_worker
from openjarvis.engine.ollama import OllamaEngine


class WorkerChecks(unittest.TestCase):
    def payload(self):
        fields='action title day start end query reply shift_minutes start_evidence end_evidence date_evidence'.split()
        properties={k:{'type':'string'} for k in fields};properties['shift_minutes']={'type':'integer'}
        return dict(model='unused',question='Find the weather',history=[],day='2026-09-25',
                    now='2026-09-25T12:00:00+08:00',schema={'type':'object','properties':properties,'required':fields,'additionalProperties':False})
    def call(self,query='weather'):
        return {'name':'request_action','arguments':json.dumps({'action':'web','query':query})}

    def test_unused_arguments_get_safe_defaults(self):
        replies=[{'content':'','tool_calls':[self.call()], 'usage':{'prompt_tokens_evaluated':12,'completion_tokens':3}},
                 {'content':'Proposal ready.','usage':{'prompt_tokens_evaluated':15,'completion_tokens':2}}]
        with patch.object(OllamaEngine,'generate',side_effect=replies):output=openjarvis_worker.run(self.payload())
        self.assertEqual(output['intent']['action'],'web')
        self.assertEqual(output['intent']['shift_minutes'],0)
        self.assertEqual(output['intent']['start'],'')
        self.assertEqual(output['metrics']['prompt_tokens'],27)
        self.assertEqual(output['metrics']['calls'],2)

    def test_multiple_proposals_are_not_executed(self):
        with patch.object(OllamaEngine,'generate',side_effect=[{'content':'','tool_calls':[self.call(),self.call('news')]},{'content':'Ready'}]):
            output=openjarvis_worker.run(self.payload())
        self.assertIn('Multiple',output['error'])
        self.assertNotIn('intent',output)

    def test_empty_answer_is_failure(self):
        with patch.object(OllamaEngine,'generate',return_value={'content':''}):output=openjarvis_worker.run(self.payload())
        self.assertIn('no answer',output['error'])

    def test_continuation_cannot_exceed_call_budget(self):
        with patch.object(OllamaEngine,'generate',return_value={'content':'unfinished','finish_reason':'length'}):
            with self.assertRaisesRegex(RuntimeError,'budget'):openjarvis_worker.run(self.payload())


if __name__=='__main__':unittest.main()
