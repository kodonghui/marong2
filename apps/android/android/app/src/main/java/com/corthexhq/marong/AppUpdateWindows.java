package com.corthexhq.marong;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.view.View;

import java.util.Collections;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Observes the app's windows, including activities hosted in a different task. */
final class AppUpdateWindows {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final Set<Activity> ACTIVITIES = Collections.newSetFromMap(new WeakHashMap<>());

    private AppUpdateWindows() {}

    static void track(Activity activity) {
        ACTIVITIES.add(activity);
    }

    static boolean visible(Context context) {
        PowerManager power = context.getSystemService(PowerManager.class);
        if (power != null && !power.isInteractive()) return false;
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        boolean locked = keyguard != null && keyguard.isKeyguardLocked();
        if (Looper.myLooper() == Looper.getMainLooper()) return visibleOnMain(locked);

        FutureTask<Boolean> check = new FutureTask<>(() -> visibleOnMain(locked));
        if (!MAIN.post(check)) return true;
        try {
            return check.get(1, TimeUnit.SECONDS);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return true;
        } catch (ExecutionException | TimeoutException error) {
            return true;
        } finally {
            check.cancel(false);
        }
    }

    private static boolean visibleOnMain(boolean locked) {
        for (Activity activity : ACTIVITIES) {
            if (activity.isDestroyed() || (locked && !(activity instanceof RingActivity))) continue;
            View decor = activity.getWindow().peekDecorView();
            if (decor != null && decor.isAttachedToWindow()
                    && decor.getWindowVisibility() == View.VISIBLE && decor.isShown()) return true;
        }
        return false;
    }
}
