package com.corthexhq.marong;

import android.os.Handler;
import android.os.Looper;
import java.lang.ref.WeakReference;

/**
 * Lets the FCM service reach the page that is open in the app (docs/app-chat.md SPEC-121 and
 * SPEC-123): a new Firebase installation id, and whether the chat is on screen right now.
 */
final class PushEvents {

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static WeakReference<MarongPushPlugin> current = new WeakReference<>(null);
    private static volatile boolean chatVisible;

    private PushEvents() {}

    static synchronized void attach(MarongPushPlugin plugin) {
        current = new WeakReference<>(plugin);
    }

    static synchronized void detach(MarongPushPlugin plugin) {
        if (current.get() == plugin) {
            current = new WeakReference<>(null);
        }
    }

    /** FCM registered or dropped this installation: the page reports the device again. */
    static void registered() {
        MAIN.post(() -> {
            MarongPushPlugin plugin;
            synchronized (PushEvents.class) {
                plugin = current.get();
            }
            if (plugin != null) {
                plugin.notifyRegistered();
            }
        });
    }

    /** True while the chat page is on screen; a message then shows there, not as a notification. */
    static boolean chatVisible() {
        return chatVisible;
    }

    static void setChatVisible(boolean visible) {
        chatVisible = visible;
    }
}
