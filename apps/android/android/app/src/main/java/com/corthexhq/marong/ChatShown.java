package com.corthexhq.marong;

import java.util.Map;
import java.util.WeakHashMap;

/**
 * Which app windows show the chat page right now (docs/app-chat.md SPEC-147). With the chat in a
 * window of its own (D20), the call window's page saying "no chat here" must not undo the chat
 * window's "the chat is on screen".
 *
 * <p>Plain Java on purpose, so it runs in JVM unit tests without a device.
 *
 * @param <W> a window's handle, held weakly: a window that is gone drops out by itself
 */
final class ChatShown<W> {

    private final Map<W, Boolean> shown = new WeakHashMap<>();

    /** Records one window's state. True when the app-wide answer of {@link #any()} changed. */
    synchronized boolean set(W window, boolean visible) {
        boolean before = !shown.isEmpty();
        if (visible) {
            shown.put(window, Boolean.TRUE);
        } else {
            shown.remove(window);
        }
        return before != !shown.isEmpty();
    }

    /** True while at least one window shows the chat. */
    synchronized boolean any() {
        return !shown.isEmpty();
    }
}
