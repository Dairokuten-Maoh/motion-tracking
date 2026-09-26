"""Authenticated, idempotent audio ingestion. Raw audio expires; transcripts do not."""
import argparse
from contextlib import contextmanager
import hashlib
import hmac
import io
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import threading
import time
import wave
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_AUDIO = 2_000_000
RETENTION = 30 * 86400
TAIPEI = timezone(timedelta(hours=8))


class Archive:
    """Own atomic ingestion, duplicate detection, and recording-time retention."""
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw = self.root / 'raw'
        self.raw.mkdir(exist_ok=True)
        self.lock = threading.Lock()
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY, started REAL NOT NULL, digest TEXT NOT NULL,
                path TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                transcript TEXT, segments TEXT, error TEXT)''')
            db.executescript('''
                CREATE INDEX IF NOT EXISTS recordings_started ON recordings(started);
                CREATE TABLE IF NOT EXISTS cloud_uploads (
                    id TEXT NOT NULL, bucket TEXT NOT NULL, object_key TEXT NOT NULL,
                    state TEXT NOT NULL, error TEXT, updated REAL NOT NULL,
                    PRIMARY KEY(id,bucket));
                CREATE TABLE IF NOT EXISTS diary_entries (
                    window INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL,
                    body TEXT NOT NULL, model TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS diary_dirty (window INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS diary_status (
                    window INTEGER PRIMARY KEY, error TEXT, attempted REAL);
                CREATE TRIGGER IF NOT EXISTS diary_insert AFTER INSERT ON recordings BEGIN
                    INSERT OR IGNORE INTO diary_dirty VALUES(CAST(NEW.started/1800 AS INTEGER)*1800);
                END;
                CREATE TRIGGER IF NOT EXISTS diary_update AFTER UPDATE OF transcript,state ON recordings
                WHEN NEW.state != OLD.state OR coalesce(NEW.transcript,'') != coalesce(OLD.transcript,'') BEGIN
                    INSERT OR IGNORE INTO diary_dirty VALUES(CAST(NEW.started/1800 AS INTEGER)*1800);
                END;
                INSERT OR IGNORE INTO diary_dirty SELECT DISTINCT CAST(started/1800 AS INTEGER)*1800
                    FROM recordings WHERE CAST(started/1800 AS INTEGER)*1800 NOT IN (SELECT window FROM diary_entries);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'archive.sqlite3', timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, clip_id, started, audio):
        if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', clip_id):
            raise ValueError('Invalid recording ID')
        if not time.time() - RETENTION < started < time.time() + 300:
            raise ValueError('Recording timestamp outside retention window')
        try:
            with wave.open(io.BytesIO(audio)) as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                    raise ValueError('Expected mono PCM16 WAV at 16000 Hz')
                frames = wav.getnframes()
                if not 0 < frames <= 16000 * 60 or len(wav.readframes(frames)) != frames * 2:
                    raise ValueError('Invalid WAV length')
        except (wave.Error, EOFError) as exc:
            raise ValueError('Invalid WAV') from exc
        digest = hashlib.sha256(audio).hexdigest()
        with self.lock, self.connect() as db:
            existing = db.execute('SELECT digest FROM recordings WHERE id=?', (clip_id,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError('Recording ID conflicts with existing audio')
                return False
            path = self.raw / (clip_id + '.wav')
            temporary = path.with_suffix('.tmp')
            with temporary.open('wb') as stream:
                stream.write(audio)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
            db.execute('INSERT INTO recordings(id,started,digest,path) VALUES(?,?,?,?)',
                       (clip_id, started, digest, str(path)))
        return True

    def expire(self):
        with self.lock, self.connect() as db:
            for clip_id, path in db.execute('SELECT id,path FROM recordings WHERE started<=?',
                                           (time.time() - RETENTION,)).fetchall():
                Path(path).unlink(missing_ok=True)
                db.execute("UPDATE recordings SET state=CASE WHEN state='done' THEN state ELSE 'expired' END WHERE id=?", (clip_id,))

    def search(self, query):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                'SELECT id,started,state,transcript,error FROM recordings WHERE instr(lower(coalesce(transcript,\'\')),lower(?))>0 OR ?=\'\' ORDER BY started DESC LIMIT 100',
                (query, query))]

    def timeline(self, day, query=''):
        """Return one Taipei calendar day; each source clip appears in its start-time window."""
        start = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=TAIPEI).timestamp()
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT id,started,state,transcript,error,path FROM recordings WHERE started>=? AND started<? ORDER BY started', (start, start + 86400)).fetchall()
            groups = {}
            for source in rows:
                row = dict(source)
                cloud = db.execute('SELECT state FROM cloud_uploads WHERE id=? ORDER BY updated DESC LIMIT 1', (row['id'],)).fetchone()
                row['cloud_state'] = cloud['state'] if cloud else 'local only'
                row['audio_available'] = row['started'] > time.time() - RETENTION and (Path(row.pop('path')).exists() or row['cloud_state']=='uploaded')
                window = int(row['started'] // 1800) * 1800
                groups.setdefault(window, {'window': window, 'clips': [], 'entry': None, 'refreshing': False, 'error': None})['clips'].append(row)
            for window, group in groups.items():
                entry = db.execute('SELECT body,updated,model FROM diary_entries WHERE window=?', (window,)).fetchone()
                if entry:
                    group['entry'] = json.loads(entry['body'])
                    group['updated'] = entry['updated']
                    group['model'] = entry['model']
                group['refreshing'] = db.execute('SELECT 1 FROM diary_dirty WHERE window=?', (window,)).fetchone() is not None
                status = db.execute('SELECT error FROM diary_status WHERE window=?', (window,)).fetchone()
                group['error'] = status['error'] if status else None
                group['open'] = window + 1800 > time.time()
            needle = query.casefold()
            return [g for g in groups.values() if not needle or needle in json.dumps(g, ensure_ascii=False).casefold()]

    def audio(self, clip_id):
        with self.lock, self.connect() as db:
            row = db.execute('SELECT path,started,digest FROM recordings WHERE id=?', (clip_id,)).fetchone()
            if not row or row[1] <= time.time() - RETENTION:
                return None
            try:
                return Path(row[0]).read_bytes()
            except FileNotFoundError:
                pass
        if (self.root / 'aws.json').exists():
            from s3_archive import CloudArchive, client_for, read_config
            config=read_config(self.root)
            return CloudArchive(self,config,client_for(config)).download(clip_id,row[2])
        return None


def handler_for(archive, token):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_bytes(status, body, 'application/json; charset=utf-8')

        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), ('Bearer ' + token).encode('utf-8')):
                # Drain a bounded upload so Windows does not reset the socket before
                # the caller receives the authentication error.
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if 0 < length <= MAX_AUDIO:
                        self.rfile.read(length)
                except (ValueError, TimeoutError):
                    pass
                self.close_connection = True
                self.reply(401, {'error': 'Authentication required'})
                return False
            return True

        def do_GET(self):
            url = urlparse(self.path)
            public = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if url.path in public:
                name, content_type = public[url.path]
                self.send_bytes(200, (Path(__file__).parent / 'web' / name).read_bytes(), content_type)
                return
            if not self.authorized():
                return
            if url.path == '/health':
                self.reply(200, {'status': 'ready'})
            elif url.path == '/recordings':
                self.reply(200, archive.search(parse_qs(url.query).get('q', [''])[0]))
            elif url.path == '/timeline':
                params = parse_qs(url.query)
                try:
                    self.reply(200, archive.timeline(params.get('day', [datetime.now(TAIPEI).strftime('%Y-%m-%d')])[0], params.get('q', [''])[0]))
                except ValueError:
                    self.reply(400, {'error': 'Use a date in YYYY-MM-DD format'})
            elif url.path.startswith('/audio/'):
                try:
                    audio = archive.audio(url.path.removeprefix('/audio/'))
                except Exception:
                    self.reply(503, {'error': 'Cloud recording temporarily unavailable; retry later'})
                    return
                if audio is None:
                    self.reply(404, {'error': 'Recording unavailable or expired'})
                else:
                    self.send_bytes(200, audio, 'audio/wav')
            else:
                self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                if self.path in ('/speak','/speak-stream'):
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192:
                        raise ValueError('Invalid speech request size')
                    body = self.rfile.read(length)
                    if len(body) != length: raise ValueError('Incomplete speech request')
                    payload = json.loads(body)
                    if not isinstance(payload, dict): raise ValueError('Expected speech text')
                    from voice_output import synthesize, synthesize_stream
                    if self.path == '/speak-stream':
                        stream=synthesize_stream(payload.get('text'),archive.root)
                        try:
                            first=next(stream)
                        except (OSError,RuntimeError,wave.Error):
                            stream.close()
                            self.reply(503, {'error':'Custom voice is unavailable; use phone speech.'})
                            return
                        self.close_connection=True
                        try:
                            self.connection.settimeout(30)
                            self.send_response(200)
                            self.send_header('Content-Type','application/x-jarvis-wav-stream')
                            self.send_header('Cache-Control','no-store')
                            self.send_header('Connection','close')
                            self.end_headers()
                            for audio in itertools.chain([first],stream):
                                self.wfile.write(struct.pack('!I',len(audio))+audio)
                                self.wfile.flush()
                            self.wfile.write(b'\0\0\0\0')
                            self.wfile.flush()
                        except (OSError,RuntimeError,wave.Error):
                            # No terminal frame: the phone reports interruption and
                            # never repeats a partially spoken reply or action.
                            pass
                        finally:stream.close()
                        return
                    try:
                        audio = synthesize(payload.get('text'), archive.root)
                        self.send_bytes(200, audio, 'audio/wav')
                    except (OSError, RuntimeError, wave.Error):
                        self.reply(503, {'error': 'Custom voice is unavailable; use phone speech.'})
                    return
                if self.path == '/transcribe-command':
                    from command_speech import transcribe, MAX_PCM, SpeechBusy
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 3200 <= length <= MAX_PCM or length % 2:
                        raise ValueError('Invalid command audio length')
                    body = self.rfile.read(length)
                    if len(body) != length: raise ValueError('Incomplete command audio')
                    # Consume a bounded body before rejecting its media type;
                    # closing with unread bytes can reset the connection on Windows.
                    if self.headers.get('Content-Type') != 'audio/pcm;rate=16000;channels=1;format=s16le':
                        raise ValueError('Unsupported command audio format')
                    try:
                        self.reply(200, {'text': transcribe(body), 'engine': 'whisper-small-local'})
                    except SpeechBusy as exc:
                        self.reply(429, {'error': str(exc)})
                    except (OSError, RuntimeError):
                        self.reply(503, {'error': 'Local command transcription is unavailable. No command was executed.'})
                    return
                if self.path == '/ask':
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192:
                        raise ValueError('Invalid question request size')
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError('Expected a question and date')
                    from conversation import ask, BusyError
                    try:
                        from dialogue import answer as dialogue_answer
                        question = payload.get('question')
                        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000:
                            raise ValueError('Enter a question between 1 and 1000 characters')
                        answer = dialogue_answer(archive, payload.get('day'), question, payload.get('session', 'phone'))
                        self.reply(200, answer)
                    except BusyError as exc:
                        self.reply(429, {'error': str(exc)})
                    except (OSError, RuntimeError):
                        self.reply(503, {'error': 'Local AI is unavailable. Check that Ollama is running, then retry.'})
                    return
                if self.path != '/recordings':
                    self.close_connection = True
                    self.reply(404, {'error': 'Not found'})
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 44 < length <= MAX_AUDIO:
                    raise ValueError('Invalid content length')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Incomplete request')
                created = archive.ingest(self.headers.get('X-Recording-Id', ''),
                                         float(self.headers.get('X-Started-At', '0')), body)
                self.reply(201 if created else 200, {'stored': True})
            except (ValueError, TimeoutError) as exc:
                self.close_connection = True
                self.reply(400, {'error': str(exc)})

        def log_message(self, fmt, *args):
            # URLs can contain private searches; never log request paths or credentials.
            pass
    return Handler


def maintain(archive):
    while True:
        archive.expire()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='jarvis-data')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    archive = Archive(args.data)
    token_file = archive.root / 'token.txt'
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
    token = token_file.read_text(encoding='utf-8').strip()
    if len(token) < 32:
        raise SystemExit('Invalid token.txt; use a random token of at least 32 characters')
    threading.Thread(target=maintain, args=(archive,), daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), handler_for(archive, token))
    print(f'Receiver: http://{args.host}:{args.port}; pairing token: {token_file.resolve()}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
