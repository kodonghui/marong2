package com.corthexhq.marong;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

/** TC-150 (docs/app-chat.md): which pages open the other app window instead (D20, SPEC-144). */
public class AppWindowsTest {

    private static final String APP = "https://marong.corthex-hq.com";
    private static final boolean CALL = false;
    private static final boolean CHAT = true;

    private static AppWindows.Move move(String url, boolean chatWindow) {
        return AppWindows.move(url, APP, chatWindow);
    }

    @Test
    public void theChatOpensTheChatWindowFromTheCallWindow() {
        assertEquals(AppWindows.Move.OPEN_CHAT, move("https://marong.corthex-hq.com/chat/", CALL));
        assertEquals(AppWindows.Move.OPEN_CHAT, move("https://marong.corthex-hq.com/chat", CALL));
        assertEquals(AppWindows.Move.OPEN_CHAT, move("https://marong.corthex-hq.com/chat/?a=1", CALL));
        assertEquals(AppWindows.Move.OPEN_CHAT, move("https://marong.corthex-hq.com/chat/#b", CALL));
        assertEquals(AppWindows.Move.OPEN_CHAT, move("https://MARONG.corthex-hq.com:443/chat/", CALL));
    }

    @Test
    public void lookalikeChatAddressesStayWithTheUsualRules() {
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/chatty", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/CHAT/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/%63hat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/x/chat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://other.example.org/chat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com:8443/chat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("http://marong.corthex-hq.com/chat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://user@marong.corthex-hq.com/chat/", CALL));
        assertEquals(AppWindows.Move.NONE, move("not a url", CALL));
        assertEquals(AppWindows.Move.NONE, move(null, CALL));
    }

    @Test
    public void theCallWindowKeepsItsOwnPages() {
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/?ring=0f8fad5b-d9cb-469f-a165-70867728950e", CALL));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/cdn-cgi/access/authorized", CALL));
    }

    @Test
    public void theCallPageClosesTheChatWindow() {
        assertEquals(AppWindows.Move.BACK_TO_CALL, move("https://marong.corthex-hq.com/", CHAT));
        assertEquals(AppWindows.Move.BACK_TO_CALL, move("https://marong.corthex-hq.com", CHAT));
        assertEquals(AppWindows.Move.BACK_TO_CALL, move("https://marong.corthex-hq.com/?ring=0f8fad5b-d9cb-469f-a165-70867728950e", CHAT));
        assertEquals(AppWindows.Move.BACK_TO_CALL, move("https://marong.corthex-hq.com/#top", CHAT));
    }

    @Test
    public void theChatWindowKeepsTheChatSignInAndOtherPages() {
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/chat/", CHAT));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/cdn-cgi/access/authorized?token=x", CHAT));
        assertEquals(AppWindows.Move.NONE, move("https://marong.corthex-hq.com/google/healthz", CHAT));
        assertEquals(AppWindows.Move.NONE, move("https://team.cloudflareaccess.com/cdn-cgi/access/login/marong.corthex-hq.com", CHAT));
        assertEquals(AppWindows.Move.NONE, move("https://other.example.org/", CHAT));
        assertEquals(AppWindows.Move.NONE, move("https://localhost/error.html?page=chat", CHAT));
    }

    @Test
    public void theChatWindowStartsAtTheChat() {
        assertEquals("/chat/", AppWindows.CHAT_PATH);
        assertEquals(AppWindows.Move.NONE, move(APP + AppWindows.CHAT_PATH, CHAT));
        assertEquals(AppWindows.Move.OPEN_CHAT, move(APP + AppWindows.CHAT_PATH, CALL));
    }
}
