package com.corthexhq.marong;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.WindowManager;
import android.webkit.WebView;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.WebViewListener;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;

/**
 * The app side of the call page (SPEC-102 to SPEC-106).
 *
 * <p>The page script (assets/marong_page.js) is injected only into the call site's origin and
 * reports when the page holds or releases the microphone. While it does, this plugin keeps the
 * call alive with a microphone foreground service, keeps the screen on and keeps the WebView
 * renderer important. The Access sign-in pages open inside the app but get no plugin access.
 */
@CapacitorPlugin(name = "MarongCall")
public class MarongCallPlugin extends Plugin {

    static final String PAGE_SCRIPT_ASSET = "marong_page.js";
    private static final String END_CALL_JS = "window.__marongApp ? window.__marongApp.endCall() : false";
    private static final long HANG_UP_GRACE_MS = 4000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable releaseAfterHangUp = () -> setCallActive(false);
    private boolean callActive;

    @Override
    public void load() {
        // Plugins load before the WebView opens the call page, so both take effect on the first load.
        bridge.setWebViewClient(new MarongWebViewClient(bridge));
        installChromeClient();
        String appUrl = bridge.getServerUrl();
        String script = readAsset(PAGE_SCRIPT_ASSET);
        if (appUrl != null && script != null) {
            installPageScript(bridge.getWebView(), appUrl, script);
        } else {
            Logger.error("MarongCall", "Page script not installed", null);
        }
        CallControl.attach(this);
    }

    /** Capacitor has no setter for its chrome client; replacing it on the WebView keeps all its behaviour. */
    private void installChromeClient() {
        try {
            bridge.getWebView().setWebChromeClient(new MarongChromeClient(bridge));
        } catch (IllegalStateException e) {
            // Too late to register for permission results: keep Capacitor's own client.
            Logger.warn("MarongCall", "Chrome client not replaced");
        }
    }

    /** Runs before Capacitor's own bridge script, so the page script reads Capacitor lazily. */
    private void installPageScript(WebView webView, String appUrl, String script) {
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            try {
                WebViewCompat.addDocumentStartJavaScript(webView, script, Collections.singleton(AppUrls.origin(appUrl)));
                return;
            } catch (IllegalArgumentException e) {
                Logger.warn("MarongCall", "Document start script refused, using page load");
            }
        }
        // Older WebView: run it after each call page load. The script ignores a second run.
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

    /** Keeps the Access email-code sign-in in the app window; null leaves the decision to Capacitor. */
    @Override
    public Boolean shouldOverrideLoad(Uri url) {
        return AppUrls.isAccessLogin(url.toString()) ? Boolean.FALSE : null;
    }

    @PluginMethod
    public void callStarted(PluginCall call) {
        main.post(() -> setCallActive(true));
        call.resolve();
    }

    @PluginMethod
    public void callEnded(PluginCall call) {
        main.post(() -> setCallActive(false));
        call.resolve();
    }

    /** The page could not get the microphone: offer the app settings when Android blocks it. */
    @PluginMethod
    public void microphoneDenied(PluginCall call) {
        main.post(this::offerMicrophoneSettings);
        call.resolve();
    }

    /** "끊기" on the call notification: end the call through the page, as its own button does. */
    void hangUpFromNotification() {
        main.post(() -> {
            WebView webView = bridge == null ? null : bridge.getWebView();
            if (webView == null) {
                setCallActive(false);
                return;
            }
            webView.evaluateJavascript(END_CALL_JS, null);
            // The page reports the end itself; release anyway if it cannot.
            main.removeCallbacks(releaseAfterHangUp);
            main.postDelayed(releaseAfterHangUp, HANG_UP_GRACE_MS);
        });
    }

    private void setCallActive(boolean active) {
        main.removeCallbacks(releaseAfterHangUp);
        Activity activity = getActivity();
        if (activity == null || activity.isFinishing()) {
            callActive = false;
            CallControl.setActive(false);
            CallService.hide(getContext());
            return;
        }
        if (active == callActive) {
            return;
        }
        callActive = active;
        CallControl.setActive(active);
        WebView webView = bridge.getWebView();
        if (active) {
            // A call started: a ring still sounding stops (docs/app-ring.md SPEC-132).
            Ring.cancel(getContext());
            activity.getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && webView != null) {
                webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false);
            }
            CallService.show(getContext());
        } else {
            activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && webView != null) {
                webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true);
            }
            CallService.hide(getContext());
        }
    }

    private void offerMicrophoneSettings() {
        Activity activity = getActivity();
        if (activity == null || activity.isFinishing()) {
            return;
        }
        if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        // After a first refusal Android asks again at the next call; only a lasting refusal needs the settings.
        if (ActivityCompat.shouldShowRequestPermissionRationale(activity, Manifest.permission.RECORD_AUDIO)) {
            return;
        }
        new AlertDialog.Builder(activity)
            .setTitle(R.string.mic_denied_title)
            .setMessage(R.string.mic_denied_message)
            .setPositiveButton(
                R.string.mic_denied_open_settings,
                (dialog, which) -> {
                    Intent settings = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                        .setData(Uri.fromParts("package", activity.getPackageName(), null));
                    activity.startActivity(settings);
                }
            )
            .setNegativeButton(R.string.mic_denied_close, null)
            .show();
    }

    @Override
    protected void handleOnDestroy() {
        main.removeCallbacks(releaseAfterHangUp);
        callActive = false;
        CallControl.setActive(false);
        CallService.hide(getContext());
        CallControl.detach(this);
        super.handleOnDestroy();
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
