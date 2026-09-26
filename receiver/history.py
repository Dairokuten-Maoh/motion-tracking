"""Read/search the permanent timeline without sending transcripts to a cloud service."""
import argparse
from datetime import datetime
from server import Archive

parser = argparse.ArgumentParser()
parser.add_argument('query', nargs='?', default='')
parser.add_argument('--data', default='jarvis-data')
args = parser.parse_args()
for row in reversed(Archive(args.data).search(args.query)):
    when = datetime.fromtimestamp(row['started']).astimezone().isoformat(timespec='seconds')
    print(f"{when} [{row['state']}] {row['id']}")
    print(row['transcript'] or row['error'] or '(Awaiting transcription)')
    print()
