package local.jarvis.capture;

import android.app.*;
import android.Manifest;
import android.content.*;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.media.*;
import android.os.*;
import java.io.*;
import java.nio.file.Files;
import java.util.UUID;
import java.util.concurrent.*;

/** Owns the microphone lifetime and continuous PCM capture; file boundaries do not reopen it. */
public class CaptureService extends Service {
    static volatile boolean running = false;
    private volatile boolean recording = false;
    private PowerManager.WakeLock wakeLock;
    private ScheduledExecutorService uploader;
    private Thread capture;
    private VoiceLoop voice;
    private static final int RATE = 16000;
    private static final long MAX_QUEUE = 2L * 1024 * 1024 * 1024;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && "STOP".equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (running) return START_NOT_STICKY;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("capture", "Audio capture", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, CaptureService.class).setAction("STOP"), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "capture")
            .setContentTitle("Jarvis is recording nearby audio")
            .setContentText("Tap to view status or stop listening")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentIntent(open)
            .addAction(new Notification.Action.Builder(null, "Stop", stop).build()).setOngoing(true).build();
        startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        running = true; recording = true;
        voice = new VoiceLoop(this);
        wakeLock = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:capture");
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire(120000);
        uploader = Executors.newSingleThreadScheduledExecutor();
        uploader.scheduleWithFixedDelay(() -> new UploadQueue(this).uploadAll(), 0, 15, TimeUnit.SECONDS);
        capture = new Thread(this::record, "jarvis-microphone"); capture.start();
        return START_NOT_STICKY;
    }

    private void status(String value) { getSharedPreferences("jarvis", MODE_PRIVATE).edit().putString("status", value).apply(); }

    private void record() {
        AudioRecord audio = null;
        try {
            File directory = UploadQueue.directory(this);
            // Recover finalized samples after a process interruption before retrying upload.
            File[] interrupted = directory.listFiles((dir, name) -> name.endsWith(".part"));
            if (interrupted != null) for (File file : interrupted) finish(file);
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                throw new IOException("Microphone permission is required");
            int buffer = Math.max(6400, AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT));
            audio = new AudioRecord(MediaRecorder.AudioSource.MIC, RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, buffer * 2);
            if (audio.getState() != AudioRecord.STATE_INITIALIZED) throw new IOException("Microphone unavailable");
            audio.startRecording();
            byte[] bytes = new byte[buffer];
            while (recording) {
                // Renew per chunk; a wedged capture must not hold the CPU awake forever.
                wakeLock.acquire(120000);
                long queued = 0;
                File[] files = directory.listFiles();
                if (files != null) for (File file : files) {
                    long started = Long.parseLong(file.getName().split("_", 2)[0]);
                    if (started < System.currentTimeMillis() - 30L * 86400000L) Files.deleteIfExists(file.toPath());
                    else queued += file.length();
                }
                if (queued >= MAX_QUEUE || directory.getUsableSpace() < 100 * 1024 * 1024)
                    throw new IOException("Queue or disk full; sync recordings before restarting");
                File part = new File(directory, System.currentTimeMillis() + "_" + UUID.randomUUID() + ".part");
                try (RandomAccessFile output = new RandomAccessFile(part, "rw")) {
                    output.write(new byte[44]);
                    int remaining = RATE * 2 * 30;
                    status("Capturing · " + (queued / 1024 / 1024) + " MB waiting to upload");
                    while (recording && remaining > 0) {
                        int count = audio.read(bytes, 0, Math.min(bytes.length, remaining), AudioRecord.READ_BLOCKING);
                        if (count <= 0) throw new IOException("Microphone read failed: " + count);
                        output.write(bytes, 0, count); remaining -= count;
                        voice.offer(bytes, count);
                    }
                } finally { finish(part); }
            }
            status("Recording stopped; completed audio remains queued until uploaded");
        } catch (Exception e) {
            status("Capture stopped: " + e.getMessage());
        } finally {
            if (audio != null) { try { audio.stop(); } catch (Exception ignored) {} audio.release(); }
            recording = false;
            // The final short WAV is now closed. Attempt to send it even after Stop.
            // Offline failures remain in the durable queue for the next retry.
            new Thread(() -> new UploadQueue(this).uploadAll(), "jarvis-final-upload").start();
            stopSelf();
        }
    }

    /** Publish a complete WAV atomically so the uploader never observes partial audio. */
    private void finish(File part) throws IOException {
        long length = part.length() - 44;
        if (length <= 0) { Files.deleteIfExists(part.toPath()); return; }
        length -= length % 2;
        try (RandomAccessFile file = new RandomAccessFile(part, "rw")) {
            file.setLength(44 + length); file.seek(0);
            file.writeBytes("RIFF"); littleInt(file, (int)length + 36); file.writeBytes("WAVEfmt ");
            littleInt(file, 16); littleShort(file, 1); littleShort(file, 1);
            littleInt(file, RATE); littleInt(file, RATE * 2); littleShort(file, 2); littleShort(file, 16);
            file.writeBytes("data"); littleInt(file, (int)length); file.getFD().sync();
        }
        Files.move(part.toPath(), new File(part.getParentFile(), part.getName().replace(".part", ".wav")).toPath());
    }
    private void littleInt(RandomAccessFile file, int value) throws IOException { file.writeInt(Integer.reverseBytes(value)); }
    private void littleShort(RandomAccessFile file, int value) throws IOException { file.writeShort(Short.reverseBytes((short)value)); }

    @Override public void onDestroy() {
        recording = false;
        if (voice != null) voice.close();
        // Let the worker close its final chunk before another session can start.
        if (capture != null) try { capture.join(2000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        if (uploader != null) uploader.shutdown();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        running = false;
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
