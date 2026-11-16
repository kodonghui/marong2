package com.corthexhq.marong;

import java.net.URI;

/**
 * Which of the app's two windows a page belongs in (D20, docs/app-chat.md SPEC-143 and SPEC-144):
 * the call window (MainActivity) keeps the call page, the chat window (ChatActivity) the chat. A
 * page that belongs in the other window never opens here: leaving the call page would end a call.
 *
 * <p>Plain Java on purpose, so the rules run in JVM unit tests without a device.
 */
final class AppWindows {

    /** The chat window always starts here; it never takes over the address that was tapped. */
    static final String CHAT_PATH = "/chat/";

    /** What a window does instead of opening a page. */
    enum Move {
        /** Nothing special: the usual rules for this address (SPEC-102). */
        NONE,
        /** The call window opens the chat window above it and keeps its own page. */
        OPEN_CHAT,
        /** The chat window closes, so the call window under it shows again as it was. */
        BACK_TO_CALL,
    }

    private AppWindows() {}

    /** What a window should do when its whole page is about to change to url. */
    static Move move(String url, String appUrl, boolean chatWindow) {
        if (!AppUrls.isAppPage(url, appUrl)) {
            return Move.NONE;
        }
        String path = rawPath(url);
        if (path == null) {
            return Move.NONE;
        }
        if (!chatWindow && isChatPath(path)) {
            return Move.OPEN_CHAT;
        }
        if (chatWindow && isCallPath(path)) {
            return Move.BACK_TO_CALL;
        }
        return Move.NONE;
    }

    /** "/chat" or anything under "/chat/", exactly as written, like the tunnel's rule ^/chat(/|$). */
    static boolean isChatPath(String rawPath) {
        return "/chat".equals(rawPath) || rawPath.startsWith("/chat/");
    }

    /** The call page is the site's root, whatever follows "?" or "#". */
    static boolean isCallPath(String rawPath) {
        return rawPath.isEmpty() || "/".equals(rawPath);
    }

    private static String rawPath(String url) {
        try {
            String path = new URI(url).getRawPath();
            return path == null ? "" : path;
        } catch (Exception e) {
            return null;
        }
    }
}
