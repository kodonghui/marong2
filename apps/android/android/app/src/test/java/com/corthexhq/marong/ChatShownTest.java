package com.corthexhq.marong;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** TC-154 (docs/app-chat.md): "the chat is on screen" is kept for each app window (SPEC-147). */
public class ChatShownTest {

    @Test
    public void theCallWindowSayingNoChatKeepsTheChatWindowsChat() {
        ChatShown<Object> shown = new ChatShown<>();
        Object callWindow = new Object();
        Object chatWindow = new Object();

        assertFalse(shown.any());
        assertTrue("the app-wide answer changed", shown.set(chatWindow, true));
        assertTrue(shown.any());
        // The call window's page reports "no chat here" when it comes back or hides (0.2.0 lost the chat here).
        assertFalse("the app-wide answer did not change", shown.set(callWindow, false));
        assertTrue(shown.any());
        assertFalse(shown.set(chatWindow, true));
        assertTrue(shown.set(chatWindow, false));
        assertFalse(shown.any());
    }

    @Test
    public void bothWindowsMustLetGoBeforeTheChatIsOffScreen() {
        ChatShown<Object> shown = new ChatShown<>();
        Object first = new Object();
        Object second = new Object();

        assertTrue(shown.set(first, true));
        assertFalse(shown.set(second, true));
        assertFalse(shown.set(first, false));
        assertTrue(shown.any());
        assertTrue(shown.set(second, false));
        assertFalse(shown.any());
    }
}
