package com.corthexhq.marong;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.app.job.JobScheduler;
import android.util.Log;

import com.google.firebase.messaging.RemoteMessage;

import java.util.concurrent.atomic.AtomicBoolean;

/** Copy only to a fixture APK, with the receiver restricted to shell via android.permission.DUMP. */
public final class UpdateFixtureReceiver extends BroadcastReceiver {
    private static final AtomicBoolean PAUSED = new AtomicBoolean();

    @Override
    public void onReceive(Context context, Intent intent) {
        String mode = intent.getStringExtra("mode");
        if ("call-on".equals(mode)) {
            if (!CallService.show(context, "Fixture")) setResultCode(1);
        } else if ("call-off".equals(mode)) {
            CallService.hide(context);
        } else if ("ring".equals(mode)) {
            Ring.receive(context, "00000000-0000-4000-8000-000000000112",
                System.currentTimeMillis(), "promise", null, "Fixture");
        } else if ("ring-off".equals(mode)) {
            Ring.cancel(context);
        } else if ("prepare-push".equals(mode)) {
            AppUpdateJob.preferences(context).edit()
                .putLong("checkedAt", System.currentTimeMillis() - 3_600_000L)
                .remove("forcedAt").commit();
            context.getSystemService(JobScheduler.class).cancel(AppUpdateJob.CHECK_JOB);
        } else if ("update-push".equals(mode)) {
            // Substitute a RemoteMessage at the Firebase callback boundary.
            new MockMessagingService(context).onMessageReceived(new RemoteMessage.Builder("fixture")
                .addData("kind", "app_update").addData("v", intent.getStringExtra("version")).build());
        } else if ("report-failure".equals(mode)) {
            AppUpdateReport.record(context, intent.getIntExtra("version", 10), AppUpdateReport.FAILED,
                intent.getIntExtra("status", 101));
        }
    }

    private static final class MockMessagingService extends MarongMessagingService {
        MockMessagingService(Context context) {
            attachBaseContext(context);
        }
    }

    static void pauseBeforeCommit() {
        if (!PAUSED.compareAndSet(false, true)) return;
        Log.i(AppUpdateJob.TAG, "fixture_waiting_to_commit");
        SystemClock.sleep(12_000);
    }
}
