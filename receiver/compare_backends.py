"""Live local-model comparison with synthetic history and a fake calendar.

No Google, web, archive, or messaging service is contacted. Reports contain only
the synthetic cases below. Both planners share the same execution validations.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import dialogue
import openjarvis_bridge
from server import Archive, TAIPEI


class Calendar:
    def __init__(self): self.items=[]; self.calls=[]
    def events(self, day):
        self.calls.append(('LIST', day, {}))
        return [e for e in self.items if e['start']['dateTime'][:10] == day]
    def request(self, method, path='', **kwargs):
        self.calls.append((method, path, kwargs))
        if method == 'POST':
            event=dict(kwargs['body'], etag='v1', organizer={'self':True})
            self.items.append(event); return event
        event=next(e for e in self.items if path.endswith(e['id']))
        if method == 'GET': return event
        if method == 'PATCH': event.update(kwargs['body']);event['etag']='v2'
        if method == 'DELETE': self.items.remove(event)
        return {}


def main():
    day=datetime.now(TAIPEI).date().isoformat()
    tomorrow=(datetime.now(TAIPEI).date()+timedelta(days=1)).isoformat()
    yesterday=(datetime.now(TAIPEI).date()-timedelta(days=1)).isoformat()
    scenarios=[
        [('My girlfriend just broke up with me.','chat'),("I feel lost. Can we just talk?",'chat')],
        [('Put lunch with Alex tomorrow at noon for an hour.','create'),
         ('Actually move it an hour later.','move'),('Cancel it.','delete')],
        [('Book dentist tomorrow.','clarify')],
        [("Do not cancel dentist tomorrow.",'negated')],
        [('Look up the latest Taipei weather.','web')],
        [('What did I talk about in my recordings yesterday?','archive')],
        [('Repeat the words Jarvis test.','repeat')],
    ]
    report={'day':day,'revision':openjarvis_bridge.REVISION,'cases':[]}
    for index, scenario in enumerate(scenarios):
        for backend, planner in [('current',dialogue.plan),('openjarvis',openjarvis_bridge.plan)]:
            with tempfile.TemporaryDirectory() as temporary:
                archive=Archive(temporary); calendar=Calendar()
                for question, expected in scenario:
                    metrics={}; proposed={}; routed=[]; error=None
                    def measured(q,h,d):
                        intent=planner(q,h,d,metrics=metrics); proposed.update(intent);return intent
                    def web(q): routed.append(('web',q));return dialogue.result('Synthetic weather result.','web')
                    def recall(a,d,q): routed.append(('archive',d));return dialogue.result('Synthetic archive result.','archive')
                    previous=len(calendar.calls); start=time.monotonic()
                    try:
                        with patch('dialogue.web_answer',web),patch('dialogue.archive_answer',recall):
                            response=dialogue.answer(archive,day,question,session='evaluation',planner=measured,calendar_factory=lambda _:calendar)
                    except Exception as exc:
                        response={'answer':''};error=f'{type(exc).__name__}: {exc}'
                    calls=calendar.calls[previous:]
                    writes=[c for c in calls if c[0] in ('POST','PATCH','DELETE')]
                    ok=bool(response['answer']) and not error and 'rephrase' not in response['answer'].lower()
                    if expected in ('chat','clarify','negated','repeat'):ok &= not writes and not routed and not calls
                    if expected=='chat':ok &= proposed.get('action') in ('chat','clarify')
                    if expected=='repeat':ok &= response['answer']=='Jarvis test' and not metrics
                    if expected in ('create','move'):
                        hour=12 if expected=='create' else 13; method='POST' if expected=='create' else 'PATCH'
                        ok &= len(writes)==1 and writes[0][0]==method
                        if ok:
                            body=writes[0][2]['body']
                            ok &= body['start']['dateTime']==f'{tomorrow}T{hour:02}:00:00+08:00'
                            ok &= body['end']['dateTime']==f'{tomorrow}T{hour+1:02}:00:00+08:00'
                    if expected=='delete':ok &= len(writes)==1 and writes[0][0]=='DELETE'
                    if expected=='web':ok &= len(routed)==1 and routed[0][0]=='web' and not writes
                    if expected=='archive':ok &= routed==[('archive',yesterday)] and not writes
                    row=dict(backend=backend,scenario=index,question=question,expected=expected,passed=bool(ok),
                        reply=response['answer'],intent=proposed,metrics=metrics,error=error,seconds=round(time.monotonic()-start,3))
                    report['cases'].append(row)
                    print(backend,expected,'PASS' if ok else 'FAIL',metrics,flush=True)
                    path=Path('jarvis-data/openjarvis-comparison.json')
                    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':main()
