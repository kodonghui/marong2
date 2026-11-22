package com.corthexhq.marong;

import java.lang.ref.WeakReference;

/**
 * Lets the call notification reach the page that is open in the app (SPEC-104), and tells a ring
 * whether a call is already going on (docs/app-ring.md SPEC-132, SPEC-134).
 */
final class CallControl {

    private static WeakReference<MarongCallPlugin> current = new WeakReference<>(null);
    private static volatile boolean active;

    private CallControl() {}

    static synchronized void attach(MarongCallPlugin plugin) {
        current = new WeakReference<>(plugin);
    }

    static synchronized void detach(MarongCallPlugin plugin) {
        if (current.get() == plugin) {
            current = new WeakReference<>(null);
        }
    }

    /** True while the page in this app holds a live microphone (a call is going on). */
    static boolean isActive() {
        return active;
    }

    static void setActive(boolean value) {
        synchronized (AppUpdateJob.STATE_LOCK) {
            active = value;
        }
    }

    /** Asks the open page to end its call. False when no page is open. */
    static boolean hangUp() {
        MarongCallPlugin plugin;
        synchronized (CallControl.class) {
            plugin = current.get();
        }
        if (plugin == null) {
            return false;
        }
        plugin.hangUpFromNotification();
        return true;
    }

    static synchronized void prepareForRing() {
        MarongCallPlugin plugin = current.get();
        if (!active && plugin != null) {
            plugin.prepareForRing();
        }
    }
}
