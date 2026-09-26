package local.jarvis.capture;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.*;

/** Consumes copies of the recorder's PCM without blocking it. Owns offline wake detection,
 * question recognition, authenticated requests, and local speech. Close cancels all interaction.
 * Speech playback is excluded from recognition, but continuous archival capture is unchanged. */
final class VoiceLoop implements AutoCloseable {
    private final Context context;
    private final SharedPreferences prefs;
    private final ArrayBlockingQueue<byte[]> audio = new ArrayBlockingQueue<>(12);
    private final Handler main = new Handler(Looper.getMainLooper());
    private final CountDownLatch speechReady = new CountDownLatch(1);
    private final Thread worker;
    private volatile boolean closed, accepting, speechAvailable, overflow;
    private volatile long acceptAfter;
    private volatile CountDownLatch spoken;
    private volatile boolean speechFailed;
    private volatile HttpURLConnection connection;
    private TextToSpeech speech;
    private MediaPlayer player;

    VoiceLoop(Context context) {
        this.context = context.getApplicationContext();
        prefs = context.getSharedPreferences("jarvis", Context.MODE_PRIVATE);
        File[] oldSpeech = context.getCacheDir().listFiles((directory, name) -> name.startsWith("jarvis-speech-") && name.endsWith(".wav"));
        if (oldSpeech != null) for (File file : oldSpeech) file.delete();
        status("Loading offline voice model...");
        speech = new TextToSpeech(context, result -> main.post(() -> {
            if (closed) { speechReady.countDown(); return; }
            if (result == TextToSpeech.SUCCESS) {
                speech.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
                if (speech.getVoices() != null) for (Voice voice : speech.getVoices()) {
                    if (voice.getLocale().getLanguage().equals(Locale.ENGLISH.getLanguage()) && !voice.isNetworkConnectionRequired()) {
                        speechAvailable = speech.setVoice(voice) == TextToSpeech.SUCCESS;
                        if (speechAvailable) break;
                    }
                }
            }
            speechReady.countDown();
        }));
        speech.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            public void onStart(String id) {}
            public void onDone(String id) { finishSpeech(id, false); }
            public void onError(String id) { finishSpeech(id, true); }
        });
        worker = new Thread(this::run, "jarvis-voice");
        worker.start();
    }

    void offer(byte[] pcm, int count) {
        if (!closed && accepting && SystemClock.elapsedRealtime() >= acceptAfter
                && !audio.offer(Arrays.copyOf(pcm, count))) overflow = true;
    }

    private void status(String value) { if (!closed) prefs.edit().putString("voice", value).apply(); }

    private void run() {
        try {
            File modelDirectory = new File(context.getFilesDir(), "voice-model-en-0.15");
            File ready = new File(modelDirectory, ".ready");
            if (!ready.exists()) {
                copyAssets("voice-model", modelDirectory);
                if (!ready.createNewFile()) throw new IOException("Cannot mark voice model ready");
            }
            try (Model model = new Model(modelDirectory.getPath());
                 Recognizer wake = new Recognizer(model, 16000, "[\"hey jarvis\", \"[unk]\"]");
                 Recognizer question = new Recognizer(model, 16000)) {
                if (!speechReady.await(15, TimeUnit.SECONDS) || !speechAvailable)
                    throw new IOException("Install an offline English voice in Android text-to-speech settings");
                listening();
                boolean conversationActive = false;
                while (!closed) {
                    try {
                    byte[] block;
                    boolean complete;
                    String words;
                    if (!conversationActive) {
                        block = audio.poll(1, TimeUnit.SECONDS);
                        if (block == null) continue;
                        if (overflow) { audio.clear(); wake.reset(); overflow = false; continue; }
                        complete = wake.acceptWaveForm(block, block.length);
                        words = new JSONObject(complete ? wake.getResult() : wake.getPartialResult())
                            .optString(complete ? "text" : "partial");
                        if (!SpeechTurn.isWakePhrase(words)) continue;
                        accepting = false; audio.clear(); wake.reset();
                        speak("I'm listening.");
                    }
                    question.reset(); audio.clear(); overflow = false;
                    // Playback has ended and queued audio was discarded. Accept the first
                    // command word immediately instead of discarding another 350 ms.
                    acceptAfter = 0;
                    accepting = true;
                    prefs.edit().putString("live_command", "").putString("last_voice_error", "").apply();
                    status(conversationActive ? "Listening for a follow-up (10 seconds). Say That's all to finish." : "Listening for your question...");
                    SpeechTurn turn = new SpeechTurn();
                    ByteArrayOutputStream commandAudio = new ByteArrayOutputStream();
                    while (!closed && !turn.finished()) {
                        block = audio.poll(1, TimeUnit.SECONDS);
                        if (block == null) { turn.elapse(1000); continue; }
                        if (overflow) break;
                        commandAudio.write(block, 0, block.length);
                        complete = question.acceptWaveForm(block, block.length);
                        words = new JSONObject(complete ? question.getResult() : question.getPartialResult())
                            .optString(complete ? "text" : "partial");
                        turn.accept(words, complete, block.length / 32);
                        String partial = turn.text();
                        if (!partial.equals(prefs.getString("live_command", "")))
                            prefs.edit().putString("live_command", partial).apply();
                    }
                    accepting = false; audio.clear();
                    if (closed) break;
                    if (overflow) {
                        prefs.edit().putString("last_voice_error", "Command interrupted: speech processing fell behind. Please repeat.")
                            .putString("live_command", "").apply();
                        speak("Please repeat your command. Speech processing fell behind.");
                        conversationActive = false;
                        wake.reset(); listening(); continue;
                    }
                    String text;
                    status("Transcribing your command on the PC...");
                    try { text = transcribe(commandAudio.toByteArray()); }
                    catch (IOException e) {
                        prefs.edit().putString("last_voice_error", "Command transcription failed: " + e.getMessage())
                            .putString("live_command", "").apply();
                        speak("I couldn't transcribe that on the PC. Please try again.");
                        conversationActive = false; wake.reset(); listening(); continue;
                    }
                    if (closed) break;
                    // Silence after a reply ends the active exchange normally. Preserve
                    // the previous command/reply rather than replacing them with an error.
                    if (text.isEmpty() && conversationActive) {
                        conversationActive = false;
                        wake.reset(); listening(); continue;
                    }
                    prefs.edit().putString("last_command", text.isEmpty() ? "No speech recognized" : text)
                        .putLong("last_command_time", System.currentTimeMillis()).putString("live_command", "")
                        .putString("last_reply", "").apply();
                    if (SpeechTurn.isEndPhrase(text)) {
                        conversationActive = false;
                        prefs.edit().putString("last_reply", "Okay. I'll wait for Hey Jarvis.").apply();
                        speak("Okay. I'll wait for Hey Jarvis.");
                    } else if (text.isEmpty()) {
                        prefs.edit().putString("last_voice_error", "No speech recognized after the acknowledgement.").apply();
                        speak("I didn't hear a question. Please try again.");
                    }
                    else {
                        status("Heard: " + text + "\nThinking...");
                        try {
                            String reply = ask(text);
                            prefs.edit().putString("last_reply", reply).apply();
                            speak(reply);
                            conversationActive = true;
                        }
                        catch (IOException e) {
                            prefs.edit().putString("last_voice_error", e.getMessage()).apply();
                            conversationActive = false;
                        }
                    }
                    if (!conversationActive) { wake.reset(); listening(); }
                    } catch (IOException e) {
                        // A failed acknowledgement or playback must not kill wake
                        // listening. Never retry an action because its reply failed.
                        prefs.edit().putString("last_voice_error", e.getMessage()).apply();
                        conversationActive = false;
                        wake.reset(); listening();
                    }
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception | LinkageError e) {
            if (!closed) prefs.edit().putString("last_voice_error", "Voice unavailable: " + e.getMessage()).apply();
            status("Voice unavailable: " + e.getMessage());
        } finally { accepting = false; audio.clear(); }
    }

    private void listening() {
        audio.clear(); overflow = false;
        acceptAfter = SystemClock.elapsedRealtime() + 350;
        accepting = true;
        status("Ready: say Hey Jarvis, then wait for I'm listening");
    }

    private String ask(String question) throws IOException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("day", LocalDate.now(ZoneId.of("Asia/Taipei")).toString()); payload.put("question", question);
            String answer = request("/ask", payload.toString().getBytes(StandardCharsets.UTF_8), "application/json", 210000).getString("answer");
            if (answer.isEmpty() || answer.length() > 4000) throw new IOException("Invalid answer length");
            return answer;
        } catch (org.json.JSONException e) { throw new IOException("Invalid PC answer", e); }
    }

    private String transcribe(byte[] pcm) throws IOException {
        if (pcm.length < 3200) return "";
        try {
            String text = request("/transcribe-command", pcm, "audio/pcm;rate=16000;channels=1;format=s16le", 90000).getString("text");
            if (text.length() > 1000) throw new IOException("Invalid transcript length");
            return text.trim();
        } catch (org.json.JSONException e) { throw new IOException("Invalid PC transcript", e); }
    }

    /** Shared authenticated transport; audio requests cannot invoke actions. */
    private JSONObject request(String route, byte[] body, String contentType, int timeout) throws IOException {
        try { return new JSONObject(new String(requestBytes(route, body, contentType, timeout, 65536), StandardCharsets.UTF_8)); }
        catch (org.json.JSONException e) { throw new IOException("Invalid PC response", e); }
    }

    private byte[] requestBytes(String route, byte[] body, String contentType, int timeout, int maximum) throws IOException {
        HttpURLConnection request = (HttpURLConnection) new URL(prefs.getString("endpoint", "") + route).openConnection();
        connection = request;
        try {
            if (closed) throw new IOException("Stopped");
            request.setConnectTimeout(10000); request.setReadTimeout(timeout);
            request.setInstanceFollowRedirects(false); request.setRequestMethod("POST"); request.setDoOutput(true);
            request.setRequestProperty("Authorization", "Bearer " + prefs.getString("token", ""));
            request.setRequestProperty("Content-Type", contentType);
            request.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = request.getOutputStream()) { output.write(body); }
            int code = request.getResponseCode();
            if (code != 200) throw new IOException("PC returned HTTP " + code);
            if (route.equals("/speak") && !"audio/wav".equals(request.getContentType()))
                throw new IOException("Invalid speech response");
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = request.getInputStream()) {
                byte[] buffer = new byte[4096]; int count;
                while ((count = input.read(buffer)) != -1) {
                    if (output.size() + count > maximum) throw new IOException("Oversized response");
                    output.write(buffer, 0, count);
                }
            }
            return output.toByteArray();
        }
        finally { request.disconnect(); connection = null; }
    }

    private void finishSpeech(String id, boolean failed) {
        CountDownLatch pending = spoken;
        if (pending != null && id.equals(Integer.toHexString(System.identityHashCode(pending)))) {
            speechFailed = failed; pending.countDown();
        }
    }

    private void speak(String text) throws IOException, InterruptedException {
        if (closed) return;
        status("Preparing voice...");
        try {
            speakRemote(text);
            prefs.edit().putString("speech_engine", "Jarvis custom voice").apply();
            return;
        } catch (PartialSpeechException e) {
            prefs.edit().putString("speech_engine", "Custom speech interrupted; reply not replayed").apply();
            throw e;
        } catch (IOException e) {
            if (closed) return;
            prefs.edit().putString("speech_engine", "Android fallback: " + e.getMessage()).apply();
        }
        status(text);
        CountDownLatch pending = new CountDownLatch(1); spoken = pending; speechFailed = false;
        String id = Integer.toHexString(System.identityHashCode(pending));
        main.post(() -> {
            if (closed || speech.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) == TextToSpeech.ERROR)
                finishSpeech(id, true);
        });
        if (!pending.await(180, TimeUnit.SECONDS) || speechFailed) throw new IOException("Phone speech playback failed");
        spoken = null;
    }

    /** Play private PC-rendered WAV without opening another microphone or retaining replies. */
    private void speakRemote(String text) throws IOException, InterruptedException {
        byte[] body;
        try { body = new JSONObject().put("text", text).toString().getBytes(StandardCharsets.UTF_8); }
        catch (org.json.JSONException e) { throw new IOException("Invalid speech text", e); }
        HttpURLConnection request = (HttpURLConnection) new URL(prefs.getString("endpoint", "") + "/speak-stream").openConnection();
        connection = request;
        boolean playbackStarted = false;
        try {
            if (closed) return;
            request.setConnectTimeout(10000); request.setReadTimeout(185000);
            request.setInstanceFollowRedirects(false); request.setRequestMethod("POST"); request.setDoOutput(true);
            request.setRequestProperty("Authorization", "Bearer " + prefs.getString("token", ""));
            request.setRequestProperty("Content-Type", "application/json");
            request.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = request.getOutputStream()) { output.write(body); }
            if (request.getResponseCode() != 200) throw new IOException("PC returned HTTP " + request.getResponseCode());
            if (!"application/x-jarvis-wav-stream".equals(request.getContentType()))
                throw new IOException("Invalid speech stream");
            try (InputStream input = request.getInputStream()) {
                SpeechFrames frames = new SpeechFrames(input);
                byte[] wav;
                while (!closed && (wav = frames.next()) != null) {
                    playbackStarted = true;
                    playWav(wav);
                }
            }
        } catch (IOException e) {
            if (playbackStarted) throw new PartialSpeechException(e);
            throw e;
        } finally { request.disconnect(); connection = null; }
    }

    private static final class PartialSpeechException extends IOException {
        PartialSpeechException(IOException cause) { super("Speech interrupted; request was not repeated", cause); }
    }

    private void playWav(byte[] wav) throws IOException, InterruptedException {
        if (closed) return;
        File file = File.createTempFile("jarvis-speech-", ".wav", context.getCacheDir());
        CountDownLatch pending = new CountDownLatch(1);
        boolean[] failed = {false};
        try {
            try (FileOutputStream output = new FileOutputStream(file)) { output.write(wav); }
            main.post(() -> {
                if (closed) { failed[0] = true; pending.countDown(); return; }
                MediaPlayer current = new MediaPlayer(); player = current;
                current.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
                current.setOnCompletionListener(mp -> pending.countDown());
                current.setOnErrorListener((mp, what, extra) -> { failed[0] = true; pending.countDown(); return true; });
                current.setOnPreparedListener(mp -> {
                    try { if (!closed) mp.start(); else pending.countDown(); }
                    catch (RuntimeException e) { failed[0] = true; pending.countDown(); }
                });
                try { current.setDataSource(file.getPath()); current.prepareAsync(); }
                catch (IOException | RuntimeException e) { failed[0] = true; pending.countDown(); }
            });
            status("Speaking...");
            if (!pending.await(180, TimeUnit.SECONDS) || failed[0]) throw new IOException("Custom speech playback failed");
        } finally {
            main.post(() -> {
                if (player != null) { player.release(); player = null; }
                file.delete();
            });
        }
    }

    private void copyAssets(String source, File destination) throws IOException {
        if (closed) throw new IOException("Stopped");
        String[] children = context.getAssets().list(source);
        if (children != null && children.length > 0) {
            if (!destination.isDirectory() && !destination.mkdirs()) throw new IOException("Cannot install voice model");
            for (String child : children) copyAssets(source + "/" + child, new File(destination, child));
        } else try (InputStream input = context.getAssets().open(source); OutputStream output = new FileOutputStream(destination)) {
            byte[] buffer = new byte[32768]; int count;
            while ((count = input.read(buffer)) != -1) { if (closed) throw new IOException("Stopped"); output.write(buffer, 0, count); }
        }
    }

    @Override public void close() {
        closed = true; accepting = false; audio.clear();
        HttpURLConnection pending = connection; if (pending != null) pending.disconnect();
        worker.interrupt();
        main.post(() -> { if (player != null) { player.release(); player = null; } speech.stop(); speech.shutdown(); });
    }
}
