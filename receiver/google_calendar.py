"""Primary-calendar commands. Only explicit requests reach Google; archive text never does.

Owns command validation, OAuth refresh, exact event selection, and durable create IDs.
Times are Asia/Taipei. No attendees or recurring-event edits are supported yet.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import quote
from server import TAIPEI

SCOPE = 'https://www.googleapis.com/auth/calendar.events.owned'
LOCK = threading.Lock()
HELP = ('Try: Show my calendar tomorrow. Add dentist to my calendar tomorrow from 3 pm to 4 pm. '
        'Move dentist on my calendar tomorrow to 5 pm until 6 pm. Cancel dentist on my calendar tomorrow. '
        'Use today, tomorrow, or a date such as 2026-09-28. Times use Taipei time.')
DATE = r'(today|tomorrow|\d{4}-\d{2}-\d{2})'


def clock(value):
    value = value.lower().strip().replace('.', '')
    numbers = ['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve']
    for number, word in reversed(list(enumerate(numbers))):
        value = re.sub(r'\b' + word + r'\b', str(number), value)
    match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', value)
    if not match or not 1 <= int(match[1]) <= 12 or int(match[2] or 0) > 59:
        raise ValueError('Include AM or PM and a time such as 3 pm or 3:30 pm.')
    return int(match[1]) % 12 + (12 if match[3] == 'pm' else 0), int(match[2] or 0)


def parse(question, today):
    """Return None for archive questions; reject unclear calendar requests without guessing."""
    if not re.search(r'\bcalendar\b', question, re.I): return None
    text = re.sub(r'\s+', ' ', question.strip().rstrip('.?!')).lower()
    text = re.sub(r'^please ', '', text)
    match = re.fullmatch(r'(?:show|check|read)(?: me)? my calendar(?: for)? ' + DATE, text)
    action = 'list'
    if not match:
        match = re.fullmatch(r'(?:what is|what\'s|whats) on my calendar(?: for)? ' + DATE, text)
    if match:
        title, date, start, end = '', match[1], None, None
    else:
        match = re.fullmatch(r'(?:add|create) (.{1,200}?) (?:to|on) my calendar(?: for)? ' + DATE + r' from (.+?) (?:to|until) (.+)', text)
        action = 'create'
        if not match:
            match = re.fullmatch(r'move (.{1,200}?) on my calendar(?: for)? ' + DATE + r' to (.+?) until (.+)', text)
            action = 'move'
        if match: title, date, start, end = match.groups()
        else:
            match = re.fullmatch(r'(?:cancel|delete|remove) (.{1,200}?) (?:on|from) my calendar(?: for)? ' + DATE, text)
            if not match: raise ValueError(HELP)
            action = 'delete'; title, date = match.groups(); start = end = None
    day = today if date == 'today' else today + timedelta(days=1) if date == 'tomorrow' else datetime.strptime(date, '%Y-%m-%d').date()
    command = {'action': action, 'title': title, 'day': day.isoformat()}
    if start:
        base = datetime.combine(day, datetime.min.time(), TAIPEI)
        hour, minute = clock(start); begin = base.replace(hour=hour, minute=minute)
        hour, minute = clock(end); finish = base.replace(hour=hour, minute=minute)
        if finish <= begin: raise ValueError('The end time must be later than the start time on the same day.')
        command.update(start=begin.isoformat(), end=finish.isoformat())
    return command


class CalendarUnavailable(Exception): pass


class GoogleCalendar:
    def __init__(self, root):
        self.token = Path(root) / 'google-calendar-token.json'
        if not self.token.exists(): raise CalendarUnavailable('Google Calendar is not connected yet. Complete Google sign-in on the PC first.')
        import truststore
        truststore.inject_into_ssl()
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import AuthorizedSession
        self.credentials = Credentials.from_authorized_user_file(str(self.token), scopes=[SCOPE])
        self.session = AuthorizedSession(self.credentials)

    def request(self, method, path='', *, params=None, body=None, etag=None):
        try:
            response = self.session.request(method, 'https://www.googleapis.com/calendar/v3/calendars/primary/events' + path,
                params=params, json=body, headers={'If-Match': etag} if etag else {}, timeout=25)
            if response.status_code == 409 and method == 'POST': return {'conflict': True}
            if not response.ok: raise CalendarUnavailable('Google Calendar could not complete the request. Check the calendar before repeating an edit.')
            return response.json() if response.content else {}
        finally:
            temporary = self.token.with_suffix('.tmp')
            temporary.write_text(self.credentials.to_json(), encoding='utf-8')
            temporary.replace(self.token)

    def events(self, day):
        start = datetime.fromisoformat(day).replace(tzinfo=TAIPEI)
        result = []; page = None
        while True:
            data = self.request('GET', params={'timeMin':start.isoformat(),'timeMax':(start+timedelta(days=1)).isoformat(),
                'singleEvents':'true','orderBy':'startTime','maxResults':250,'pageToken':page,'timeZone':'Asia/Taipei'})
            result.extend(data.get('items', [])); page = data.get('nextPageToken')
            if not page: return result
            if len(result) >= 1000: raise CalendarUnavailable('Too many events on that day to select safely. Use Google Calendar directly.')


def execute(archive, command, client):
    """Resolve a unique event before mutation and use ETags to avoid overwriting concurrent edits."""
    action, day, title = command['action'], command['day'], command['title']
    if action == 'list':
        events = client.events(day)
        lines = []
        for event in events[:20]:
            start = event.get('start', {})
            when = datetime.fromisoformat(start['dateTime'].replace('Z','+00:00')).astimezone(TAIPEI).strftime('%I:%M %p') if 'dateTime' in start else 'All day'
            lines.append(f"{when}: {event.get('summary', 'Untitled event')[:120]}")
        if not events: return f'Your primary calendar has no events on {day}.'
        return f'Your primary calendar for {day}, Taipei time: ' + '; '.join(lines) + (f'. Showing the first 20 of {len(events)} events.' if len(events)>20 else '')
    body = None
    if action in ('create','move'):
        body = {'start':{'dateTime':command['start'],'timeZone':'Asia/Taipei'},'end':{'dateTime':command['end'],'timeZone':'Asia/Taipei'}}
    if action == 'create':
        # Persist the ID before sending. Repeating an uncertain request reuses it;
        # an API timeout must not silently create another appointment.
        key = json.dumps({**command,'title':title.casefold()}, sort_keys=True)
        with archive.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS calendar_creates (command TEXT PRIMARY KEY,event_id TEXT NOT NULL)')
            row = db.execute('SELECT event_id FROM calendar_creates WHERE command=?',(key,)).fetchone()
            event_id = row[0] if row else uuid.uuid4().hex
            db.execute('INSERT OR IGNORE INTO calendar_creates VALUES (?,?)',(key,event_id))
        body.update(summary=title,id=event_id)
        result = client.request('POST', params={'sendUpdates':'none'},body=body)
        if result.get('conflict'):
            event = client.request('GET','/'+quote(event_id,safe=''))
            if event.get('status') == 'cancelled' or event.get('summary','').casefold()!=title.casefold() or any(event.get(k,{}).get('dateTime')!=body[k]['dateTime'] for k in ('start','end')):
                return 'That request was used before and the event has since changed or been deleted. Check Google Calendar directly; I did not create a duplicate.'
            return f'{title} is already on your primary calendar on {day} from {command["start"][11:16]} to {command["end"][11:16]} Taipei time.'
        return f'Added {title} to your primary calendar on {day} from {command["start"][11:16]} to {command["end"][11:16]} Taipei time.'
    matches = [e for e in client.events(day) if (e.get('id') == command['event_id'] if command.get('event_id') else e.get('summary','').casefold() == title.casefold())]
    if len(matches) != 1: return f'I found {len(matches)} exact matches for {title} on {day}. No changes made. Use the exact unique event title.'
    event = matches[0]
    if command.get('expected_etag') and event.get('etag') != command['expected_etag']:
        return 'That event changed while I was processing your request. No changes made; please ask again.'
    if event.get('attendees') or event.get('recurringEventId') or event.get('recurrence') or not event.get('organizer',{}).get('self'):
        return 'This event has guests, is recurring, or is organized by someone else. Please edit it in Google Calendar; this version handles only your own single personal events.'
    if not event.get('etag'): raise CalendarUnavailable('The event could not be checked for concurrent edits. No changes made.')
    client.request('DELETE' if action == 'delete' else 'PATCH','/'+quote(event['id'],safe=''),params={'sendUpdates':'none'},body=body,etag=event['etag'])
    return f'Cancelled {title} on {day}.' if action == 'delete' else f'Moved {title} to {command["start"][:10]} at {command["start"][11:16]} until {command["end"][11:16]} Taipei time.'


def answer(archive, question, factory=GoogleCalendar):
    """Calendar result for an explicit calendar request, or None for archive routing."""
    if not isinstance(question,str) or not re.search(r'\bcalendar\b',question,re.I): return None
    client = None
    with LOCK:
        try:
            command = parse(question, datetime.now(TAIPEI).date())
            client = factory(archive.root)
            text = execute(archive, command, client)
        except ValueError as exc: text = str(exc) if str(exc) else HELP
        except CalendarUnavailable as exc: text = str(exc)
        except Exception: text = 'Calendar access failed. Check Google Calendar before repeating an edit; an interrupted request may already have reached Google.'
        finally:
            if client and hasattr(client,'session'): client.session.close()
    return {'answer':text,'source':'google_calendar','citations':[],'insufficient_evidence':False,
            'coverage':{'day':datetime.now(TAIPEI).date().isoformat(),'selected_clips':0,'total_clips':0,'partial':False}}
