package local.jarvis.capture;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.*;
import java.net.*;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONObject;

/** Finalized files are the durable queue; remove only after receiver acknowledgement. */
final class UploadQueue {
    private final Context context;
    private static final Object lock = new Object();
    UploadQueue(Context context) { this.context = context.getApplicationContext(); }
    static File directory(Context context) {
        File dir = new File(context.getFilesDir(), "queue"); dir.mkdirs(); return dir;
    }
    void uploadAll() {
        synchronized (lock) {
            SharedPreferences prefs = context.getSharedPreferences("jarvis", Context.MODE_PRIVATE);
            File[] files = directory(context).listFiles((dir, name) -> name.endsWith(".wav"));
            if (files == null) return;
            Arrays.sort(files);
            for (File file : files) {
                HttpURLConnection connection = null;
                try {
                    String[] name = file.getName().replace(".wav", "").split("_", 2);
                    long started = Long.parseLong(name[0]);
                    if (started < System.currentTimeMillis() - 30L * 86400000L) {
                        Files.deleteIfExists(file.toPath()); continue;
                    }
                    connection = (HttpURLConnection) new URL(prefs.getString("endpoint", "") + "/recordings").openConnection();
                    connection.setInstanceFollowRedirects(false);
                    connection.setConnectTimeout(10000); connection.setReadTimeout(15000);
                    connection.setRequestMethod("POST"); connection.setDoOutput(true);
                    connection.setRequestProperty("Authorization", "Bearer " + prefs.getString("token", ""));
                    connection.setRequestProperty("Content-Type", "audio/wav");
                    connection.setRequestProperty("X-Recording-Id", name[1]);
                    connection.setRequestProperty("X-Started-At", Double.toString(started / 1000.0));
                    connection.setFixedLengthStreamingMode(file.length());
                    try (OutputStream out = connection.getOutputStream()) { Files.copy(file.toPath(), out); }
                    int code = connection.getResponseCode();
                    if (code != 200 && code != 201) throw new IOException("Receiver HTTP " + code);
                    try (InputStream input = connection.getInputStream(); ByteArrayOutputStream response = new ByteArrayOutputStream()) {
                        byte[] buffer = new byte[256];
                        int count;
                        while ((count = input.read(buffer)) != -1) {
                            response.write(buffer, 0, count);
                            if (response.size() > 1024) throw new IOException("Unexpected acknowledgement");
                        }
                        if (!new JSONObject(response.toString("UTF-8")).optBoolean("stored", false))
                            throw new IOException("Recording was not acknowledged");
                    }
                    Files.delete(file.toPath());
                    prefs.edit().putString("upload", "Last upload: " + new java.util.Date()).apply();
                } catch (Exception e) {
                    prefs.edit().putString("upload", "Upload pending: " + e.getClass().getSimpleName()
                        + (e instanceof IOException && e.getMessage() != null && e.getMessage().startsWith("Receiver HTTP") ? " " + e.getMessage() : "")
                        + ". Check connection and pairing token.").apply();
                    break;
                } finally { if (connection != null) connection.disconnect(); }
            }
        }
    }
}
