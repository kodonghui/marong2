package com.corthexhq.marong;

import org.junit.Test;

import java.util.Map;
import java.util.Set;

import static org.junit.Assert.*;

public final class AppUpdateReportTest {
    @Test public void tc606DeviceBodyIncludesRingAndOnlyFailedHasAStatus() {
        Map<String, Object> body = AppUpdateReport.body(null, "granted", "0.3.2", "enabled", "denied",
            11, AppUpdateReport.FAILED, 115);
        assertEquals(Set.of("fid", "notifications", "appVersion", "ring", "update"), body.keySet());
        assertNull(body.get("fid"));
        assertEquals(Map.of("channel", "enabled", "fullScreen", "denied"), body.get("ring"));
        assertEquals(Map.of("versionCode", 11, "state", "failed", "status", 115), body.get("update"));
        assertEquals(Map.of("versionCode", 11, "state", "installed"), AppUpdateReport.body(
            "fixture", "denied", "0.3.3", "disabled", "denied", 11, AppUpdateReport.INSTALLED, 0).get("update"));
    }

    @Test public void tc606DedupIncludesFailureStatus() {
        assertTrue(AppUpdateReport.same(11, "failed", 101, 11, "failed", 101));
        assertFalse(AppUpdateReport.same(11, "failed", 101, 11, "failed", 102));
        assertFalse(AppUpdateReport.same(11, "failed", 101, 12, "failed", 101));
        assertFalse(AppUpdateReport.same(11, "downloaded", 0, 11, "waiting_quiet", 0));
    }

    @Test public void tc606ResponseAndRetryWindow() {
        for (int code : new int[] {200, 201}) assertEquals(AppUpdateReport.Response.SENT, AppUpdateReport.response(code));
        for (int code : new int[] {302, 399, 401, 403}) assertEquals(AppUpdateReport.Response.SIGN_IN, AppUpdateReport.response(code));
        for (int code : new int[] {400, 409}) assertEquals(AppUpdateReport.Response.DROP, AppUpdateReport.response(code));
        for (int code : new int[] {404, 429, 500}) assertEquals(AppUpdateReport.Response.RETRY, AppUpdateReport.response(code));
        long first = 1_000_000L;
        long retry = first + 900_000L;
        assertEquals(900_000L, AppUpdateReport.retryDelay(retry, first));
        assertEquals(1, AppUpdateReport.retryDelay(retry, retry - 1));
        assertEquals(0, AppUpdateReport.retryDelay(retry, retry));
        assertFalse(AppUpdateReport.expired(first, first + 86_399_999L));
        assertTrue(AppUpdateReport.expired(first, first + 86_400_000L));
        assertFalse(AppUpdateReport.expired(first, first - 1));
    }
}
