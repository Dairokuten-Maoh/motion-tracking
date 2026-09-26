package local.jarvis.capture;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.text.InputType;
import android.widget.*;
import java.net.URI;

/** Pairing and explicit recording controls; capture never begins on app launch. */
public class MainActivity extends Activity {
    private EditText endpoint, token;
    private TextView status, commandHistory;
    private final Handler handler = new Handler();
    private final Runnable refresh = new Runnable() {
        public void run() {
            SharedPreferences prefs = getSharedPreferences("jarvis", MODE_PRIVATE);
            status.setText((CaptureService.running ? "Recording service active\n" : "Recording stopped\n")
                + prefs.getString("status", "Ready to pair") + "\n" + prefs.getString("upload", "No uploads yet")
                + "\n" + (CaptureService.running ? prefs.getString("voice", "Voice loading...") : "Voice stopped"));
            long lastTime = prefs.getLong("last_command_time", 0);
            String time = lastTime == 0 ? "" : " (" + java.text.DateFormat.getTimeInstance().format(new java.util.Date(lastTime)) + ")";
            commandHistory.setText("Hearing now (provisional): " + prefs.getString("live_command", "")
                + "\n\nLast command (PC Whisper)" + time + ":\n" + prefs.getString("last_command", "No command yet")
                + "\n\nLast reply:\n" + prefs.getString("last_reply", "")
                + "\n\nVoice: " + prefs.getString("speech_engine", "Not used yet")
                + "\n\nLast error:\n" + prefs.getString("last_voice_error", ""));
            handler.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        SharedPreferences prefs = getSharedPreferences("jarvis", MODE_PRIVATE);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40, 50, 40, 30);
        TextView title = new TextView(this);
        title.setText("Jarvis · Capture prototype"); title.setTextSize(24); layout.addView(title);
        TextView help = new TextView(this);
        help.setText("Say Hey Jarvis, wait for I'm listening, then speak your English command. "
            + "After each reply, speak again within 10 seconds without repeating Hey Jarvis. Say That's all to finish. "
            + "Your recognized command and reply stay visible below. "
            + "The PC must be connected. Call capture and location are not enabled.\n");
        layout.addView(help);
        endpoint = new EditText(this);
        endpoint.setHint("Receiver URL"); endpoint.setSingleLine(true);
        endpoint.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        endpoint.setText(prefs.getString("endpoint", "http://127.0.0.1:8765")); layout.addView(endpoint);
        token = new EditText(this);
        token.setHint("Pairing token from PC token.txt"); token.setSingleLine(true);
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setText(prefs.getString("token", "")); layout.addView(token);
        Button start = new Button(this); start.setText("Start listening"); layout.addView(start);
        start.setOnClickListener(v -> startCapture());
        Button stop = new Button(this); stop.setText("Stop listening"); layout.addView(stop);
        stop.setOnClickListener(v -> stopService(new Intent(this, CaptureService.class)));
        Button sync = new Button(this); sync.setText("Retry queued uploads (no recording)"); layout.addView(sync);
        sync.setOnClickListener(v -> {
            if (saveSettings()) new Thread(() -> new UploadQueue(this).uploadAll()).start();
        });
        status = new TextView(this); layout.addView(status);
        commandHistory = new TextView(this); commandHistory.setTextIsSelectable(true); layout.addView(commandHistory);
        ScrollView scroll = new ScrollView(this); scroll.addView(layout); setContentView(scroll);
    }

    private boolean saveSettings() {
        if (CaptureService.running) {
            Toast.makeText(this, "Stop recording before changing pairing settings", Toast.LENGTH_LONG).show();
            return false;
        }
        String url = endpoint.getText().toString().trim().replaceAll("/+$", "");
        try {
            URI uri = new URI(url);
            if (!("http".equals(uri.getScheme()) || "https".equals(uri.getScheme()))
                || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null
                || uri.getFragment() != null || !uri.getPath().isEmpty()
                || token.getText().toString().trim().length() < 32) throw new Exception();
        } catch (Exception e) {
            Toast.makeText(this, "Enter a base http(s) URL and a token of at least 32 characters", Toast.LENGTH_LONG).show();
            return false;
        }
        getSharedPreferences("jarvis", MODE_PRIVATE).edit().putString("endpoint", url)
            .putString("token", token.getText().toString().trim()).apply();
        return true;
    }

    private void startCapture() {
        if (!saveSettings()) return;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(Build.VERSION.SDK_INT >= 33
                ? new String[]{Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS}
                : new String[]{Manifest.permission.RECORD_AUDIO}, 1);
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 2);
        startForegroundService(new Intent(this, CaptureService.class));
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 1 && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) startCapture();
    }
    @Override public void onResume() { super.onResume(); handler.post(refresh); }
    @Override public void onPause() { handler.removeCallbacks(refresh); super.onPause(); }
}
