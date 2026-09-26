import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import dialogue
import openjarvis_bridge as bridge
from server import Archive
from test_dialogue import intent


class BridgeTests(unittest.TestCase):
    def test_validated_proposal_and_metrics_cross_process_boundary(self):
        output={'intent':intent('chat',reply='Hello.'),'metrics':{'calls':1,'prompt_tokens':20,'completion_tokens':3}}
        with patch('openjarvis_bridge.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(output),'')) as run:
            metrics={}
            self.assertEqual(bridge.plan('Hello',[],'2026-09-25',metrics)['reply'],'Hello.')
            self.assertEqual(metrics['calls'],1)
            self.assertNotIn('Hello',run.call_args.args[0])
            self.assertEqual(json.loads(run.call_args.kwargs['input'])['question'],'Hello')

    def test_invalid_candidate_never_reaches_calendar(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Archive(folder)
            output={'intent':intent('shell'),'metrics':{}}
            with patch('openjarvis_bridge.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(output),'')):
                response=dialogue.answer(archive,'2026-09-25','Do something',planner=bridge.plan,
                    calendar_factory=lambda _:self.fail('Invalid proposal executed'))
                self.assertIn('rephrase',response['answer'])

    def test_timeout_does_not_retry_or_use_another_backend(self):
        with patch('openjarvis_bridge.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',145)) as run:
            with self.assertRaisesRegex(RuntimeError,'no action'):
                bridge.plan('Cancel lunch',[],'2026-09-25')
            self.assertEqual(run.call_count,1)

    def test_backend_switch_is_explicit_and_reversible(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertIs(dialogue.configured_planner(root),dialogue.plan)
            config=root/'agent-backend.json'
            config.write_text('{"backend":"openjarvis"}')
            self.assertIs(dialogue.configured_planner(root),bridge.plan)
            config.write_text('{"backend":"current"}')
            self.assertIs(dialogue.configured_planner(root),dialogue.plan)
            config.write_text('{"backend":"unknown"}')
            with self.assertRaises(ValueError):dialogue.configured_planner(root)


if __name__=='__main__':unittest.main()
