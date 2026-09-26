# Jarvis capture prototype

First milestone: Pixel microphone → durable PC audio archive → local English/Mandarin transcription.
Your existing `import cv2.py` is unchanged. No recording starts until you tap **Start listening**.

## Daily history and silent summaries

Open **http://127.0.0.1:8765/** after starting the receiver. Paste the existing pairing token from `jarvis-data/token.txt` to unlock the page. `open-history.ps1` opens the page and copies that token to your clipboard for convenience. The web page keeps the token only in memory, never in a URL, cookie, or browser storage. Reloading locks the page.

The page offers a Taipei-date timeline, English/Chinese search within the chosen day, original audio playback, and half-hour entries with links to supporting transcript excerpts. Use **Refresh** to see new uploads. No summary is announced aloud or sent as a notification.

Run `powershell -ExecutionPolicy Bypass -File .\start-diary.ps1` alongside the receiver and transcription worker. It uses the already-installed local Ollama model `qwen2.5:14b`. Ollama must be running. No cloud AI is called. Completed half-hour windows are processed within the worker's next polling cycle, plus inference time. Late transcripts automatically invalidate and refresh their entry. `receiver/diary.py --once --include-current` can generate a preview for the current period.

Each summary item must contain an exact source quote and a valid recording ID. Unsupported citations reject the generated result and leave it queued for retry. This checks evidence linkage, not the truth of every model interpretation: verify the cited transcript. Recorded voices are unidentified; background media must not be treated as your personal actions. Task candidates have **unverified ownership** and do not trigger actions or calendar edits. Durable task completion tracking is a future feature.

Entries and transcript text remain in SQLite indefinitely. Summaries survive raw-audio expiration. If Ollama fails, existing summaries and all transcripts remain available. The worker batches long periods without silently dropping source text. Clips are grouped by start time; a clip crossing a half-hour boundary appears in its starting period.

## Optional AWS raw-audio archive

The S3 integration and private-bucket CloudFormation template are ready. Follow [AWS setup](aws/README.md) to deploy the bucket and configure your AWS profile. Cloud uploading remains disabled until `jarvis-data/aws.json` exists and the archive worker is started. No AWS account credentials are stored on the phone or in this repository. The archive verifies uploaded checksums, retries failed uploads, supports cloud playback when a local copy is missing, and expires raw audio without deleting transcripts. The current PC remains the primary store for transcripts and summaries; cloud database backup is not yet implemented.

## Ask Jarvis

Unlock the history page, select a date, and enter a question in **Ask Jarvis**. For the initial test day, try **What English test phrase was recorded?** Each question is independent and uses transcripts from that selected Taipei date; it does not silently search a different date or remember earlier chat questions.

Answers run locally through the existing Ollama model. Source quotes link to the original transcript and recording. For a busy day, bounded excerpts are ranked by query terms and the page explicitly labels partial coverage. This is lexical retrieval, so English questions about Mandarin-only terms may miss relevant excerpts in a large archive. An empty or unfinished day produces a clear limitation rather than invented memories. Citation validation proves the quote exists, not that every interpretation is correct.

Click **Read aloud** for English spoken playback; **Stop speaking** stops it. Only browser voices marked as local are selected. If your browser exposes no local English voice, the text still works and the page explains that limitation. No microphone, cloud speech service, wake word, or automatic speech is activated. Locking the page clears the answer and cancels speech. Questions and answers are not written to the archive; only the current answer stays in the tab.

This release answers archive questions only. It cannot identify speakers, browse the internet, send messages, change calendars, or operate devices. Those actions remain later milestones. Phone wake-phrase interaction is available as described below.

## Quick start on this Windows PC

1. Run `powershell -ExecutionPolicy Bypass -File .\start-receiver.ps1` from this folder. It creates `jarvis-data/token.txt` on first launch. Keep that token private.
2. Connect your Pixel by USB, enable Developer options and USB debugging, and accept the phone's debugging prompt.
3. Run `powershell -ExecutionPolicy Bypass -File .\setup-phone.ps1`. This installs the APK and forwards phone port 8765 to the PC. The initial test needs the USB connection.
4. In Jarvis Capture, leave the receiver URL as `http://127.0.0.1:8765`. Copy the content of `jarvis-data/token.txt` into the pairing-token field. Tap **Start listening**, and grant microphone/notification permissions.
5. Speak for at least 30 seconds, then lock the phone and continue speaking. The app queues mono 16 kHz PCM WAV files and uploads every 15 seconds. **Stop listening** finalizes the last partial chunk and attempts one final upload. If offline or interrupted by Android, use **Retry queued uploads** to send remaining files without recording.
6. In a second terminal, run `powershell -ExecutionPolicy Bypass -File .\start-transcription.ps1`. The first run downloads the multilingual Whisper `small` model. Default CPU int8 avoids CUDA setup; GPU tuning comes after capture verification.
7. View history: `.venv\Scripts\python.exe receiver/history.py`. Search: `.venv\Scripts\python.exe receiver/history.py "meeting"` (Chinese searches work too). Audio is in `jarvis-data/raw`, transcripts and per-segment time offsets in `jarvis-data/archive.sqlite3`.

If dependencies are not installed:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --use-feature=truststore -r receiver/requirements.txt
```

Run only one transcription worker. `--retry-errors` retries failed items; `--once` processes the current backlog and exits. Transcription is automatic language detection with multilingual processing, not translation. Mixed-language accuracy needs testing with your actual speech.

## Network and data boundaries

The receiver defaults to loopback and USB forwarding. It requires a random bearer token. The prototype also permits HTTP for trusted-LAN testing: explicitly run the receiver with `--host 0.0.0.0`, allow its private-network firewall access, and use the PC's LAN address. **Plain HTTP is not encrypted; use USB for the first test. Do not expose this receiver to the internet.** Remote use needs an encrypted tunnel or HTTPS before deployment. When AWS archival is configured, the PC uploads raw recordings to the configured private S3 bucket.

Phone files use app-private storage, with Android backup disabled. Uploaded files are removed from the phone only after acknowledgement. Interrupted files are recovered when recording restarts. Queue capacity is 2 GiB (roughly 18 hours of this uncompressed audio); capture stops visibly if full or disk space is low. PCM is intentionally easy to inspect for the prototype; compressed storage is future work.

Raw PC audio is expired by recording timestamp after 30 days while the receiver or worker runs. Phone expiration runs during capture/sync; an app that is stopped cannot run this cleanup. Transcripts remain. This is prototype cleanup, not guaranteed deletion at an exact wall-clock deadline. S3 archives raw audio; permanent transcript/database backups are not yet configured. The database and pairing token are private data: do not commit or share `jarvis-data`.

## What is implemented

- Explicit recording controls and Android microphone foreground notification, partial wake lock, screen-off capture design.
- Continuous AudioRecord session with 30-second WAV boundaries, durable offline queue, retry and duplicate-safe receiver acknowledgements.
- Authenticated bounded uploads, WAV validation, chronological searchable SQLite archive, separate restartable local transcription worker.
- Capture/upload status and receiver error codes in the app; raw-data retention independent of transcripts.

## Not implemented yet

Call-audio capture, speaker identity, location/presence, PC microphone recording, cameras/screens, LINE, calendar edits, and Canva integration. AWS archival is configured on this PC; other installations need their own account deployment/configuration. These remain later milestones, not hidden active features. Android may silence/interfere with capture during calls or competing microphone use; the prototype does not claim to capture both sides. It does not restart recording after force-stop/reboot; reopen and tap Start.

## Physical acceptance test

1. English, Mandarin, and a mixed-language sentence arrive with the correct capture time and useful transcripts.
2. Lock the phone for 10 minutes: verify continuous file timestamps and playable speech, not just file existence.
3. Disconnect USB/network for 2 minutes: queue grows; reconnect and check no missing or duplicate clips.
4. Stop and restart: final short clip is preserved. Kill the process during capture and check partial-file recovery on restart.
5. Try a cellular call, LINE call, music, and another microphone app. Inspect audio for silence and record the supported/unsupported cases.
6. Run an hour locked and measure battery use, temperature, queue size, and transcription lag before an overnight trial.

## Build and tests

Open `android` in Android Studio. The project uses AGP 8.7.3, Gradle 8.9, SDK 35 and JDK 17. Select JDK 17 for Gradle, rather than the newer bundled JDK.
`powershell -ExecutionPolicy Bypass -File .\build-android.ps1` builds the APK at `android/app/build/outputs/apk/debug/app-debug.apk`. On this machine it uses the isolated JDK under `.tools/jdk17`; elsewhere set `JAVA_HOME` to JDK 17.
Install `receiver/requirements-aws.txt` to include the SDK contract tests, then run `.venv\Scripts\python.exe -m unittest discover -s receiver -v`. These tests use fake/stubbed AWS responses and require no cloud credentials. Validate the deployment template with `cfn-lint aws/archive-stack.yaml` when cfn-lint is installed.

## Design decisions

A browser recorder was considered but a native foreground service gives explicit ownership of Android microphone lifetime and offline files. Capture stays in one service; upload knows only finalized WAV files. An in-request transcription design was rejected because slow inference would delay acknowledgement and complicate retries. The receiver acknowledges durable storage and the independent worker processes pending rows. UUID plus content digest makes lost acknowledgements safe to retry.

Diary generation also runs outside HTTP requests. Database triggers mark changed periods for regeneration; snapshot fingerprints prevent a slow model response from overwriting more recent transcripts. A read-time-only summary design was rejected because it would delay searches and provide no durable entries. The existing archive owns the timeline rather than introducing a second database or duplicated recording format.

References: [Android microphone foreground services](https://developer.android.com/develop/background-work/services/fgs/service-types), [AGP 8.7 compatibility](https://developer.android.com/build/releases/agp-8-7-0-release-notes), [faster-whisper](https://github.com/SYSTRAN/faster-whisper).


## Phone voice interaction (0.2)

Build with `build-android.ps1`, then install with `setup-phone.ps1` while the Pixel is connected and authorized for debugging. Installation preserves the existing pairing settings. Keep the PC receiver and Ollama running and the USB forwarding connection active.

1. Tap **Start listening** and wait for **Ready: say Hey Jarvis** in the app. First launch copies the bundled model into app-private storage.
2. Say **Hey Jarvis**, then pause until the phone says **I'm listening**.
3. Ask an English question, such as **What English test phrase was recorded today?**, then stop speaking. The phone reads the PC's answer aloud. Check media volume if it is silent.
4. Say the wake phrase again for another question. **Stop listening** stops recording, wake recognition, and speech playback.

Wake detection and English question dictation use the bundled Vosk small English model. Question capture ends on the recognizer's silence boundary, or at 15 seconds; no recognized question times out after 8 seconds. Only recognized question text is sent to the existing authenticated `/ask` endpoint. Each question is independent and selects today's date in Asia/Taipei. Use the history page for another date. Mandarin/English archival transcription remains handled by multilingual Whisper; this version's spoken questions are English only.

Phone replies require an installed offline English Android TTS voice. An unavailable voice is reported in the app. Voice processing never opens a second microphone or waits inside the recorder thread. Recognition is suspended during replies and PC inference to prevent speech feedback; archival recording continues, including audible Jarvis replies. The queue is bounded; a voice overload is reported while archival capture continues. Voice requests are not queued for replay when offline. Replies can take time while the PC model is busy.

This is an initial speech-recognition-based wake detector, not speaker verification. Other voices/media can trigger it, and accents/noise can cause missed wakes. It only answers archive questions; it does not execute device actions or send messages. Physical Pixel wake accuracy, locked-screen operation, battery use, and playback still need acceptance testing with this build.

The build downloads [Vosk's Android English model](https://alphacephei.com/vosk/models), Apache 2.0, from its official source, checks a pinned SHA-256, and bundles it in the APK. Run `prepare-voice-model.ps1` before building directly through Android Studio. Model/cache files are ignored by Git. Android uses Vosk 0.3.75 and JNA 5.18.1. No additional cloud AI subscription is required.


## Remote access through Tailscale

Install Tailscale on Windows and Android and sign in with the same account. Enable the Android VPN connection. After the PC is signed in and the local receiver is running, run `powershell -ExecutionPolicy Bypass -File .\setup-remote-access.ps1`. If Tailscale provides a link to enable HTTPS, complete that account step. The script refuses to overwrite an existing Serve configuration, publishes the receiver privately through Serve, attempts authenticated HTTPS health from the PC, and saves the endpoint in ignored `jarvis-data/remote.json`. It never enables Funnel or router forwarding.

In Jarvis Capture, stop listening, replace Receiver URL with the verified HTTPS endpoint, preserve the pairing token, then start listening. Keep Tailscale connected on both devices. The receiver stays on `127.0.0.1:8765`; HTTPS certificate validation remains enabled. Access also follows the account's Tailscale access policy, so keep the network restricted to trusted devices. Existing USB/Wi-Fi ADB forwarding is no longer required once this endpoint works.

Acceptance: turn off phone Wi-Fi while keeping mobile data and Tailscale connected; say Hey Jarvis and ask about today. Verify a new recorded clip also arrives on the PC. Test reconnection after a brief outage. Do not count a test performed only on home Wi-Fi as remote acceptance. Android may require allowing Tailscale background activity. PC sleep, receiver shutdown, or a disconnected/expired Tailscale login interrupts access. The app retains failed archival uploads for retry; spoken questions must be repeated after reconnection.

Reference: [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).


Current PC endpoint: **https://balthazar.tail603afd.ts.net**. The Pixel is configured to use this address with its existing pairing token. Tailscale Serve is running in the background; Funnel is not enabled. The Pixel verified TLS using its normal certificate trust and received the expected 401 without authentication. A subsequent Jarvis upload arrived after switching the app to HTTPS and removing ADB reverse forwarding. The PC cannot currently connect to its own Serve address (timeout); peer access works. A voice test over mobile data is still required.


## Automatic startup and recovery

Installed Windows task: **Jarvis Personal Assistant**. It runs `watch-jarvis.ps1` hidden after this Windows user signs in, with no stored Windows password. It is running now. Tailscale unattended mode is enabled, and its private Serve route persists separately.

The watchdog checks every 15 seconds and starts missing receiver, transcription, diary, and (when configured) AWS archive processes. Existing processes from this workspace's virtual environment are reused. Ollama is reused when available; if its server process is absent, the installed local executable is started. Failed starts retry no faster than once per minute. A workspace mutex blocks duplicate watchdogs, and Task Scheduler is configured to restart the watchdog after failure. The task has no execution time limit and can run on battery power.

Logs are under `jarvis-data/logs`; `jarvis-data/processes.json` holds the latest observed process IDs. The watchdog log rotates at 2 MB; service output keeps one previous run when restarted. Service logs can grow during long runs. To reinstall the task after moving this folder, inspect/remove the old task first, then run `install-startup.ps1` from the new location. Keep this folder and its virtual environment in place.

This recovers exited processes, not every possible application hang. It does not repair expired AWS/Tailscale credentials, wake a sleeping PC, or restart phone recording after a phone reboot. Services start **after Windows sign-in**, not at the Windows login screen. Keep the PC awake. To disable future sign-in startup, run `Disable-ScheduledTask -TaskName 'Jarvis Personal Assistant'`; this does not stop the current watchdog. Avoid manually stopping individual workers while the watchdog is active, as it will restart them.

Verified without reboot: existing worker adoption, duplicate watchdog rejection, and receiver process termination followed by automatic restart and authenticated health success. A real reboot/sign-in test remains pending.


## Primary Google Calendar (authorization pending)

Calendar command handling is installed in the receiver and works through both the phone voice loop and the text dashboard. Complete [Google Calendar setup](google-calendar-setup.md) before live use. Try **Show my calendar tomorrow**, **Add dentist to my calendar tomorrow from three pm to four pm**, **Move dentist on my calendar tomorrow to five pm until six pm**, or **Cancel dentist on my calendar tomorrow**. See the setup guide for supported syntax and first-version limits.

Only explicit calendar requests reach this integration; background transcripts never generate calendar edits. All times are Taipei time and the API calendar is always `primary`. OAuth credentials remain on the PC. Google authentication and live account read/write tests are pending; no real events were modified during implementation. The earlier archive-only descriptions apply to archive questions; these explicit calendar commands are now a separate capability once authorized.


## Voice capture update 0.3 (installation pending)

The phone now displays **Hearing now**, **Last command** with its timestamp, **Last reply**, and **Last error** below the recording controls. The last command/reply persist in app-private preferences when readiness status changes or the app is reopened. Live recognition is provisional; these fields show what the command recognizer heard, separately from the searchable archival transcripts.

Command recognition accepts audio immediately after acknowledgement playback ends, rather than dropping a further 350 ms. It joins final recognition segments across short pauses, allowing another 1.5 seconds after the recognizer endpoint before submission, with a 20-second total limit and 10-second initial no-speech timeout. Queue overload reports an error and returns to wake listening. This retains the existing Vosk model; it does not establish improved word accuracy for names or remove the calendar parser's explicit syntax requirements. Real-phone acceptance of this update is pending.


## Internet lookup

After Hey Jarvis and its acknowledgement, say **Search the web for Taipei 101 height** or **Look up Taipei 101 height**. Supported prefixes are Search the web for, Search the internet for, Search for, Look up, Look up online, and Look online for (optionally preceded by Please). Explicit search takes priority over calendar routing, so searching for Google Calendar instructions does not edit your calendar. Other wording retains the existing archive/calendar routing.

The PC uses DDGS's Bing backend with TLS verification and summarizes up to five search snippets using the existing local Ollama model. Only your search terms go to the search provider; archive transcripts, calendar data, and pairing/OAuth tokens are not included. Search runs only on an explicit request. No extra paid API key is configured. Install `receiver/requirements-web.txt` when setting up another PC.

The phone speaks the result and retains it in Last reply. Searches entered on the history web page show clickable source links and a retrieval timestamp. Phone searches do not populate the web page's current-answer panel; repeat the search there to inspect links. Results are not saved as permanent web-search history in this version.

These are search-snippet summaries, not full-page browsing or guaranteed live weather/price/news data. Retrieval time does not establish publication freshness. Missing results, provider failure, AI contention, or invalid source IDs produce an explicit limitation; ordinary questions are not silently sent to a search engine. Search content cannot invoke action tools. The model can still misinterpret snippets, and valid source IDs do not prove every claim. DDGS is an unofficial metasearch library and provider availability/rate limits may change; paid search-provider integration is not configured.

Reference: [DDGS upstream documentation](https://github.com/deedy5/ddgs).


## Conversational interpretation (first version)

The receiver now interprets natural requests with the local Ollama model before choosing calendar, internet lookup, or archive tools. Exact command prefixes are no longer required. Examples: **What is on my schedule tomorrow?**, **How tall is Taipei 101?**, **What did I talk about yesterday?**, and **Put lunch with Alex tomorrow at noon for an hour**. After a calendar operation, **Actually move it an hour later** can refer to the prior appointment. Missing times/durations prompt a question; you can answer **At noon for an hour**. Close calendar-title matches are suggested without editing; **Yes, that one** selects a single suggested candidate.

The phone still requires Hey Jarvis and acknowledgement before **each turn**. Open-mic conversational turn-taking is not implemented. The existing phone APK works with this receiver update. It still uses Vosk for recognition, so words may be misheard; inspect Last command when behavior differs from intent.

Each phone conversation uses its last six turns within 30 minutes. The web page has a separate conversation per page load; refresh starts a new page session. **New conversation** resets active context while retaining saved records. User requests, proposed intents, and concise tool replies are stored permanently in the private SQLite `dialogue_turns` table; this is short-term working context over saved turns, not unlimited autobiographical memory or an existing searchable conversation UI. Raw audio retention is unchanged.

The model proposes one structured intent; Python validates field types, dates/timezones, user-provided date/time evidence, event matches, and concurrent changes. Unclear creates cannot invent a default time or duration. Moves preserve the real event's duration unless explicitly changed. Negated mutation requests are blocked. Calendar event selection uses unique exact/whole-word matches; close spellings require clarification. Existing guest/recurring-event restrictions remain. Model inference can still misinterpret natural language; this is the first conversation layer, not completion of every planned autonomous capability.

Only supported tools are exposed: calendar, web snippets, and recorded-history answers. LINE, email, cameras, PC/phone control, and unattended planning are not added by this update. One operation per turn is supported. Calendar edits execute on clear instructions; there is no generic approval prompt. Speech recognition does not authenticate the speaker. Model planning runs locally; a routed web search sends its search query externally. Source material is treated as untrusted evidence, not tool instructions.

Validation includes automated checks and a live local-model create/relative-move/missing-time sequence against a fake calendar. No real calendar events were modified in deployment tests. A read-only live follow-up check is recorded in VALIDATION.md. A real Windows reboot and broader accent/noise/long-conversation acceptance still remain pending.


## Continuous voice conversation (0.4)

Say Hey Jarvis once and wait for the acknowledgement. After each completed reply, the phone automatically listens for the next English turn; repeating the wake phrase is no longer necessary during that exchange. Begin the follow-up within approximately 10 seconds. A turn can last up to 20 seconds, retaining the existing pause handling. The app status says when it is listening for a follow-up.

Say **That's all**, **That is all**, **End conversation**, **Stop talking**, or **Goodbye** as a standalone utterance to return to wake listening. Closing phrases are handled on the phone, without a PC action request. Ten seconds with no recognized speech ends the exchange silently and preserves Last command/Last reply. Playback and PC processing still suspend command recognition, so wait until the reply finishes; interruption/barge-in is not implemented. Network failures or recognition overload end the active exchange. Stop listening still stops the entire microphone service.

Continuous archival recording remains active when conversation ends. The server's recent context also remains available for 30 minutes; use New conversation to reset working context explicitly. Background speech can be recognized during the follow-up window because speaker verification is not implemented.


## Open-ended conversation

Jarvis now supports ordinary conversation, personal disclosures, emotional support, brainstorming, drafting, and stable explanations through its local chat route. A new topic can interrupt calendar discussion. Personal disclosures do not inherently request an archive search, web search, or calendar action. Current/sourced information and explicit recall requests still use their respective tools. This is a receiver update; phone 0.4 needs no reinstall. Existing recent-context limits and speech-recognition limitations remain.


## PC command transcription (phone 0.5)

Wake detection and provisional text still run locally on the phone with Vosk. Each captured command is now sent as bounded 16 kHz mono PCM to the authenticated `/transcribe-command` endpoint over the configured private connection. The PC uses the already-cached Whisper small model, CPU int8, English command transcription, VAD, and low-confidence segment filtering. The finalized transcript replaces the provisional text before any conversation/tool request is sent. This improves the recognition architecture without introducing a paid/cloud speech provider; actual name/accent accuracy still requires testing.

The endpoint only transcribes; it never executes actions or creates another audio file. Ordinary archival capture and English/Mandarin background transcription remain unchanged. Command audio is held in memory (maximum 21 seconds); the phone still uses existing 20-second command limits and provisional recognition for endpoint timing. Whisper does not recover audio that was clipped before it was captured. No automatic action fallback to Vosk occurs when PC transcription fails. Last command shows the finalized PC transcript; Hearing now is labeled provisional.

Expect a few additional seconds before the answer. A synthetic English calendar command including Jarvis test was recognized correctly in about four seconds including model initialization on this PC; this is not a real-user accuracy benchmark. Follow-up silence still exits conversation, now after the PC confirms an empty transcript. Closing phrases are checked against the finalized transcript and therefore also require the PC connection. The phone keeps its existing continuous conversation behavior.


## Custom Jarvis voice (phone 0.6)

Phone replies use the local VoxCPM2 Jarvis adapter and supplied reference recording through the authenticated PC speech endpoint. A persistent worker now keeps the model in system RAM between replies. Local tests measured 5.2 seconds for a warm short reply and 11.0 seconds for a warm two-sentence reply, down from 27.2 and 34.0 seconds. The first uncached reply after restarting still takes about 27 seconds, and recognition/conversation/network time is additional. Wake acknowledgements remain cached. Android TTS remains the fallback, shown in the app Voice field. Playback waits for the complete WAV. See [voice setup and limitations](VOICE_SETUP.md).


## OpenJarvis candidate backend

A pinned, isolated OpenJarvis planning adapter and repeatable comparison are available. The current backend remains active: it passed 10/10 synthetic acceptance cases against 8/10 for the candidate, which used about 27% more tokens overall. See [integration details and measurements](OPENJARVIS_INTEGRATION.md).
