"""Bounded process boundary to the pinned OpenJarvis candidate planner.

Existing dialogue execution remains the single owner of validation and effects.
The worker has no archive or credential inputs and only proposes an action.
"""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time
from gpu_slot import inference_slot

ROOT = Path(__file__).resolve().parent.parent
REVISION = '309a4f1044ccfb2032264832a31fef2f1d314586'


def plan(question, history, day, metrics=None):
    from dialogue import SCHEMA, validate
    from conversation import MODEL
    from server import TAIPEI
    payload = dict(question=question, history=history, day=day,
                   now=datetime.now(TAIPEI).isoformat(), schema=SCHEMA, model=MODEL)
    started = time.monotonic()
    with inference_slot():
        try:
            process = subprocess.run([str(ROOT / '.tools/openjarvis-env/Scripts/python.exe'),
                str(ROOT / 'receiver/openjarvis_worker.py')], input=json.dumps(payload),
                encoding='utf-8', capture_output=True, cwd=ROOT, timeout=145,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('OpenJarvis timed out; no action was executed') from exc
    if process.returncode != 0:
        raise RuntimeError('OpenJarvis candidate failed; no action was executed')
    output = json.loads(process.stdout)
    if metrics is not None:
        metrics.update(output['metrics'])
        metrics['wall_seconds'] = round(time.monotonic()-started, 3)
        metrics['revision'] = REVISION
    if output.get('error'):raise RuntimeError(output['error'])
    return validate(output['intent'])
