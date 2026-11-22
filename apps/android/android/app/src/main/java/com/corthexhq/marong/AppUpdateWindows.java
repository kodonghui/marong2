package com.corthexhq.marong;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.view.View;
import android.view.WindowManager;

import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Observes the app's windows, including activities hosted in a different task. */
final class AppUpdateWindows {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final Map<Activity, Boolean> ACTIVITIES = new WeakHashMap<>();

    private AppUpdateWindows() {}

    static void track(Activity activity) {
        ACTIVITIES.put(activity, false);
    }

    @SuppressWarnings("deprecation")
    static void showWhenLocked(Activity activity) {
        ACTIVITIES.put(activity, true);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            activity.setShowWhenLocked(true);
        } else {
            activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED);
        }
    }

    static boolean visible(Context context) {
        if (Looper.myLooper() == Looper.getMainLooper()) return visibleOnMain(context);

        FutureTask<Boolean> check = new FutureTask<>(() -> visibleOnMain(context));
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

    @SuppressWarnings("deprecation")
    private static boolean visibleOnMain(Context context) {
        if (ACTIVITIES.isEmpty()) return false;
        PowerManager power = context.getSystemService(PowerManager.class);
        if (power != null && !power.isInteractive()) return false;
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        boolean locked = keyguard != null && keyguard.isKeyguardLocked();
        for (Map.Entry<Activity, Boolean> entry : ACTIVITIES.entrySet()) {
            Activity activity = entry.getKey();
            if (activity.isDestroyed()) continue;
            View decor = activity.getWindow().peekDecorView();
            if (decor == null || !decor.isAttachedToWindow()
                    || decor.getWindowVisibility() != View.VISIBLE || !decor.isShown()) continue;
            if (!locked || decor.hasWindowFocus() || entry.getValue()
                    || (activity.getWindow().getAttributes().flags & WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED) != 0) {
                return true;
            }
        }
        return false;
    }
}
