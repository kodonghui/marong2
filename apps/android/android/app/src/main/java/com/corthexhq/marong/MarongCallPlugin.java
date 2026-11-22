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
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * The app side of the call page (SPEC-103 to SPEC-106), in the call window only.
 *
 * <p>The page script (assets/marong_page.js, injected by MarongWindowPlugin) reports when the page
 * holds or releases the microphone. While it does, this plugin keeps the call alive with a
 * microphone foreground service, keeps the screen on and keeps the WebView renderer important.
 * The chat window (D20, docs/app-chat.md SPEC-147) has no MarongCall: closing it must never end
 * or release a call.
 */
@CapacitorPlugin(name = "MarongCall")
public class MarongCallPlugin extends Plugin {

    private static final String END_CALL_JS = "window.__marongApp ? window.__marongApp.endCall() : false";
    private static final long HANG_UP_GRACE_MS = 4000;

    private final Handler main = new Handler(Looper.getMainLooper());
    private final Runnable releaseAfterHangUp = () -> setCallActive(false);
    private boolean callActive;
    private String callName;
    private CallAudio audio;
    private boolean destroyed;

    @Override
    public void load() {
        CallControl.attach(this);
        CallAudioPhone phone = new CallAudioPhone(getActivity(), main, bridge.getWebView());
        audio = new CallAudio(phone, phone);
        if (!CallControl.isActive()) {
            audio.restoreLeftover();
        }
    }

    @PluginMethod
    public void callStarted(PluginCall call) {
        String name = call.getString("name");
        main.post(() -> {
            callName = name == null || name.trim().isEmpty() || name.length() > 24
                ? getContext().getString(R.string.ring_caller) : name.trim();
            setCallActive(true);
        });
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
        if (destroyed) {
            return;
        }
        Activity activity = getActivity();
        if (activity == null || activity.isFinishing()) {
            callActive = false;
            CallControl.setActive(false);
            CallService.hide(getContext());
            audio.end();
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
            CallService.show(getContext(), callName);
            audio.start();
        } else {
            activity.getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && webView != null) {
                webView.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true);
            }
            CallService.hide(getContext());
            audio.end();
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
        destroyed = true;
        main.removeCallbacks(releaseAfterHangUp);
        callActive = false;
        CallControl.setActive(false);
        CallService.hide(getContext());
        audio.end();
        CallControl.detach(this);
        super.handleOnDestroy();
    }
}
