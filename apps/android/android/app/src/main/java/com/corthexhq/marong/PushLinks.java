package com.corthexhq.marong;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Rules for what a notification or a ring may open (docs/app-chat.md SPEC-122, docs/app-ring.md
 * SPEC-132 and SPEC-134).
 *
 * <p>Plain Java on purpose, so the rules run in JVM unit tests without a device.
 */
final class PushLinks {

    /** A ring older than this when it arrives is dropped: the friend's answer window is 5 minutes. */
    static final long RING_MAX_AGE_MS = 5 * 60_000L;

    private static final Pattern RING_ID = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");

    private PushLinks() {}

    /**
     * The page a notification's "open" value may show: exactly "/chat/" (the in-app chat) or "/"
     * (the call page, for a missed call). Anything else opens nothing.
     */
    static String openPath(String open) {
        if ("/chat/".equals(open) || "/".equals(open)) {
            return open;
        }
        return null;
    }

    /** A ring id as the server sends it: a lowercase UUID and nothing else. */
    static boolean isRingId(String ringId) {
        return ringId != null && RING_ID.matcher(ringId).matches();
    }

    /** The call page address that answers a ring. */
    static String ringUrl(String appUrl, String ringId) {
        if (!isRingId(ringId)) {
            throw new IllegalArgumentException("Not a ring id");
        }
        return trimSlash(appUrl) + "/?ring=" + ringId;
    }

    /** The app page address for a notification's open path. */
    static String pageUrl(String appUrl, String path) {
        return trimSlash(appUrl) + path;
    }

    /**
     * A ring may still sound: FCM gave its send time and it is under 5 minutes old. A send time in
     * the future (the phone's clock is behind) counts as fresh; no send time counts as old.
     */
    static boolean isFresh(long sentTimeMs, long nowMs) {
        return sentTimeMs > 0 && nowMs - sentTimeMs <= RING_MAX_AGE_MS;
    }

    /**
     * The rings this phone received, newest first, as "id@receivedAtMs" (SPEC-132): the list with
     * this ring added and at most {@code keep} entries, or null when the ring is already in it
     * (FCM may deliver a message twice).
     */
    static List<String> addRing(List<String> rung, String ringId, long nowMs, int keep) {
        if (receivedAt(rung, ringId) != -1L) {
            return null;
        }
        List<String> next = new ArrayList<>();
        next.add(ringId + "@" + nowMs);
        for (String entry : rung) {
            if (next.size() >= keep) {
                break;
            }
            next.add(entry);
        }
        return next;
    }

    /** When this phone received the ring, or -1 when it never did. */
    static long receivedAt(List<String> rung, String ringId) {
        if (ringId == null) {
            return -1L;
        }
        for (String entry : rung) {
            int at = entry.indexOf('@');
            if (at > 0 && entry.substring(0, at).equals(ringId)) {
                try {
                    return Long.parseLong(entry.substring(at + 1));
                } catch (NumberFormatException e) {
                    return 0L;
                }
            }
        }
        return -1L;
    }

    /**
     * 받기 may open the call page for this ring: this phone received it in the last 5 minutes and
     * has not answered it yet (SPEC-134). Another app can send the same intent to the app, but it
     * cannot know a ring id that only came through FCM.
     */
    static boolean mayAnswer(List<String> rung, String answered, String ringId, long nowMs) {
        if (!isRingId(ringId) || ringId.equals(answered)) {
            return false;
        }
        long received = receivedAt(rung, ringId);
        return received > 0 && nowMs - received <= RING_MAX_AGE_MS;
    }

    private static String trimSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
