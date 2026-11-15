package com.corthexhq.marong;

import android.Manifest;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import androidx.activity.OnBackPressedCallback;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    private static final String PREFS = "marong_app";
    private static final String ASKED_NOTIFICATIONS = "asked_notifications";
    private static final int NOTIFICATION_REQUEST = 101;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // Plugins load before the WebView opens the call page (SPEC-102).
        registerPlugin(MarongCallPlugin.class);
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

        askForNotificationsOnce();
    }

    /** Android 13+: the "통화 중" notification shows only with this permission (SPEC-103). */
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
