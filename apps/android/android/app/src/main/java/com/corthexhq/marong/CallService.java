package com.corthexhq.marong;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;
import com.getcapacitor.Logger;

/**
 * Keeps the microphone and the call alive while the screen is off or another app is open
 * (REQ-103, SPEC-103). Runs only while the call page holds a live microphone track.
 */
public class CallService extends Service {

    static final String ACTION_SHOW = "com.corthexhq.marong.action.SHOW_CALL";
    static final String ACTION_HANG_UP = "com.corthexhq.marong.action.HANG_UP";
    static final String CHANNEL_ID = "call";
    static final int NOTIFICATION_ID = 101;

    /**
     * Starts the service while the app is in the foreground. Uses startService, not
     * startForegroundService, so a failure can never become a "did not call startForeground"
     * crash. Returns false when Android refuses (for example from the background).
     */
    static boolean show(Context context) {
        try {
            context.startService(new Intent(context, CallService.class).setAction(ACTION_SHOW));
            return true;
        } catch (RuntimeException e) {
            Logger.warn("MarongCall", "Call service not started: " + e.getClass().getSimpleName());
            return false;
        }
    }

    static void hide(Context context) {
        context.stopService(new Intent(context, CallService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_HANG_UP.equals(action)) {
            // The page ends the call; CallControl stops this service when it reports the end.
            if (!CallControl.hangUp()) {
                stopSelf();
            }
            return START_NOT_STICKY;
        }
        try {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                buildNotification(),
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.R ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE : 0
            );
        } catch (RuntimeException e) {
            // Missing microphone permission or a background start: the call still works while visible.
            Logger.warn("MarongCall", "Foreground not allowed: " + e.getClass().getSimpleName());
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        // Swiping the app away closes the page and its call, so nothing is left to keep alive.
        stopSelf();
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private Notification buildNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager != null) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.call_channel_name),
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription(getString(R.string.call_channel_description));
            channel.setShowBadge(false);
            manager.createNotificationChannel(channel);
        }

        int immutable = PendingIntent.FLAG_IMMUTABLE;
        Intent open = new Intent(this, MainActivity.class)
            .setAction(Intent.ACTION_MAIN)
            .addCategory(Intent.CATEGORY_LAUNCHER)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent openCall = PendingIntent.getActivity(this, 0, open, immutable | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent hangUp = PendingIntent.getService(
            this,
            1,
            new Intent(this, CallService.class).setAction(ACTION_HANG_UP),
            immutable | PendingIntent.FLAG_UPDATE_CURRENT
        );

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_call)
            .setContentTitle(getString(R.string.call_notification_title))
            .setContentText(getString(R.string.call_notification_text))
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setContentIntent(openCall)
            .addAction(R.drawable.ic_stat_hang_up, getString(R.string.call_notification_hang_up), hangUp)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build();
    }
}
