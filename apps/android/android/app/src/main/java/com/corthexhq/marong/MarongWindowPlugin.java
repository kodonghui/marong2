package com.corthexhq.marong;

import android.webkit.WebView;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.WebViewListener;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;

/**
 * What both app windows share (SPEC-102, SPEC-106, SPEC-108; D20, docs/app-chat.md SPEC-143,
 * SPEC-144 and SPEC-147): the web view client (same-site session login, the "can't connect"
 * page only for server outages, moving between the call window and the chat window), the
 * microphone rule and the page script (assets/marong_page.js), injected only into the call site's
 * origin. Each window registers it first, so all of it is in place before its first page loads.
 */
@CapacitorPlugin(name = "MarongWindow")
public class MarongWindowPlugin extends Plugin {

    static final String PAGE_SCRIPT_ASSET = "marong_page.js";
    private static final String TAG = "MarongWindow";

    @Override
    public void load() {
        boolean chatWindow = getActivity() instanceof ChatActivity;
        bridge.setWebViewClient(new MarongWebViewClient(bridge, chatWindow));
        // Only the call window holds calls; the chat window asks for no microphone.
        installChromeClient(!chatWindow);
        String appUrl = bridge.getServerUrl();
        String script = readAsset(PAGE_SCRIPT_ASSET);
        if (appUrl != null && script != null) {
            installPageScript(bridge.getWebView(), appUrl, script);
        } else {
            Logger.error(TAG, "Page script not installed", null);
        }
    }

    /** Capacitor has no setter for its chrome client; replacing it on the WebView keeps all its behaviour. */
    private void installChromeClient(boolean microphone) {
        try {
            bridge.getWebView().setWebChromeClient(new MarongChromeClient(bridge, microphone));
        } catch (IllegalStateException e) {
            // Too late to register for permission results: keep Capacitor's own client.
            Logger.warn(TAG, "Chrome client not replaced");
        }
    }

    /** Runs before Capacitor's own bridge script, so the page script reads Capacitor lazily. */
    private void installPageScript(WebView webView, String appUrl, String script) {
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            try {
                WebViewCompat.addDocumentStartJavaScript(webView, script, Collections.singleton(AppUrls.origin(appUrl)));
                return;
            } catch (IllegalArgumentException e) {
                Logger.warn(TAG, "Document start script refused, using page load");
            }
        }
        // Older WebView: run it after each call site page load. The script ignores a second run.
        bridge.addWebViewListener(
            new WebViewListener() {
                @Override
                public void onPageLoaded(WebView view) {
                    if (AppUrls.isAppPage(view.getUrl(), appUrl)) {
                        view.evaluateJavascript(script, null);
                    }
                }
            }
        );
    }

    private String readAsset(String name) {
        try (InputStream in = getContext().getAssets().open(name); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) != -1) {
                out.write(buffer, 0, read);
            }
            return out.toString(StandardCharsets.UTF_8.name());
        } catch (Exception e) {
            return null;
        }
    }
}
