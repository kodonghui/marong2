package com.corthexhq.marong;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;
import android.util.Log;

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
        }
    }

    static void pauseBeforeCommit() {
        if (!PAUSED.compareAndSet(false, true)) return;
        Log.i(AppUpdateJob.TAG, "fixture_waiting_to_commit");
        SystemClock.sleep(12_000);
    }
}
