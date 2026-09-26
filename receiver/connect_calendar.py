"""Interactive PC-only OAuth enrollment; never expose this through the HTTP receiver."""
import argparse
import json
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from google_auth_oauthlib.flow import InstalledAppFlow
from google_calendar import SCOPE, GoogleCalendar

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',default='jarvis-data')
    args=parser.parse_args()
    root=Path(args.data)
    source=root/'google-oauth-client.json'
    if not source.exists():
        raise SystemExit('Save a Google Desktop app OAuth client JSON as jarvis-data/google-oauth-client.json first. See google-calendar-setup.md.')
    config=json.loads(source.read_text(encoding='utf-8-sig'))
    if 'installed' not in config: raise SystemExit('Use a Desktop app OAuth client, not a web or service-account credential.')
    flow=InstalledAppFlow.from_client_config(config,[SCOPE])
    credentials=flow.run_local_server(host='127.0.0.1',port=0,open_browser=True,timeout_seconds=300,
        authorization_prompt_message='Complete Google sign-in in the browser. Do not share the sign-in URL or authorization code.',
        success_message='Jarvis Calendar sign-in complete. You can close this tab.',prompt='consent',access_type='offline')
    target=root/'google-calendar-token.json'
    temporary=target.with_suffix('.tmp')
    temporary.write_text(credentials.to_json(),encoding='utf-8');temporary.replace(target)
    client=GoogleCalendar(root)
    try: client.request('GET',params={'maxResults':1})
    finally: client.session.close()
    print('Connected to your primary Google Calendar. No events created or changed.')

if __name__=='__main__': main()
