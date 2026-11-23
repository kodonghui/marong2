package com.corthexhq.marong;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;
import android.text.TextUtils;
import androidx.core.app.NotificationManagerCompat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/**
 * What this phone reports to the server for notifications and rings (docs/app-chat.md SPEC-115,
 * SPEC-121 and SPEC-123, docs/app-ring.md SPEC-139), kept in app storage that is never backed up.
 */
final class PushState {

    private static final String PREFS = "marong_push";
    private static final String INSTALL_ID = "install_id";
    private static final String FID = "fid";
    private static final String RUNG = "rung";
    private static final String ANSWERED = "answered";
    private static final int RUNG_KEPT = 20;

    private PushState() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** This installation's id, made once (a random lowercase UUID). */
    static synchronized String installId(Context context) {
        SharedPreferences prefs = prefs(context);
        String id = existingInstallId(context);
        if (id == null) {
            id = UUID.randomUUID().toString();
            prefs.edit().putString(INSTALL_ID, id).apply();
        }
        return id;
    }

    static String existingInstallId(Context context) {
        String id = prefs(context).getString(INSTALL_ID, null);
        return id != null && PushLinks.isRingId(id) ? id : null;
    }

    /** The Firebase installation id FCM registered (onRegistered), or null before that. */
    static String fid(Context context) {
        return prefs(context).getString(FID, null);
    }

    /** True when the stored id changed. */
    static synchronized boolean setFid(Context context, String fid) {
        SharedPreferences prefs = prefs(context);
        if (fid == null || fid.equals(prefs.getString(FID, null))) {
            return false;
        }
        prefs.edit().putString(FID, fid).apply();
        return true;
    }

    /** FCM dropped this id (onUnregistered): forget it unless a newer one replaced it. */
    static synchronized boolean clearFid(Context context, String fid) {
        SharedPreferences prefs = prefs(context);
        String stored = prefs.getString(FID, null);
        if (stored == null || (fid != null && !fid.equals(stored))) {
            return false;
        }
        prefs.edit().remove(FID).apply();
        return true;
    }

    /** True the first time a ring id arrives: FCM may deliver a message twice (SPEC-132). */
    static synchronized boolean firstRing(Context context, String ringId, long nowMs) {
        SharedPreferences prefs = prefs(context);
        List<String> next = PushLinks.addRing(rung(prefs), ringId, nowMs, RUNG_KEPT);
        if (next == null) {
            return false;
        }
        prefs.edit().putString(RUNG, TextUtils.join(",", next)).apply();
        return true;
    }

    /** True once for a ring this phone received in the last 5 minutes (SPEC-134). */
    static synchronized boolean answerRing(Context context, String ringId, long nowMs) {
        SharedPreferences prefs = prefs(context);
        if (!PushLinks.mayAnswer(rung(prefs), prefs.getString(ANSWERED, null), ringId, nowMs)) {
            return false;
        }
        prefs.edit().putString(ANSWERED, ringId).apply();
        return true;
    }

    private static List<String> rung(SharedPreferences prefs) {
        String stored = prefs.getString(RUNG, "");
        List<String> rung = new ArrayList<>();
        if (!stored.isEmpty()) {
            rung.addAll(Arrays.asList(stored.split(",")));
        }
        return rung;
    }

    /** This app's version name (x.y.z), as build.gradle sets it. */
    static String appVersion(Context context) {
        try {
            String name = context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName;
            return name != null ? name : "0.0.0";
        } catch (PackageManager.NameNotFoundException e) {
            return "0.0.0";
        }
    }

    /** "granted" when the app may show notifications at all, else "denied". */
    static String notifications(Context context) {
        return NotificationManagerCompat.from(context).areNotificationsEnabled() ? "granted" : "denied";
    }

    /** "enabled" when notifications are on and the '마롱이 전화' channel is not turned off. */
    static String ringChannel(Context context) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return "disabled";
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            NotificationChannel channel = manager == null ? null : manager.getNotificationChannel(Channels.RING);
            if (channel != null && channel.getImportance() == NotificationManager.IMPORTANCE_NONE) {
                return "disabled";
            }
        }
        return "enabled";
    }

    /** Android 14+ asks the user for full-screen rings; older versions always allow them. */
    static String fullScreen(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            return manager != null && manager.canUseFullScreenIntent() ? "granted" : "denied";
        }
        return "granted";
    }
}
