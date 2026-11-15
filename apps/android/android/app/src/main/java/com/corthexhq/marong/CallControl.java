package com.corthexhq.marong;

import java.lang.ref.WeakReference;

/** Lets the call notification reach the page that is open in the app (SPEC-104). */
final class CallControl {

    private static WeakReference<MarongCallPlugin> current = new WeakReference<>(null);

    private CallControl() {}

    static synchronized void attach(MarongCallPlugin plugin) {
        current = new WeakReference<>(plugin);
    }

    static synchronized void detach(MarongCallPlugin plugin) {
        if (current.get() == plugin) {
            current = new WeakReference<>(null);
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
}
