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
import com.getcapacitor.Logger;
import com.google.firebase.messaging.FirebaseMessaging;

public class MainActivity extends BridgeActivity {

    private static final String PREFS = "marong_app";
    private static final String ASKED_NOTIFICATIONS = "asked_notifications";
    private static final int NOTIFICATION_REQUEST = 101;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // Plugins load before the WebView opens the call page (SPEC-102).
        registerPlugin(MarongCallPlugin.class);
        registerPlugin(MarongPushPlugin.class);
        super.onCreate(savedInstanceState);

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
        if (savedInstanceState == null) {
            openFromIntent(getIntent());
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
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
     * opens the page its "open" value names (docs/app-chat.md SPEC-122). During a call nothing
     * opens: leaving the call page would end the call.
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
            // Only a ring this phone received, once: another app cannot start a call this way.
            if (!PushState.answerRing(this, ringId, System.currentTimeMillis())) {
                return;
            }
            Ring.cancel(this);
            if (!CallControl.isActive()) {
                webView.loadUrl(PushLinks.ringUrl(appUrl, ringId));
            }
            return;
        }
        String path = PushLinks.openPath(intent.getStringExtra(Talk.EXTRA_OPEN));
        if (path != null && !CallControl.isActive()) {
            webView.loadUrl(PushLinks.pageUrl(appUrl, path));
        }
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
