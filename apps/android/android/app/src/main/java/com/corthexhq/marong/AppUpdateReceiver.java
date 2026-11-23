package com.corthexhq.marong;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInstaller;
import android.os.Build;
import android.util.Log;

import androidx.core.app.NotificationCompat;

/** Install results and cleanup after Android replaces the package (SPEC-296~298). */
public final class AppUpdateReceiver extends BroadcastReceiver {
    static final String RESULT = "com.corthexhq.marong.APP_UPDATE_RESULT";
    static final String RETRY = "com.corthexhq.marong.APP_UPDATE_RETRY";
    static final String VERSION = "versionCode";
    static final String SESSION = "sessionId";
    static final int NOTIFICATION_ID = 301;

    @Override
    public void onReceive(Context context, Intent intent) {
        if (RETRY.equals(intent.getAction())) {
            PendingResult pending = goAsync();
            AppUpdateJob.backupAlarmFired(context.getApplicationContext(), pending::finish);
            return;
        }
        SharedPreferences prefs = AppUpdateJob.preferences(context);
        synchronized (AppUpdateJob.STATE_LOCK) {
            if (Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction())) {
                AppUpdateJob.clearManualConfirmation(-1);
                AppUpdateJob.cancelBackupAlarm(context);
                Channels.ensure(context);
                AppUpdateJob.rearm(context);
                AppUpdateJob.clean(context, -1);
                long installed = AppUpdateJob.installed(context);
                AppUpdateJob.clearOlderFailures(prefs, installed);
                prefs.edit().remove("release").remove("notified").apply();
                cancelNotification(context);
                if (installed <= AppUpdate.MAX_VERSION) {
                    AppUpdateReport.record(context, (int) installed, AppUpdateReport.INSTALLED, 0);
                }
                return;
            }
            if (!RESULT.equals(intent.getAction())) return;
            AppUpdateJob.Candidate candidate = AppUpdateJob.candidate(prefs);
            int code = intent.getIntExtra(VERSION, -1);
            if (candidate == null || candidate.release.code != code
                    || candidate.session != intent.getIntExtra(SESSION, -2)) return;
            int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            switch (AppUpdate.result(status)) {
                case SUCCESS:
                    AppUpdateJob.clearManualConfirmation(candidate.session);
                    AppUpdateJob.clean(context, -1);
                    AppUpdateJob.clearOlderFailures(prefs, code);
                    prefs.edit().remove("release").remove("notified").apply();
                    cancelNotification(context);
                    Log.i(AppUpdateJob.TAG, "update_install success code=" + code);
                    break;
                case CONFIRM:
                    AppUpdateJob.save(prefs, new AppUpdateJob.Candidate(candidate.release, candidate.session, true,
                        AppUpdateJob.installPermissionMissing(context)));
                    AppUpdateReport.record(context, code, AppUpdateReport.NEEDS_CONFIRM, 0);
                    PushEvents.updateChanged();
                    Intent confirmation = confirmation(intent);
                    if (AppUpdateJob.openManualConfirmation(context, candidate.session, confirmation)) {
                        cancelNotification(context);
                        Log.i(AppUpdateJob.TAG, "update_install confirmation_opened code=" + code);
                        break;
                    }
                    if (AppUpdate.notifyVersion(code, prefs.getInt("notified", -1))
                            && notify(context, confirmation, candidate.release)) {
                        prefs.edit().putInt("notified", code).apply();
                    }
                    break;
                case FAILED:
                    AppUpdateJob.clearManualConfirmation(candidate.session);
                    cancelNotification(context);
                    if (candidate.permissionBlocked && status == PackageInstaller.STATUS_FAILURE_ABORTED) {
                        // Settings can abort this session even when the user allows the source.
                        // Keep the verified APK and wait for the permission before creating another session.
                        AppUpdateJob.save(prefs, new AppUpdateJob.Candidate(candidate.release, -1, true, true));
                        if (!AppUpdateJob.installPermissionMissing(context)) AppUpdateJob.check(context);
                        Log.i(AppUpdateJob.TAG, "update_install permission_session_ended code=" + code);
                        PushEvents.updateChanged();
                        break;
                    }
                    // Use the contracted generic failure for a platform-specific status outside 1–7.
                    int reportStatus = status >= 1 && status <= 7 ? status : PackageInstaller.STATUS_FAILURE;
                    AppUpdateJob.fail(context, prefs, code, reportStatus);
                    Log.i(AppUpdateJob.TAG, "update_install fail=" + status + " code=" + code);
                    break;
            }
        }
    }

    @SuppressWarnings("deprecation")
    private static Intent confirmation(Intent result) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return result.getParcelableExtra(Intent.EXTRA_INTENT, Intent.class);
        }
        return result.getParcelableExtra(Intent.EXTRA_INTENT);
    }

    private static boolean notify(Context context, Intent confirmation, AppUpdate.Release release) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        Channels.ensure(context);
        if (confirmation == null || manager == null || !manager.areNotificationsEnabled()) {
            Log.i(AppUpdateJob.TAG, "update_install confirmation_hidden code=" + release.code);
            return false;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = manager.getNotificationChannel(Channels.UPDATE);
            if (channel == null || channel.getImportance() == NotificationManager.IMPORTANCE_NONE) return false;
        }
        PendingIntent open = PendingIntent.getActivity(context, release.code, confirmation,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder publicNotice = new NotificationCompat.Builder(context, Channels.UPDATE)
            .setSmallIcon(R.drawable.ic_stat_marong)
            .setContentTitle(context.getString(R.string.update_notification_public));
        NotificationCompat.Builder notice = new NotificationCompat.Builder(context, Channels.UPDATE)
            .setSmallIcon(R.drawable.ic_stat_marong)
            .setContentTitle(context.getString(R.string.update_notification_title))
            .setContentText(context.getString(R.string.update_notification_body, release.name))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicNotice.build())
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(open)
            .setAutoCancel(true);
        try {
            manager.notify(NOTIFICATION_ID, notice.build());
            Log.i(AppUpdateJob.TAG, "update_install confirmation code=" + release.code);
            return true;
        } catch (SecurityException error) {
            Log.i(AppUpdateJob.TAG, "update_install confirmation_hidden code=" + release.code);
            return false;
        }
    }

    static void cancelNotification(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager != null) manager.cancel(NOTIFICATION_ID);
    }
}
