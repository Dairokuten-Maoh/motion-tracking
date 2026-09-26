# Local Jarvis speech

Current local status (2026-09-26): custom speech is temporarily disabled after
the user reported distortion during phone testing. Android TTS is the fallback.
The private `enabled` marker was moved to `enabled-quality-hold`; restore it only
after listening acceptance. Correct transcripts and valid WAV files do not prove
that a synthetic voice sounds good.

The custom voice uses [FuturePresentLabs/tts-jarvis](https://huggingface.co/FuturePresentLabs/tts-jarvis)
with VoxCPM2 and a local reference recording. It is synthesized speech, not an
official movie voice. Similarity depends on the reference and needs listening
evaluation. The author's unpublished reference and runtime patch are not included;
this installation uses the published upstream runtime and raw model output.

Pinned sources:

- Runtime: OpenBMB/VoxCPM `f772e498a45fbb5fb8e13fbf9b9c48be9fe33e69`
- Base: openbmb/VoxCPM2 `32279effe8c19989596f05d353d1447f51d9e915`
- Adapter: FuturePresentLabs/tts-jarvis `32beb72bbef5c7793bb5d808a4940467e7b2c5da`

The isolated Python 3.11 environment is `.tools/tts-env`. It uses matching
PyTorch/torchaudio 2.8.0 CUDA 12.8 wheels plus `receiver/requirements-voice.txt`.
The runtime checkout is `.tools/VoxCPM`, base files are `.tools/tts-model/base`,
and LoRA files are `.tools/tts-model/adapter`. All model files stay outside git.
The runtime needs config/tokenizer files, model.safetensors and audiovae.pth;
the adapter needs lora_config.json and lora_weights.safetensors. Inference uses
local paths; it does not download code or weights during a phone request.

The supplied M4A remains untouched. `jarvis-data/voice/reference.wav` contains
its opening ten seconds, converted to mono PCM16 at 24 kHz and peak-normalized
to 0.8 because the source was very quiet. This is a persistent voice configuration
asset, separate from the 30-day daily recording archive. It is not sent to AWS
or an external synthesis service.

Create `jarvis-data/voice/enabled` only after successful local synthesis checks.
Remove that marker to disable custom speech; Android speech remains the fallback.
The authenticated POST `/speak` accepts JSON with `text` (1–1200 characters) and
returns a bounded mono PCM16 WAV. It does not execute commands or add recordings.

GPU inference is serialized across Jarvis's conversation, web-summary, diary,
and voice workers. Rendering unloads qwen2.5:14b from Ollama and uses a persistent
isolated voice process. Between replies it parks model weights, attention caches,
and computed AudioVAE weights in system RAM; the measured remaining Torch GPU
allocation is about 8 MB. Ollama reloads for the next AI request. The voice worker
uses additional system RAM (about 11 GB observed during this test) to avoid
repeated Python imports and model loading. It starts on the first uncached reply,
exits when its parent closes the input pipe, and is killed on failure or timeout.
Other applications using the GPU are not managed by this lock.

On this PC, an uncached short reply improved from 27.2 seconds to 5.2 seconds
with a warm worker; a two-sentence reply improved from 34.0 to 11.0 seconds.
The first reply after a receiver restart still took 26.7 seconds. These are local
speech-rendering measurements, excluding recognition, conversation generation,
network transfer and contention for the GPU. These measurements predate sentence
streaming in phone 0.7. Both benchmark texts were recovered
exactly by local Whisper, and synthesis worked after an interleaved Ollama call.

Only fixed interface phrases such as "I'm listening." are cached on the PC.
Personal reply WAV files are temporary and removed after generation/delivery;
the phone also deletes its playback file. After a forced crash, leftover PC
render folders may require cleanup; phone leftovers are removed on the next
voice-loop start. Existing text conversation retention remains unchanged.

The phone waits for playback to finish before listening again. The app's Voice
field identifies custom speech or Android fallback. A synthesis failure never
retries the preceding action. Long replies over 1200 characters use fallback.
Generation uses six steps, guidance 2.4, seed 42, and no optional Forward audio
effects or text normalization. Names, numbers, long text and Mandarin require
further listening checks; this English adapter is not validated for Mandarin.

## Sentence streaming and interactive priority (phone 0.7)

The phone uses authenticated `/speak-stream`: each frame has a four-byte
big-endian WAV byte length and a complete PCM WAV. A zero-length frame marks
successful completion. A missing terminal frame means interruption. The server
renders bounded sentences in order; the phone plays each as it arrives while
later sentences can render. This is sentence streaming, not token-by-token audio.
Cold model loading and first-sentence synthesis still happen before playback.
The original `/speak` endpoint remains compatible with older phones.

Streams are bounded to 16 MB in total. A failure before playback can use Android
TTS. After playback starts, interruption is reported without replaying the reply
or the action. Request/playback IO failures return to wake listening. Playback
continues to suspend microphone recognition, while archival capture is unchanged.

Interactive model requests and speech streams reserve priority across processes.
Diary processing defers while a reservation exists and for 30 seconds afterward,
giving command capture and follow-ups time to proceed. A crashed reservation
expires after ten minutes. Already-running inference is not forcibly preempted:
one background batch can still delay a request, especially on a busy GPU.

Diary batches now contain at most 1,200 transcript characters and request at most
450 generated tokens. Validated intermediate results are cached for seven days,
so yielding to a conversation does not discard completed batches. Failed unchanged
snapshots retry after 5, 10, 20, 40, then 60 minutes; changed transcripts can retry
immediately. Deferral for interactive work is not recorded as a summary failure.
