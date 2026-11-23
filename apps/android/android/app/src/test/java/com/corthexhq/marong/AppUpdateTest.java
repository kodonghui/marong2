package com.corthexhq.marong;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

import static org.junit.Assert.*;

public final class AppUpdateTest {
    private static final String HASH = "a".repeat(64);
    private static final String PATH = "/chat/app/marong-0.2.3-6.apk";
    private static final String PACKAGE = "com.corthexhq.marong";
    private static final AppUpdate.Release RELEASE = AppUpdate.release(6, "0.2.3", 5120, HASH, PATH);

    @Test public void tc603PushVersionRequiresPositiveAndroidVersionCode() {
        for (String value : new String[] { null, "", "0", "-1", "1.5", " 10", "2100000001", "99999999999999999999" }) {
            assertEquals(0, AppUpdate.pushVersion(value));
        }
        assertEquals(11, AppUpdate.pushVersion("11"));
        assertEquals(2_100_000_000, AppUpdate.pushVersion("2100000000"));
    }

    @Test public void tc603ForcedCheckRequiresNewerVersionAndTenMinutesUnlessClockRolledBack() {
        long forced = 1_000_000;
        assertFalse(AppUpdate.shouldForce(11, 10, forced, forced + 599_000));
        assertTrue(AppUpdate.shouldForce(11, 10, forced, forced + 600_000));
        assertTrue(AppUpdate.shouldForce(11, 10, forced, forced - 1));
        assertTrue(AppUpdate.shouldForce(11, 10, 0, forced));
        assertFalse(AppUpdate.shouldForce(10, 10, 0, forced));
        assertFalse(AppUpdate.shouldForce(9, 10, 0, forced));
    }

    @Test public void tc213SixHourBoundaryAndClockRollback() {
        long now = 10 * AppUpdate.CHECK_INTERVAL_MS;
        assertTrue(AppUpdate.shouldCheck(0, now));
        assertTrue(AppUpdate.shouldCheck(now + 1, now));
        assertFalse(AppUpdate.shouldCheck(now - AppUpdate.CHECK_INTERVAL_MS + 60_000, now));
        assertTrue(AppUpdate.shouldCheck(now - AppUpdate.CHECK_INTERVAL_MS, now));
    }

    @Test public void tc214ReleaseAndSameOriginPath() {
        assertEquals(6, RELEASE.code);
        assertEquals(5120, RELEASE.size);
        for (String path : new String[]{null, "", "/chat/app/", PATH + "?x=1", PATH + "#x",
                "https://other.test" + PATH, "//other.test" + PATH, "/chat/app/../" + PATH,
                "/chat/app/%2f" + PATH, "/chat/app/marong-0.2.2-6.apk", "/chat//app/marong-0.2.3-6.apk"}) {
            assertNull("unsafe path " + path, AppUpdate.release(6, "0.2.3", 5120, HASH, path));
        }
        assertNull(AppUpdate.release("6", "0.2.3", 5120, HASH, PATH));
        assertNull(AppUpdate.release(6.0, "0.2.3", 5120, HASH, PATH));
        assertNull(AppUpdate.release(2100000001L, "0.2.3", 5120, HASH, PATH));
        assertNull(AppUpdate.release(6, null, 5120, HASH, PATH));
        assertNull(AppUpdate.release(6, "0.2.3", null, HASH, PATH));
        assertNull(AppUpdate.release(6, "0.2.3", 0, HASH, PATH));
        assertNull(AppUpdate.release(6, "0.2.3", AppUpdate.APK_MAX_BYTES + 1, HASH, PATH));
        assertNull(AppUpdate.release(6, "0.2.3", 5120, HASH.substring(1), PATH));
    }

    @Test public void tc215OnlySuccessAdvancesCheck() {
        assertEquals(AppUpdate.Check.RELEASE, AppUpdate.check(200));
        assertEquals(AppUpdate.Check.NONE, AppUpdate.check(204));
        for (int status : new int[]{301, 302, 307, 308, 401, 403}) assertEquals(AppUpdate.Check.SIGNED_OUT, AppUpdate.check(status));
        for (int status : new int[]{-1, 404, 500, 503}) assertEquals(AppUpdate.Check.RETRY, AppUpdate.check(status));
    }

    @Test public void tc216FailThreeTimesPerVersion() {
        int count = 0;
        for (int i = 0; i < 3; i++) {
            assertTrue(AppUpdate.eligible(6, 5, count));
            count = AppUpdate.afterFailure(count);
        }
        assertEquals(3, AppUpdate.afterFailure(count));
        assertFalse(AppUpdate.eligible(6, 5, count));
        assertTrue(AppUpdate.eligible(7, 5, 0));
        assertFalse(AppUpdate.eligible(5, 5, 0));
        assertFalse(AppUpdate.eligible(4, 5, 0));
    }

    private static int verify(long size, String hash, String pkg, long version, Set<String> archive, Set<String> installed) {
        return AppUpdate.verify(RELEASE, size, hash, pkg, PACKAGE, version, 5, archive, installed);
    }

    @Test public void tc217AllFiveApkChecks() {
        Set<String> matching = new HashSet<>(Arrays.asList("A", "B"));
        Set<String> reversed = new HashSet<>(Arrays.asList("B", "A"));
        assertEquals(0, verify(5120, HASH, PACKAGE, 6, matching, reversed));
        assertEquals(1, verify(5121, HASH, PACKAGE, 6, matching, matching));
        assertEquals(2, verify(5120, "bad hash", PACKAGE, 6, matching, matching));
        assertEquals(3, verify(5120, HASH, "other.fixture.app", 6, matching, matching));
        assertEquals(4, verify(5120, HASH, PACKAGE, 5, matching, matching));
        assertEquals(4, verify(5120, HASH, PACKAGE, 7, matching, matching));
        assertEquals(5, verify(5120, HASH, PACKAGE, 6, Collections.singleton("A"), matching));
        assertEquals(5, verify(5120, HASH, PACKAGE, 6, matching, Collections.singleton("A")));
        assertEquals(5, verify(5120, HASH, PACKAGE, 6, Collections.emptySet(), Collections.emptySet()));
    }

    @Test public void tc218DeferUntilAllThreeConditionsAreAbsent() {
        for (int mask = 0; mask < 8; mask++) {
            assertEquals(mask == 0, AppUpdate.quiet((mask & 1) != 0, (mask & 2) != 0, (mask & 4) != 0));
        }
    }

    @Test public void tc219ResultAndConfirmOncePerVersion() {
        assertEquals(AppUpdate.Result.SUCCESS, AppUpdate.result(0));
        assertEquals(AppUpdate.Result.CONFIRM, AppUpdate.result(-1));
        assertTrue(AppUpdate.notifyVersion(6, 0));
        assertFalse(AppUpdate.notifyVersion(6, 6));
        assertTrue(AppUpdate.notifyVersion(7, 6));
        for (int failure = 1; failure <= 9; failure++) assertEquals(AppUpdate.Result.FAILED, AppUpdate.result(failure));
    }
}
