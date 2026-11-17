package com.corthexhq.marong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

/** TC-134 (docs/app-chat.md) and TC-146 (docs/app-ring.md): what a notification or a ring may open. */
public class PushLinksTest {

    private static final String APP = "https://marong.corthex-hq.com";
    private static final String RING = "0f8fad5b-d9cb-469f-a165-70867728950e";
    private static final String OTHER = "7c9e6679-7425-40de-944b-e07fc1f90ae7";
    private static final long NOW = 1_763_200_000_000L;

    @Test
    public void notificationsOpenOnlyTheChatOrTheCallPage() {
        assertEquals("/chat/", PushLinks.openPath("/chat/"));
        assertEquals("/", PushLinks.openPath("/"));
        for (String other : Arrays.asList(
            "/chat",
            "/chat/x",
            "/CHAT/",
            " /chat/",
            "/chat/?x=1",
            "https://example.test/chat/",
            "//example.test/",
            "javascript:alert(1)",
            "",
            null
        )) {
            assertNull(String.valueOf(other), PushLinks.openPath(other));
        }
        assertEquals(APP + "/chat/", PushLinks.pageUrl(APP, "/chat/"));
        assertEquals(APP + "/", PushLinks.pageUrl(APP + "/", "/"));
    }

    @Test
    public void ringIdsAreLowercaseUuidsOnly() {
        assertTrue(PushLinks.isRingId(RING));
        assertFalse(PushLinks.isRingId(RING.toUpperCase()));
        assertFalse(PushLinks.isRingId("{" + RING + "}"));
        assertFalse(PushLinks.isRingId(RING + "\n"));
        assertFalse(PushLinks.isRingId(RING.substring(1)));
        assertFalse(PushLinks.isRingId("../" + RING));
        assertFalse(PushLinks.isRingId(""));
        assertFalse(PushLinks.isRingId(null));
    }

    @Test
    public void answeringOpensTheCallPageWithTheRingAndNothingElse() {
        assertEquals(APP + "/?ring=" + RING, PushLinks.ringUrl(APP, RING));
        assertEquals(APP + "/?ring=" + RING, PushLinks.ringUrl(APP + "/", RING));
        assertThrows(IllegalArgumentException.class, () -> PushLinks.ringUrl(APP, RING + "&x=1"));
        assertThrows(IllegalArgumentException.class, () -> PushLinks.ringUrl(APP, null));
    }

    @Test
    public void aHelloRingShowsItsLineOnlyWithinTheRules() {
        assertTrue(PushLinks.isHello("hello"));
        assertFalse(PushLinks.isHello("promise"));
        assertFalse("an unknown reason is a promise ring", PushLinks.isHello("HELLO"));
        assertFalse(PushLinks.isHello(null));
        assertEquals("나 털모자 샀다!", PushLinks.ringLine("hello", "  나 털모자 샀다!  "));
        assertEquals("가".repeat(30), PushLinks.ringLine("hello", "가".repeat(30)));
        assertEquals("emoji count as one", "눈사람 ⛄".repeat(5), PushLinks.ringLine("hello", "눈사람 ⛄".repeat(5)));
        assertNull("31 characters", PushLinks.ringLine("hello", "가".repeat(31)));
        assertNull(PushLinks.ringLine("hello", "두 줄\n이에요"));
        assertNull(PushLinks.ringLine("hello", "   "));
        assertNull(PushLinks.ringLine("hello", null));
        assertNull("a promise ring has no line", PushLinks.ringLine("promise", "나 털모자 샀다!"));
        assertNull(PushLinks.ringLine(null, "나 털모자 샀다!"));
    }

    @Test
    public void theCallNotificationSaysWhichCallItIs() {
        String promise = "약속한 전화예요";
        String hello = "마롱이가 먼저 걸었어요";
        assertEquals("마롱이가 먼저 걸었어요 · 나 털모자 샀다!", PushLinks.ringText("hello", "나 털모자 샀다!", promise, hello));
        assertEquals(hello, PushLinks.ringText("hello", null, promise, hello));
        assertEquals(hello, PushLinks.ringText("hello", "가".repeat(31), promise, hello));
        assertEquals(promise, PushLinks.ringText("promise", "나 털모자 샀다!", promise, hello));
        assertEquals(promise, PushLinks.ringText(null, null, promise, hello));
        assertEquals(promise, PushLinks.ringText("later", null, promise, hello));
    }

    @Test
    public void aRingOlderThanFiveMinutesIsDropped() {
        assertTrue(PushLinks.isFresh(NOW, NOW));
        assertTrue(PushLinks.isFresh(NOW - 5 * 60_000L, NOW));
        assertFalse(PushLinks.isFresh(NOW - 5 * 60_000L - 1, NOW));
        assertTrue("the phone's clock is behind", PushLinks.isFresh(NOW + 60_000L, NOW));
        assertFalse("no send time", PushLinks.isFresh(0L, NOW));
    }

    @Test
    public void aRingSoundsOnceAndTheListStaysShort() {
        List<String> rung = PushLinks.addRing(Collections.<String>emptyList(), RING, NOW, 20);
        assertEquals(Collections.singletonList(RING + "@" + NOW), rung);
        assertNull("FCM delivered it twice", PushLinks.addRing(rung, RING, NOW + 1_000L, 20));
        List<String> many = new ArrayList<>();
        for (int i = 0; i < 25; i++) {
            many.add(String.format("00000000-0000-4000-8000-%012d@%d", i, NOW));
        }
        List<String> kept = PushLinks.addRing(many, OTHER, NOW, 20);
        assertEquals(20, kept.size());
        assertEquals(OTHER + "@" + NOW, kept.get(0));
        assertEquals(NOW, PushLinks.receivedAt(kept, OTHER));
        assertEquals(-1L, PushLinks.receivedAt(kept, RING));
        assertEquals(0L, PushLinks.receivedAt(Collections.singletonList(RING + "@soon"), RING));
    }

    @Test
    public void onlyARingThisPhoneReceivedInTheLastFiveMinutesIsAnsweredAndOnlyOnce() {
        List<String> rung = Arrays.asList(RING + "@" + (NOW - 60_000L), OTHER + "@" + (NOW - 6 * 60_000L));
        assertTrue(PushLinks.mayAnswer(rung, null, RING, NOW));
        assertFalse("already answered", PushLinks.mayAnswer(rung, RING, RING, NOW));
        assertFalse("too old", PushLinks.mayAnswer(rung, null, OTHER, NOW));
        assertFalse("never received: another app made it up", PushLinks.mayAnswer(rung, null, "1b4e28ba-2fa1-41d2-883f-0016d3cca427", NOW));
        assertFalse(PushLinks.mayAnswer(rung, null, RING.toUpperCase(), NOW));
        assertFalse(PushLinks.mayAnswer(Collections.singletonList(RING + "@soon"), null, RING, NOW));
        assertFalse(PushLinks.mayAnswer(rung, null, null, NOW));
    }
}
