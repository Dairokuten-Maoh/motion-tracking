# Prototype verification

## Completed locally

- Built the installable debug APK with JDK 17, Gradle 8.9, and Android SDK 35. `assembleDebug` and `lintDebug` completed successfully; remaining lint warnings concern English-only UI strings and conservative disk-space checks, not build errors.
- Seven receiver integration tests passed: authentication, duplicate retries after lost acknowledgement, conflicting IDs, malformed/truncated WAV and traversal rejection, persistence after restart, timestamp validation, and raw expiration without transcript deletion.
- Installed the isolated Python environment and downloaded the multilingual Whisper `small` model.
- Synthesized English and Mandarin audio using Windows voices (no live microphone recording), ingested both through the archive, and ran the real transcription worker.
- English output: “Hello Jarvis. Please remember my meeting tomorrow at 10 in the morning.”
- Mandarin output: “明天下午3点开会,请帮我记住。”

## Physical Pixel test completed

Seven real clips uploaded and transcribed. Mandarin and the English phrase “Testing, testing, English phrase” were recognized. Capture rolled into a new clip while Android reported Dozing. Stopping capture ended the service; a manual retry uploaded the final short clip, leaving an empty phone queue. These establish a short successful test, not all-day reliability.

## Daily-history milestone

- Fifteen automated tests pass, including Taipei date boundaries, bilingual search, authenticated audio playback, audio expiration, invalid citation rejection, late-transcription races, and retaining the previous entry after summary failure.
- Android rebuild and lint pass with no errors after adding the final upload attempt on Stop.
- JavaScript syntax check passes. Browser automation was unavailable in this session, so the dashboard has not been visually verified.
- The installed local `qwen2.5:14b` model generated an English entry from the seven real clips with validated exact-quote citations. No task candidates were extracted. A preview of the current half-hour was generated explicitly; normal operation waits for each period to close.
- Live HTTP checks passed for the dashboard assets, authenticated timeline (all seven clips), and authenticated WAV playback. The receiver and diary worker are running locally. Updated APK installed on the connected Pixel without starting its microphone.

Long-duration battery use, network reconnection, call/microphone interruptions, and the updated automatic final-upload behavior still require physical testing. Use the acceptance checklist in README.md.

## AWS archive integration

- 25 automated tests pass. New cases cover verified encrypted uploads, lost upload acknowledgements, corruption rejection, expired-object deletion retries, transcript preservation, cloud playback fallback, and rejection of public/versioned buckets.
- Actual boto3 request shapes were checked with botocore Stubber. The exact inline Lambda cleanup code was executed against a fake paginator and verified to delete only expired recording keys.
- `cfn-lint aws/archive-stack.yaml` passes without findings. JavaScript syntax check passes after displaying archive status in the timeline.
- At the integration-only stage, the SDK was installed but cloud deployment was not yet configured. Live results are recorded below.

## Live AWS verification (after account sign-in)

- Stack `jarvis-audio-archive` is CREATE_COMPLETE in Sydney (`ap-southeast-2`). Private-access and 30-day lifecycle checks passed.
- Seven recordings uploaded using a dedicated IAM service identity with the stack's bucket-only policy as both its attached policy and permissions boundary. Credential values were saved only to the local AWS credential store and not displayed.
- Downloaded all seven cloud objects and verified their SHA-256 digests against the local archive.
- Invoked the deployed cleanup Lambda successfully (`deleted: 0` for these fresh recordings); its hourly schedule is ENABLED. Future timed expiration and actual billing still require observation.
- Continuous archive worker started. Temporary root setup login was signed out; ongoing archiving uses the restricted `jarvis-archive` profile.

## Ask Jarvis

- 34 automated tests pass, covering dated retrieval, explicit partial coverage, missing evidence, invalid citations, concurrent requests, authentication and input validation, alongside prior archive tests.
- Live authenticated `/ask` returned the complete phrase “Testing, testing, English phrase” with one exact source citation for the test recording day.
- Live “Who was I talking to?” returned “The recordings do not establish who you were talking to,” marked insufficient evidence with no invented identity.
- The running page includes the new panel; JavaScript syntax validation passes. Browser visual layout and local-voice playback have not been manually verified. Wake-word detection and voice input are not implemented.


## Phone voice loop ? 2026-09-25

- Android 0.2 APK assembled successfully; lint: 0 errors, 8 existing-style UI localization warnings.
- Four JVM tests pass: exact wake-word boundaries, replacing partial hypotheses, silent timeout, maximum question length in time.
- All 34 receiver regression tests pass. No receiver endpoint changes were needed; voice uses authenticated `/ask`.
- Synthetic Windows TTS PCM (16 kHz mono) tested against the bundled English model with desktop Vosk 0.3.45: wake recognized as `hey jarvis`; unrelated sentence produced only `[unk]`; full question recognized as `what english test phrase was recorded today`. This is model-level evidence, not an Android end-to-end test; Android uses Vosk 0.3.75.
- Model includes `jarvis` in vocabulary (index 40825). Download SHA-256: `30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498`.
- Phone absent from both `adb devices` and mDNS discovery during implementation. APK not installed yet; real microphone wake accuracy, Android local TTS availability/playback, lifecycle cancellation, locked-screen behavior, and battery use remain unverified.


## Pixel voice acceptance and remote-access preparation

- User confirmed version 0.2 woke and returned a spoken summary, then confirmed it also worked with the phone locked.
- Installed over wireless ADB; versionCode 2 / versionName 0.2 verified. Receiver forwarding was active on port 8765.
- Prepared `setup-remote-access.ps1` for private Tailscale Serve HTTPS routing to the unchanged localhost receiver. PowerShell syntax check passed. Deployment and mobile-data acceptance are pending Tailscale installation/sign-in.


## Tailscale deployed ? 2026-09-25

- PC and Pixel online in the same tailnet. Serve config: private HTTPS 443 -> http://127.0.0.1:8765, no Funnel setting.
- On-Pixel Java HTTPS probe validated the certificate using Android trust, negotiated TLS_AES_128_GCM_SHA256, and received expected HTTP 401 from /health without credentials.
- PC self-connection to its Tailscale address timed out; phone peer request succeeded. Setup script now distinguishes this self-check failure from deployment status.
- Gracefully stopped capture through app UID, updated only endpoint in private preferences while process stopped, preserved token, reopened app and restarted foreground service. Voice status returned Ready. Removed ADB reverse tcp:8765.
- App reported a successful upload at 09:53:06 Taipei and PC database confirmed a recent recording after the switch. Current endpoint saved in ignored jarvis-data/remote.json.
- Mobile-data voice acceptance remains pending user test. Home Wi-Fi success does not establish mobile-network reachability or background VPN endurance.


## Startup and recovery ? 2026-09-25

- User confirmed voice responses over mobile data with Wi-Fi off and Tailscale on.
- Registered and started limited-privilege Interactive logon task `Jarvis Personal Assistant`; no password stored. Task state Running, unlimited execution duration, restart-on-failure configured.
- Watchdog adopted the four existing project venv launchers. A second invocation exited with `Jarvis watchdog is already running`.
- Verified receiver executable and command identity, then terminated its process tree (old launcher PID 5920). Supervisor restarted it as PID 47220; authenticated localhost health returned ready. Other worker PIDs unchanged.
- Tailscale `set --unattended=true` completed successfully.
- PowerShell scripts parsed/executed successfully. Full Windows reboot/sign-in, watchdog crash recovery by Task Scheduler, Ollama failure recovery, and non-receiver worker failure paths not physically tested.


## Primary Google Calendar implementation ? 2026-09-25

- 45 receiver tests pass, including 11 new calendar tests for routing, date/time validation, missing credentials, durable create IDs after network failure, duplicate-title rejection, guest/recurrence exclusion, ETag updates, cancellation, empty lists, and deleted-create conflicts.
- Browser JavaScript syntax check passed; calendar results carry a distinct source label instead of transcript-citation claims.
- Calendar dependencies installed. Watchdog restarted receiver after deployment; authenticated live /ask returned the expected Google Calendar not connected message.
- No Google OAuth client/token exists yet. All calendar mutation tests used a fake API. OAuth enrollment, actual primary-calendar reads, and real insert/patch/delete behavior remain unverified until account setup.


## Google Calendar connected ? 2026-09-25

- Desktop OAuth sign-in completed and primary-calendar API read succeeded.
- Authenticated live /ask request for tomorrow returned a successful primary-calendar response. Event details were not printed in diagnostic output.
- No real events created, moved, or cancelled; live mutation testing and phone voice acceptance remain pending.


## Command recognition diagnostics ? 2026-09-25

- User reports wake works, commands fail, and no visible transcript. Code inspection found transient recognition text overwritten by Ready state, a 350 ms post-acknowledgement input discard, and submission at the first recognizer endpoint.
- APK 0.3 adds persistent last command/reply/error and live partial recognition. Removed post-acknowledgement discard and added segmented-command pause grace, with hard limits and recoverable queue overflow.
- Android assembleDebug, lintDebug, and all six JVM tests passed. Added pause-in-calendar-command and committed-plus-partial hard-limit regressions.
- Live authenticated PC calendar-read request still succeeds. No event edits performed during diagnosis.
- No ADB device or mDNS service is currently visible. APK not installed yet. Actual user utterance recognition and UI behavior remain unverified on phone; the underlying speech model is unchanged.

- Update: Installed APK 0.3 over wireless ADB, verified versionCode 3, restarted capture, and preserved the private HTTPS endpoint. User speech/UI acceptance is still pending.


## Internet lookup ? 2026-09-25

- User confirmed calendar create/move/cancel voice tests and phone 0.3 recognition diagnostics.
- Added explicit search routing before calendar/archive routing, bounded snippets, local model summary, source-ID validation and linked source results in the web dashboard.
- All 55 receiver tests passed (10 web-search tests); browser JavaScript syntax passed. Tests cover routing/privacy boundaries, invalid/private URL filtering, deduplication, missing results, provider errors, fabricated source IDs, and search lock cleanup.
- Live Bing/DDGS search and local Ollama summary succeeded for a public Taipei 101 height query with source links. No archive/calendar content was sent in the query.
- Current-information accuracy, long-term provider reliability, visual dashboard validation, and phone voice acceptance for web commands remain unverified. This version does not fetch full webpages.


## First conversation layer ? 2026-09-25

- Internet lookup endpoint deployment confirmed HTTP 200, web source, 3 links, and a supported snippet summary before dialogue work.
- Added local structured intent routing, per-session last-six-turn/30-minute context, private durable turn records, clarification follow-ups, relative event moves, cross-date move support, and deterministic single-candidate selection replies.
- During live-model evaluation, an unspecified dentist time was invented by the model. Added Python checks requiring date/time phrases from user requests, plus negation gating. This finding is why schema validity alone is not treated as authorization evidence.
- 70 receiver tests passed; JavaScript syntax passed. Coverage includes session isolation/reset, missing dates/times, negated edits, relative duration preservation, ambiguous/close-name selection, ETag race rejection, and unsupported plans.
- Live local-model test with a fake calendar: lunch tomorrow noon-to-one generated POST; 'Actually move it an hour later' generated PATCH to 13:00?14:00; 'Book dentist tomorrow' asked for time/duration and generated no write. Repeated after evidence-field changes; passed.
- No real calendar writes made during this implementation. Phone voice testing for natural requests/follow-ups remains pending.

- Live authenticated receiver test passed: 'What is on my schedule tomorrow?' read September 26, followed in the same session by 'How about the day after that?' reading September 27. Only calendar reads were performed.


## Continuous voice conversation 0.4 ? 2026-09-25

- User confirmed the natural-language calendar follow-up worked, then requested eliminating repeated wake phrases.
- Added active follow-up capture after successful spoken replies, silent no-speech return to wake listening, and local standalone closing-phrase handling. Recognition remains suspended during replies and requests.
- Android assembleDebug/lintDebug passed; seven JVM tests passed, including closing-phrase boundaries and existing capture timeout/pause tests.
- Physical multi-turn speech, silence exit, closing phrase exit, and feedback behavior remain pending user acceptance.

- APK 0.4 installed successfully over wireless ADB; versionCode 4 verified, capture restarted.


## Open-ended chat correction ? 2026-09-25

- Root cause: dialogue system prompt restricted chat to greetings/capability explanations. Removed that restriction and distinguished personal disclosure from archive recall/tool requests.
- Live local-model sequence after calendar history: breakup disclosure, feeling lost, and gentle activity brainstorming all routed to chat with conversational replies. No external search or calendar action was invoked by these plan tests.
- An existing endpoint test used ambiguous What happened? and implicitly invoked live Ollama. Updated it to test explicit recorded-history recall with an injected planner, retaining real HTTP/authentication/archive validation. All 70 tests now pass deterministically without that live-model dependency.
- Deployed receiver; authenticated live request expressing a rough day returned HTTP 200 and a supportive conversation reply. Phone acceptance pending; no APK update required.


## PC command transcription 0.5 ? 2026-09-25

- Added authenticated, bounded in-memory PCM transcription endpoint using cached local Whisper small CPU int8. It cannot dispatch tools or persist a second recording.
- Phone sends captured command PCM before /ask; provisional Vosk text is not used for actions when transcription fails. Wake detection, capture ownership, pause handling, and follow-up flow retained.
- Android build/lint and seven JVM tests passed. All 76 receiver tests passed, including invalid lengths, silent input, confidence filtering, inference-lock contention/release, endpoint authentication/format, and no archive side effects.
- Synthetic 16 kHz speech: Add Jarvis test to my calendar tomorrow from three PM to four PM transcribed correctly (3.64 seconds including cold model setup). Live authenticated /transcribe-command returned HTTP 200 with the same words. Test audio was never sent to /ask and no real calendar mutation occurred.
- Real user name accuracy, noisy speech, follow-up silence, network failure, and closing-phrase recognition on the updated phone remain pending acceptance.

- APK 0.5 installed over wireless ADB; versionCode 5 verified and capture restarted.

## Literal repetition correction - 2026-09-25

- Phone diagnostics showed the finalized transcript was Repeat the word Jarvis test.; the incorrect clarification came from conversation routing.
- Explicit repeat-the-word/words/phrase requests now return the supplied text without model planning or tool execution.
- All 77 receiver tests passed, including a repeated calendar instruction remaining literal text. Restarted receiver and verified authenticated HTTP 200 with exact reply Jarvis test.
- Phone voice remains Android TTS; no movie voice model has been configured.



## Custom voice 0.6 - 2026-09-25

- Converted the user-supplied 22.912-second M4A into a normalized 10-second PCM reference; original untouched. Voice data stays on this PC.
- Pinned published runtime, base and adapter revisions; verified SHA-256 of base model, AudioVAE, LoRA weights and CUDA Torch wheel. CUDA available; all 384 LoRA parameters loaded with no skipped parameters. Isolated runtime dependency check passed.
- Local preview requested: I'm here. The voice system is ready. Jarvis test. Whisper recovered all three sentences exactly. Output: 3.82 seconds; cold end-to-end render 64.8 seconds (reported model load 17.77 seconds, synthesis 34.53 seconds; remainder interpreter/import overhead). This verifies intelligibility in one sample, not voice similarity or broad pronunciation quality.
- Authenticated /speak returned HTTP 200, valid 0.96-second WAV for I'm listening., in 38.2 seconds. Repeated cached request returned in under 0.01 seconds locally. GPU peak observed around 7.2 GiB including desktop processes.
- All 83 receiver tests passed, including cross-process model exclusion, authentication, cache invalidation, timeout cleanup, and no speech archive/action side effects. Android assembleDebug/lintDebug and seven JVM tests passed.
- APK 0.6 installed successfully by wireless ADB and capture restarted. Real-phone playback, voice similarity, and follow-up acceptance remain for the user to verify.

- Phone package verified as versionCode 6 / versionName 0.6; status Ready: say Hey Jarvis, continuous capture active, upload queue empty. All three fixed interface phrases are now cached. Another fresh phrase rendered through /speak in 31.5 seconds. One warmup client connection reset after rendering; fetching that completed cached WAV immediately succeeded. Receiver remained healthy with no logged exception.



## OpenJarvis staged integration - 2026-09-25

- Added an isolated pinned OpenJarvis OrchestratorAgent/OllamaEngine candidate, bounded proposal bridge, reversible backend selection, and live synthetic comparison using the existing execution checks. No external actions run in the worker.
- All 87 receiver tests and four isolated worker checks passed. Covered invalid proposals, timeout without retries, explicit selection/rollback, optional-field defaults, multiple-proposal rejection and model-call budget.
- Final synthetic comparison: current 10/10, 10,495 tokens, 32.44 seconds total; candidate 8/10, 13,328 tokens, 39.55 seconds. Candidate cancellation returned no usable output; archive lookup omitted yesterday's date. Real cloud services, events, archive content and messages were excluded from comparison.
- Active configuration remains current. OpenJarvis multi-step execution, memory extraction and scheduling have not been activated. See OPENJARVIS_INTEGRATION.md for scope, reproducibility and limitations.

## Persistent voice worker - 2026-09-25

- Replaced per-reply interpreter/model loading with an isolated persistent process. GPU work remains serialized; weights and attention/AudioVAE caches park in CPU RAM before acknowledging completion. Torch reports about 8 MB allocated while parked. An interleaved qwen2.5:14b request completed and subsequent speech succeeded.
- Same synthetic texts and generation settings: short reply 27.172 seconds before, 5.157 seconds warm after; two-sentence reply 34.015 before, 11.047 warm after. Cold worker still took 26.672 seconds. Local Whisper recovered both requested texts exactly. This does not measure phone round-trip latency or subjective voice similarity.
- Added protocol reuse, timeout termination/restart, malformed-response and disconnect tests. An initial suite run contended with the concurrent live benchmark's GPU lock; isolated voice unit tests to their temporary lock directory. All 90 receiver tests then passed in 12.581 seconds.
- Restarted the workspace receiver through its existing watchdog. Authenticated live /speak returned valid WAVs: cold 25.734 seconds, warm 5.016 seconds, cached wake under 0.01 seconds. No APK change. Streaming playback is not implemented.
- Wireless ADB remains connected. Phone preferences currently report recording stopped and a previous Android fallback following HTTP 503; live PC checks now pass. Physical playback and follow-up acceptance remain pending with phone capture restarted.
