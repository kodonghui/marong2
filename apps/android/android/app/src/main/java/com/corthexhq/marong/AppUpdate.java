package com.corthexhq.marong;

import java.util.Set;
import java.util.regex.Pattern;

/** Self-update rules shared by the job, result receiver and JVM tests (SPEC-289~297). */
final class AppUpdate {
    static final long CHECK_INTERVAL_MS = 6L * 60 * 60 * 1000;
    private static final long FORCED_INTERVAL_MS = 10 * 60_000L;
    private static final long MANUAL_RECHECK_INTERVAL_MS = 10 * 60_000L;
    static final int MAX_VERSION = 2_100_000_000;
    static final long APK_MAX_BYTES = 200L * 1024 * 1024;
    static final int FAILURE_LIMIT = 3;
    static final String RELEASE_PATH = "/chat/api/app/release";
    private static final Pattern VERSION_NAME = Pattern.compile("[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}");
    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");

    private AppUpdate() {}

    enum Check { RELEASE, NONE, SIGNED_OUT, RETRY }
    enum Result { SUCCESS, CONFIRM, FAILED }

    static final class Release {
        final int code;
        final String name;
        final long size;
        final String sha256;
        final String url;

        private Release(int code, String name, long size, String sha256, String url) {
            this.code = code;
            this.name = name;
            this.size = size;
            this.sha256 = sha256;
            this.url = url;
        }

        boolean sameAs(Release other) {
            return code == other.code && name.equals(other.name) && size == other.size && sha256.equals(other.sha256);
        }
    }

    static Release release(Object code, Object name, Object size, Object sha256, Object url) {
        if (!(code instanceof Integer || code instanceof Long) || !(size instanceof Integer || size instanceof Long)
                || !(name instanceof String) || !(sha256 instanceof String) || !(url instanceof String)) return null;
        long version = ((Number) code).longValue();
        long bytes = ((Number) size).longValue();
        String versionName = (String) name;
        if (version < 1 || version > MAX_VERSION || bytes < 1 || bytes > APK_MAX_BYTES
                || !VERSION_NAME.matcher(versionName).matches() || !SHA256.matcher((String) sha256).matches()) return null;
        String expected = "/chat/app/marong-" + versionName + "-" + version + ".apk";
        if (!expected.equals(url)) return null;
        return new Release((int) version, versionName, bytes, (String) sha256, expected);
    }

    static boolean shouldCheck(long checkedAt, long now) {
        return checkedAt <= 0 || now < checkedAt || now - checkedAt >= CHECK_INTERVAL_MS;
    }

    static boolean shouldRecheckForManualInstall(long checkedAt, long now) {
        return checkedAt <= 0 || now < checkedAt || now - checkedAt > MANUAL_RECHECK_INTERVAL_MS;
    }

    static int pushVersion(String value) {
        if (value == null || !value.matches("[0-9]{1,10}")) return 0;
        long code = Long.parseLong(value);
        return code > MAX_VERSION ? 0 : (int) code;
    }

    static boolean shouldForce(int offered, long installed, long forcedAt, long now) {
        return offered > installed && (forcedAt <= 0 || now < forcedAt || now - forcedAt >= FORCED_INTERVAL_MS);
    }

    static Check check(int status) {
        if (status == 200) return Check.RELEASE;
        if (status == 204) return Check.NONE;
        if ((status >= 300 && status < 400) || status == 401 || status == 403) return Check.SIGNED_OUT;
        return Check.RETRY;
    }

    static boolean eligible(int version, long installed, int failures) {
        return version > installed && failures < FAILURE_LIMIT;
    }

    static int afterFailure(int failures) {
        return Math.min(failures + 1, FAILURE_LIMIT);
    }

    static boolean quiet(boolean calling, boolean ringing, boolean visible) {
        return !calling && !ringing && !visible;
    }

    static int verify(Release release, long bytes, String sha256, String archivePackage, String installedPackage,
                      long archiveVersion, long installedVersion, Set<String> archiveKeys, Set<String> installedKeys) {
        if (bytes != release.size) return 1;
        if (!release.sha256.equals(sha256)) return 2;
        if (!installedPackage.equals(archivePackage)) return 3;
        if (archiveVersion != release.code || archiveVersion <= installedVersion) return 4;
        if (installedKeys.isEmpty() || !installedKeys.equals(archiveKeys)) return 5;
        return 0;
    }

    static boolean notifyVersion(int version, int notified) {
        return version != notified;
    }

    static Result result(int status) {
        if (status == 0) return Result.SUCCESS;
        return status == -1 ? Result.CONFIRM : Result.FAILED;
    }
}
