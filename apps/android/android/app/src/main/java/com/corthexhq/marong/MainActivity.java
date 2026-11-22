package com.corthexhq.marong;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.webkit.WebView;
import androidx.activity.OnBackPressedCallback;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;
import com.getcapacitor.Logger;
import com.google.firebase.messaging.FirebaseMessaging;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The call window (SPEC-101 to SPEC-105). From 0.2.1 the chat opens in its own window above it
 * (D20, docs/app-chat.md SPEC-143), so this window keeps the call page and a call going on in it.
 */
public class MainActivity extends BridgeActivity {

    private static final String PREFS = "marong_app";
    private static final String ASKED_NOTIFICATIONS = "asked_notifications";
    private static final int NOTIFICATION_REQUEST = 101;

    /**
     * True while super.onCreate runs. Capacitor's BridgeActivity.load() hands the launch intent to
     * onNewIntent from inside onCreate; onCreate below opens it once itself, after the restore
     * check. Without this a cold start from a chat notification opened two chat windows (BUG-107).
     */
    private boolean creating;
    private String coldRingId;
    private long coldAnsweredAt;
    private int answerAttempt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // Plugins load before the WebView opens the call page (SPEC-102); the window's own handling first.
        registerPlugin(MarongWindowPlugin.class);
        registerPlugin(MarongCallPlugin.class);
        registerPlugin(MarongPushPlugin.class);
        if (savedInstanceState == null) {
            configureColdAnswer(getIntent());
        }
        creating = true;
        try {
            super.onCreate(savedInstanceState);
        } finally {
            creating = false;
        }

        // Back never closes the page: closing it would end a call and lose the screen (SPEC-105).
        getOnBackPressedDispatcher()
            .addCallback(
                this,
                new OnBackPressedCallback(true) {
                    @Override
                    public void handleOnBackPressed() {
                        moveTaskToBack(true);
                    }
                }
            );

        Channels.ensure(this);
        registerForMessages();
        askForNotificationsOnce();
        // A restored window keeps the page it had: an old tap must not open a page or answer again.
        if (savedInstanceState == null && coldRingId == null) {
            openFromIntent(getIntent());
        }
    }

    String coldRingScript() {
        return RingAnswer.coldScript(coldRingId, coldAnsweredAt);
    }

    private static boolean isAnswer(Intent intent) {
        return intent != null && Ring.ACTION_ANSWER.equals(intent.getAction())
            && (intent.getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) == 0;
    }

    private static long answeredAt(Intent intent, long now) {
        long tap = intent.getLongExtra(Ring.EXTRA_ANSWERED_AT, now);
        return tap > 0 && tap <= now && now - tap <= PushLinks.RING_MAX_AGE_MS ? tap : now;
    }

    /** Capacitor applies server.appStartPath before loading its first WebView document. */
    @SuppressWarnings("deprecation")
    private void configureColdAnswer(Intent intent) {
        if (!isAnswer(intent) || CallControl.isActive()) {
            return;
        }
        long now = System.currentTimeMillis();
        String ringId = intent.getStringExtra(Ring.EXTRA_RING_ID);
        if (!PushLinks.isRingId(ringId)) {
            return;
        }
        String asset = MarongWindowPlugin.readAsset(this, "capacitor.config.json");
        if (asset == null) {
            return;
        }
        try {
            JSONObject document = new JSONObject(asset);
            JSONObject server = document.getJSONObject("server");
            String serverUrl = server.getString("url");
            server.put("url", PushLinks.pageUrl(serverUrl, ""));
            server.put("appStartPath", "/?ring=" + ringId);
            boolean debuggable = (getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
            JSONObject android = document.getJSONObject("android");
            if (!android.has("webContentsDebuggingEnabled")) {
                android.put("webContentsDebuggingEnabled", debuggable);
            }
            CapConfig ringConfig = new CapConfig(getAssets(), document);
            if (PushState.answerRing(this, ringId, now)) {
                Ring.cancel(this);
                coldRingId = ringId;
                coldAnsweredAt = answeredAt(intent, now);
                config = ringConfig;
            }
        } catch (JSONException invalidConfig) {
            Logger.warn("MarongRing", "ring_start_config_failed");
        }
    }

    @Override
    public void onStart() {
        AppUpdateJob.activityStarted(this);
        super.onStart();
    }

    @Override
    public void onStop() {
        super.onStop();
        AppUpdateJob.activityStopped(this);
    }

    @Override
    public void onResume() {
        super.onResume();
        AppUpdateJob.check(this);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        if (creating) {
            return; // The launch intent: onCreate opens it once (BUG-107).
        }
        setIntent(intent);
        openFromIntent(intent);
    }

    /**
     * Asks FCM for this installation's id; it arrives in MarongMessagingService.onRegistered
     * (docs/app-chat.md SPEC-121). Without google-services.json in the build, or without Google
     * Play services, there is no id and the friend's messages go to Discord.
     */
    private void registerForMessages() {
        try {
            FirebaseMessaging.getInstance()
                .register()
                .addOnFailureListener(e -> Logger.warn("MarongPush", "fcm_register_failed " + e.getClass().getSimpleName()));
        } catch (IllegalStateException e) {
            Logger.warn("MarongPush", "fcm_unavailable");
        }
    }

    /**
     * 받기 on a ring opens the call page with the ring (docs/app-ring.md SPEC-134); a notification
     * opens the page its "open" value names (docs/app-chat.md SPEC-122). The chat opens in the chat
     * window, also during a call (SPEC-146). This window's page changes only when no call is going
     * on: leaving the call page would end the call.
     */
    private void openFromIntent(Intent intent) {
        if (intent == null || (intent.getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0) {
            return;
        }
        String appUrl = bridge == null ? null : bridge.getServerUrl();
        WebView webView = bridge == null ? null : bridge.getWebView();
        if (appUrl == null || webView == null) {
            return;
        }
        if (Ring.ACTION_ANSWER.equals(intent.getAction())) {
            String ringId = intent.getStringExtra(Ring.EXTRA_RING_ID);
            long now = System.currentTimeMillis();
            // Only a ring this phone received, once: another app cannot start a call this way.
            if (!PushState.answerRing(this, ringId, now)) {
                return;
            }
            Ring.cancel(this);
            if (!CallControl.isActive()) {
                answerLoadedRing(webView, appUrl, ringId, answeredAt(intent, now));
            }
            return;
        }
        String path = PushLinks.openPath(intent.getStringExtra(Talk.EXTRA_OPEN));
        if (AppWindows.CHAT_PATH.equals(path)) {
            ChatActivity.open(this);
        } else if (path != null && !CallControl.isActive()) {
            webView.loadUrl(PushLinks.pageUrl(appUrl, path));
        }
    }

    private void answerLoadedRing(WebView webView, String appUrl, String ringId, long answeredAt) {
        int attempt = ++answerAttempt;
        String fallback = PushLinks.ringUrl(appUrl, ringId);
        if (webView.getProgress() != 100 || !AppUrls.isCallPage(webView.getUrl(), appUrl)) {
            webView.loadUrl(fallback);
            return;
        }
        webView.evaluateJavascript(RingAnswer.answerScript(ringId, answeredAt), result -> {
            if (!"true".equals(result) && answerAttempt == attempt && !isFinishing() && !isDestroyed()
                && !CallControl.isActive()) {
                webView.loadUrl(fallback);
            }
        });
    }

    /**
     * Android 13+: the "통화 중" notification (SPEC-103), messages (docs/app-chat.md SPEC-121) and
     * rings (docs/app-ring.md SPEC-132) show only with this permission. Asked once; after that the
     * chat menu offers the settings (SCR-109).
     */
    private void askForNotificationsOnce() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (prefs.getBoolean(ASKED_NOTIFICATIONS, false)) {
            return;
        }
        prefs.edit().putBoolean(ASKED_NOTIFICATIONS, true).apply();
        ActivityCompat.requestPermissions(this, new String[] { Manifest.permission.POST_NOTIFICATIONS }, NOTIFICATION_REQUEST);
    }
}
