package com.corthexhq.marong;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONObject;

/**
 * The app side of notifications and rings for the page script (docs/app-chat.md SPEC-123,
 * docs/app-ring.md SPEC-139 and SPEC-140). Like MarongCall, only pages of the app's own address
 * reach it: Capacitor's bridge runs on that origin alone.
 */
@CapacitorPlugin(name = "MarongPush")
public class MarongPushPlugin extends Plugin {

    @Override
    public void load() {
        PushEvents.attach(this);
    }

    /** What the page reports to the server with PUT /chat/api/devices/{installId} (API-105). */
    @PluginMethod
    public void state(PluginCall call) {
        Context context = getContext();
        String fid = PushState.fid(context);
        JSObject ring = new JSObject();
        ring.put("channel", PushState.ringChannel(context));
        ring.put("fullScreen", PushState.fullScreen(context));
        JSObject result = new JSObject();
        result.put("installId", PushState.installId(context));
        result.put("fid", fid == null ? JSONObject.NULL : fid);
        result.put("notifications", PushState.notifications(context));
        result.put("appVersion", PushState.appVersion(context));
        result.put("ring", ring);
        // For the chat menu (SCR-109): the full-screen setting exists from Android 14, and Samsung
        // phones may hold back a sleeping app's messages.
        result.put("fullScreenSettings", Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE);
        result.put("samsung", "samsung".equalsIgnoreCase(Build.MANUFACTURER));
        call.resolve(result);
    }

    /** The chat page is on screen (true) or not (false). On screen, its notifications go away. */
    @PluginMethod
    public void chatVisible(PluginCall call) {
        boolean visible = Boolean.TRUE.equals(call.getBoolean("visible", false));
        PushEvents.setChatVisible(visible);
        if (visible) {
            Talk.clear(getContext());
        }
        call.resolve();
    }

    /** Android's notification settings for this app, or for the '마롱이 전화' channel. */
    @PluginMethod
    public void openNotificationSettings(PluginCall call) {
        Context context = getContext();
        Intent settings;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && "ring".equals(call.getString("channel"))) {
            Channels.ensure(context);
            settings = new Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName())
                .putExtra(Settings.EXTRA_CHANNEL_ID, Channels.RING);
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName());
        } else {
            settings = appDetails(context);
        }
        open(call, settings);
    }

    /** Android 14+: the setting that lets the ring screen show over the lock screen (SPEC-140). */
    @PluginMethod
    public void openFullScreenSettings(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            JSObject result = new JSObject();
            result.put("opened", false);
            call.resolve(result);
            return;
        }
        Context context = getContext();
        open(call, new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT).setData(Uri.fromParts("package", context.getPackageName(), null)));
    }

    /** FCM gave or took this installation's id: the page sends a new device report. */
    void notifyRegistered() {
        // Kept until a page listens, so a page that is still loading reports it too.
        notifyListeners("registered", new JSObject(), true);
    }

    @Override
    protected void handleOnResume() {
        super.handleOnResume();
        // Back from Android's settings or from another app: the page checks what changed.
        notifyListeners("resumed", new JSObject());
    }

    @Override
    protected void handleOnPause() {
        PushEvents.setChatVisible(false);
        super.handleOnPause();
    }

    @Override
    protected void handleOnDestroy() {
        PushEvents.setChatVisible(false);
        PushEvents.detach(this);
        super.handleOnDestroy();
    }

    private void open(PluginCall call, Intent settings) {
        Activity activity = getActivity();
        Context context = activity != null ? activity : getContext();
        if (activity == null) {
            settings.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        }
        boolean opened;
        try {
            context.startActivity(settings);
            opened = true;
        } catch (ActivityNotFoundException e) {
            // Some phones lack the exact page: the app's details page has the same switches.
            Intent details = appDetails(context);
            if (activity == null) {
                details.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            }
            try {
                context.startActivity(details);
                opened = true;
            } catch (ActivityNotFoundException again) {
                opened = false;
            }
        }
        JSObject result = new JSObject();
        result.put("opened", opened);
        call.resolve(result);
    }

    private static Intent appDetails(Context context) {
        return new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(Uri.fromParts("package", context.getPackageName(), null));
    }
}
