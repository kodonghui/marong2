package com.corthexhq.marong;

import java.net.URI;
import java.util.Locale;

/**
 * Which web addresses stay inside the app window (SPEC-102, SPEC-108).
 *
 * <p>Plain Java on purpose, so the rules run in JVM unit tests without a device.
 */
final class AppUrls {

    private AppUrls() {}

    /** True when url is a page on the same origin (scheme, host, port) as appUrl. */
    static boolean isAppPage(String url, String appUrl) {
        URI uri = parse(url);
        URI app = parse(appUrl);
        if (uri == null || app == null || uri.getRawUserInfo() != null) {
            return false;
        }
        String host = lowerHost(uri);
        return (
            host != null &&
            host.equals(lowerHost(app)) &&
            schemeOf(uri).equals(schemeOf(app)) &&
            portOf(uri) == portOf(app)
        );
    }

    static boolean isCallPage(String url, String appUrl) {
        if (!isAppPage(url, appUrl)) {
            return false;
        }
        String path = parse(url).getRawPath();
        return path.isEmpty() || "/".equals(path);
    }

    /** "https://host[:port]" for a full URL, used as the injection origin rule. */
    static String origin(String url) {
        URI uri = parse(url);
        if (uri == null || lowerHost(uri) == null) {
            throw new IllegalArgumentException("Not an absolute URL");
        }
        String scheme = schemeOf(uri);
        int port = uri.getPort();
        return scheme + "://" + lowerHost(uri) + (port == -1 ? "" : ":" + port);
    }

    /** Server outages that should swap in the app's own "can't connect" page. */
    static boolean isServerOutage(int statusCode) {
        return statusCode >= 500 && statusCode <= 599;
    }

    private static int portOf(URI uri) {
        if (uri.getPort() != -1) {
            return uri.getPort();
        }
        return "https".equals(schemeOf(uri)) ? 443 : "http".equals(schemeOf(uri)) ? 80 : -1;
    }

    private static String schemeOf(URI uri) {
        String scheme = uri.getScheme();
        return scheme == null ? "" : scheme.toLowerCase(Locale.ROOT);
    }

    private static String lowerHost(URI uri) {
        String host = uri.getHost();
        return host == null ? null : host.toLowerCase(Locale.ROOT);
    }

    private static URI parse(String url) {
        if (url == null) {
            return null;
        }
        try {
            URI uri = new URI(url);
            return uri.isAbsolute() ? uri : null;
        } catch (Exception e) {
            return null;
        }
    }
}
