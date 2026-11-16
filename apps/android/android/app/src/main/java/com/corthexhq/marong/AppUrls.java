package com.corthexhq.marong;

import java.net.URI;
import java.util.Locale;

/**
 * Which web addresses stay inside the app window (SPEC-102, SPEC-108).
 *
 * <p>Plain Java on purpose, so the rules run in JVM unit tests without a device.
 */
final class AppUrls {

    private static final String ACCESS_SUFFIX = ".cloudflareaccess.com";

    private AppUrls() {}

    /**
     * True for the Cloudflare Access sign-in pages ("team.cloudflareaccess.com"), where the
     * email one-time code is entered. Exactly one label before the suffix, HTTPS, default port.
     */
    static boolean isAccessLogin(String url) {
        URI uri = parse(url);
        if (uri == null || !isHttpsDefaultPort(uri) || uri.getRawUserInfo() != null) {
            return false;
        }
        String host = lowerHost(uri);
        if (host == null || !host.endsWith(ACCESS_SUFFIX)) {
            return false;
        }
        String team = host.substring(0, host.length() - ACCESS_SUFFIX.length());
        return !team.isEmpty() && team.indexOf('.') < 0;
    }

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

    private static boolean isHttpsDefaultPort(URI uri) {
        return "https".equals(schemeOf(uri)) && (uri.getPort() == -1 || uri.getPort() == 443);
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
