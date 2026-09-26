"""Process the durable archive with local Whisper; safe to restart after interruption."""
import argparse
import json
import time
from server import Archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='jarvis-data')
    parser.add_argument('--model', default='small')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--retry-errors', action='store_true')
    args = parser.parse_args()
    # Honor the OS certificate store, including managed Windows trust roots.
    import truststore
    truststore.inject_into_ssl()
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device=args.device,
                         compute_type='int8' if args.device == 'cpu' else 'float16')
    archive = Archive(args.data)
    if args.retry_errors:
        with archive.connect() as db:
            db.execute("UPDATE recordings SET state='pending',error=NULL WHERE state='error'")
    while True:
        archive.expire()
        with archive.connect() as db:
            pending = db.execute("SELECT id,path FROM recordings WHERE state='pending' ORDER BY started").fetchall()
        for clip_id, path in pending:
            try:
                segments, info = model.transcribe(path, vad_filter=True, beam_size=5,
                                                  multilingual=True)
                parts = [dict(start=s.start, end=s.end, text=s.text) for s in segments]
                with archive.connect() as db:
                    db.execute("UPDATE recordings SET state='done',transcript=?,segments=?,error=NULL WHERE id=? AND state='pending'",
                               (' '.join(s['text'] for s in parts), json.dumps(parts, ensure_ascii=False), clip_id))
                print(f'Transcribed {clip_id}', flush=True)
            except Exception as exc:
                with archive.connect() as db:
                    db.execute("UPDATE recordings SET state='error',error=? WHERE id=? AND state='pending'", (str(exc), clip_id))
                print(f'Failed {clip_id}: {type(exc).__name__}', flush=True)
        if args.once:
            return
        time.sleep(3)


if __name__ == '__main__':
    main()
