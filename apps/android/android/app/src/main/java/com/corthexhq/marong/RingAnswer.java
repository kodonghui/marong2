package com.corthexhq.marong;

/** An accepted native ring calls the page hook while older pages use the ring URL. */
final class RingAnswer {
    static final String PREPARE_JS =
        "(function(){try{var c=window.__marongCall;if(c&&typeof c.prepareCall==='function')c.prepareCall();}catch(e){}})()";

    private RingAnswer() {}

    static String answerScript(String ringId, long answeredAt) {
        if (!PushLinks.isRingId(ringId)) {
            throw new IllegalArgumentException("Invalid ring");
        }
        return "(function(){try{var c=window.__marongCall;return !!(c&&typeof c.answerRing==='function'&&c.answerRing(\""
            + ringId + "\"," + answeredAt + ")===true);}catch(e){return false;}})()";
    }

    static String coldScript(String ringId, long answeredAt) {
        if (!PushLinks.isRingId(ringId)) {
            return "";
        }
        return "if(location.pathname==='/'&&location.search==='?ring=" + ringId + "')"
            + "window.__marongColdAnswerAt=" + answeredAt + ";\n";
    }
}
