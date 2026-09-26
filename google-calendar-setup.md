# Connect your primary Google Calendar

The integration runs on your PC and requires a Google Desktop app OAuth client. A ChatGPT Calendar connection does not supply credentials to the standalone Jarvis process.

1. Open [Google Cloud Console](https://console.cloud.google.com/), create/select a project named **Jarvis**, then enable **Google Calendar API** under APIs & Services → Library.
2. Open **Google Auth Platform** and configure the app: name **Jarvis Personal Assistant**, your support/contact email, and **External** audience for a personal Google account. Add your Google account as a test user under Audience.
3. Under Data Access, add `https://www.googleapis.com/auth/calendar.events.owned`. This scope permits event access on calendars you own; Jarvis's code always targets `primary`.
4. Under Clients, create an OAuth client with application type **Desktop app**, named **Jarvis PC**. Download its JSON locally. Save it as `jarvis-data/google-oauth-client.json` in this project. Do not paste its contents in chat.
5. Run `powershell -ExecutionPolicy Bypass -File .\connect-calendar.ps1`. Sign in using the account whose primary calendar you want, and approve the requested access. The callback listens only on PC loopback and times out after five minutes.
6. A successful setup prints **Connected to your primary Google Calendar**. Setup reads a small event response to verify access; it does not create or edit any event. Ask Jarvis **Show my calendar tomorrow** for the first live test.

Tokens stay in ignored `jarvis-data/google-calendar-token.json`, never on the phone or in AWS. Keep this folder private. Google OAuth apps in Testing issue refresh tokens that expire after seven days for calendar access; complete setup first, then review the app's publishing status for ongoing personal use. Until then, repeat sign-in when needed. Revoking access in your Google account also stops Jarvis calendar access.

## Supported first-version commands

After Hey Jarvis and its acknowledgement, use one of these:

- **Show my calendar tomorrow.**
- **What is on my calendar today?**
- **Add dentist to my calendar tomorrow from three pm to four pm.**
- **Move dentist on my calendar tomorrow to five pm until six pm.**
- **Cancel dentist on my calendar tomorrow.**

Use today, tomorrow, or an ISO date such as 2026-09-28 (ISO dates are easiest through the text dashboard). Include AM/PM; minutes can be written as 3:30 pm. Times are always Asia/Taipei. Calendar commands use their spoken/written date, not the archive date selector. Event titles currently normalize to lower case. Unclear requests receive help instead of an inferred edit. There is no multi-turn clarification memory; repeat the complete corrected command.

Create commands require explicit start and end on the same day. Move/cancel requires exactly one matching title on the selected day. This version edits only your own single personal events, without guests or recurrence. It does not send invitations, edit attendees, move between dates, handle all-day creation, or edit recurring series. Personal events are changed immediately on a clear instruction, without an additional confirmation prompt. The voice recognizer does not verify speaker identity.

Repeated identical create commands reuse a durable Google event ID, including after an uncertain network response. If that event was later changed/deleted, use Google Calendar directly to recreate the identical appointment. An interrupted edit can already have reached Google, so check your calendar before issuing a different replacement command. Updates use ETags to avoid overwriting concurrent changes.

Archive transcripts and calendar event text are never treated as action instructions. Questions without the word calendar retain the existing archive-only behavior; this initial parser does not infer calendar intent from arbitrary wording. Tests use a fake Google API and do not prove account authorization or live API behavior.

References: [Google Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python), [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth), [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2).
