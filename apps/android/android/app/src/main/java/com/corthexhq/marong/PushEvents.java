package com.corthexhq.marong;

import android.os.Handler;
import android.os.Looper;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.function.Consumer;

/**
 * Lets the FCM service reach the pages that are open in the app (docs/app-chat.md SPEC-121,
 * SPEC-123 and SPEC-147): a new Firebase installation id, and whether the chat is on screen right
 * now. From 0.2.1 the app has two windows (D20), each with its own MarongPush.
 */
final class PushEvents {

    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final Set<MarongPushPlugin> ATTACHED = Collections.newSetFromMap(new WeakHashMap<>());
    private static final ChatShown<MarongPushPlugin> CHAT = new ChatShown<>();

    private PushEvents() {}

    static synchronized void attach(MarongPushPlugin plugin) {
        ATTACHED.add(plugin);
    }

    static synchronized void detach(MarongPushPlugin plugin) {
        ATTACHED.remove(plugin);
        CHAT.set(plugin, false);
    }

    /** FCM registered or dropped this installation: the page in every open window reports again. */
    static void registered() {
        forEachWindow(MarongPushPlugin::notifyRegistered);
    }

    static void updateChanged() {
        forEachWindow(MarongPushPlugin::notifyUpdateChanged);
    }

    private static void forEachWindow(Consumer<MarongPushPlugin> event) {
        MAIN.post(() -> {
            List<MarongPushPlugin> plugins;
            synchronized (PushEvents.class) {
                plugins = new ArrayList<>(ATTACHED);
            }
            plugins.forEach(event);
        });
    }

    /** True while a window shows the chat page; a message then shows there, not as a notification. */
    static boolean chatVisible() {
        return CHAT.any();
    }

    /** One window's page shows the chat (true) or not (false). True when {@link #chatVisible()} changed. */
    static boolean setChatVisible(MarongPushPlugin window, boolean visible) {
        return CHAT.set(window, visible);
    }
}
