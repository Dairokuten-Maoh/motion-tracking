import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import gpu_slot


class PriorityTests(unittest.TestCase):
    def test_background_yields_across_processes_and_resumes_after_quiet_period(self):
        code = '''import sys
from pathlib import Path
import gpu_slot
gpu_slot.ROOT=Path(sys.argv[1])
try:
 with gpu_slot.inference_slot(timeout=.1,background=True):print('acquired')
except gpu_slot.BackgroundDeferred:print('deferred')
'''
        with tempfile.TemporaryDirectory() as folder, patch('gpu_slot.ROOT',Path(folder)):
            def attempt():
                return subprocess.check_output([sys.executable,'-c',code,folder],cwd=Path(__file__).parent,text=True,timeout=5).strip()
            with gpu_slot.interactive_activity():
                self.assertEqual(attempt(),'deferred')
                with gpu_slot.inference_slot(timeout=.1):pass
            self.assertEqual(attempt(),'deferred')
            os.utime(Path(folder)/'last-interaction',(time.time()-31,)*2)
            self.assertEqual(attempt(),'acquired')

    def test_crashed_marker_expires_and_exception_releases_reservation(self):
        with tempfile.TemporaryDirectory() as folder, patch('gpu_slot.ROOT',Path(folder)):
            with self.assertRaises(ValueError):
                with gpu_slot.interactive_activity():raise ValueError()
            self.assertFalse(list((Path(folder)/'interactive').iterdir()))
            (Path(folder)/'last-interaction').unlink()
            marker=Path(folder)/'interactive'/'stale'
            marker.touch();os.utime(marker,(time.time()-601,)*2)
            self.assertFalse(gpu_slot.interactive_pending())
            self.assertFalse(marker.exists())
