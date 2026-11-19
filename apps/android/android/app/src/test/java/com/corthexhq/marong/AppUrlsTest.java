package com.corthexhq.marong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** TC-108, TC-109: which pages stay inside the app window. */
public class AppUrlsTest {

    private static final String APP = "https://marong.corthex-hq.com";

    @Test
    public void appPagesMatchOnlyTheCallSiteOrigin() {
        assertTrue(AppUrls.isAppPage("https://marong.corthex-hq.com/", APP));
        assertTrue(AppUrls.isAppPage("https://MARONG.corthex-hq.com/status?x=1", APP));
        assertTrue(AppUrls.isAppPage("https://marong.corthex-hq.com:443/live", APP));
        assertFalse(AppUrls.isAppPage("http://marong.corthex-hq.com/", APP));
        assertFalse(AppUrls.isAppPage("https://marong.corthex-hq.com:8443/", APP));
        assertFalse(AppUrls.isAppPage("https://evil.corthex-hq.com/", APP));
        assertFalse(AppUrls.isAppPage("https://marong.corthex-hq.com.example.org/", APP));
        assertFalse(AppUrls.isAppPage("https://marong.corthex-hq.com@example.org/", APP));
        assertFalse(AppUrls.isAppPage("https://localhost/error.html", APP));
        assertFalse(AppUrls.isAppPage(null, APP));
    }

    @Test
    public void originDropsPathAndKeepsPort() {
        assertEquals("https://marong.corthex-hq.com", AppUrls.origin("https://Marong.corthex-hq.com/live?x=1"));
        assertEquals("https://marong.corthex-hq.com:8443", AppUrls.origin("https://marong.corthex-hq.com:8443/"));
    }

    @Test
    public void onlyServerErrorsShowTheOfflinePage() {
        assertTrue(AppUrls.isServerOutage(502));
        assertTrue(AppUrls.isServerOutage(530));
        assertFalse(AppUrls.isServerOutage(403));
        assertFalse(AppUrls.isServerOutage(404));
        assertFalse(AppUrls.isServerOutage(200));
    }
}
