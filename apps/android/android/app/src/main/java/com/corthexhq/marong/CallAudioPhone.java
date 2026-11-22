package com.corthexhq.marong;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.webkit.WebView;
import androidx.annotation.RequiresApi;
import com.getcapacitor.Logger;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;

final class CallAudioPhone implements CallAudio.Phone, CallAudio.Store {
    private static final String ORIGINAL = "original";
    private static final String RAISED = "raised";
    private static final int CALL_STREAM = AudioManager.STREAM_VOICE_CALL;
    private static final String REPORT_JS =
        "(function(r){try{var c=window.__marongCall;if(c&&typeof c.audioRoute==='function')c.audioRoute(r);}catch(e){}})";

    private final Activity activity;
    private final AudioManager audio;
    private final Handler main;
    private final WebView webView;
    private final SharedPreferences preferences;
    private AudioDeviceCallback deviceCallback;
    private AudioManager.OnCommunicationDeviceChangedListener communicationListener;
    private boolean legacySpeakerEnabled;

    CallAudioPhone(Activity activity, Handler main, WebView webView) {
        this.activity = activity;
        this.audio = activity.getSystemService(AudioManager.class);
        this.main = main;
        this.webView = webView;
        this.preferences = activity.getSharedPreferences("marong_call_audio", Context.MODE_PRIVATE);
    }

    @Override
    public int mode() {
        return audio.getMode();
    }

    @Override
    public void setMode(int mode) {
        audio.setMode(mode);
    }

    @Override
    public Collection<String> outputs() {
        boolean modern = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S;
        List<AudioDeviceInfo> devices = modern
            ? audio.getAvailableCommunicationDevices()
            : Arrays.asList(audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS));
        List<String> outputs = new ArrayList<>();
        for (AudioDeviceInfo device : devices) {
            String kind = kindOf(device.getType(), modern);
            if (kind != null) {
                outputs.add(kind);
            }
        }
        return outputs;
    }

    static String kindOf(int type, boolean modern) {
        switch (type) {
            case AudioDeviceInfo.TYPE_WIRED_HEADSET:
            case AudioDeviceInfo.TYPE_WIRED_HEADPHONES:
                return "wired";
            case AudioDeviceInfo.TYPE_USB_HEADSET:
                return "usb";
            case AudioDeviceInfo.TYPE_BLUETOOTH_SCO:
                return "bluetooth";
            case AudioDeviceInfo.TYPE_BLE_HEADSET:
            case AudioDeviceInfo.TYPE_HEARING_AID:
                return modern ? "bluetooth" : null;
            case AudioDeviceInfo.TYPE_BUILTIN_SPEAKER:
                return "speaker";
            case AudioDeviceInfo.TYPE_BUILTIN_EARPIECE:
                return "earpiece";
            default:
                return null;
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void route(String kind) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            routeModern(kind);
        } else if ("speaker".equals(kind)) {
            if (!audio.isSpeakerphoneOn()) {
                audio.setSpeakerphoneOn(true);
                legacySpeakerEnabled = true;
            }
        } else {
            clearLegacySpeaker();
        }
    }

    @RequiresApi(Build.VERSION_CODES.S)
    private void routeModern(String kind) {
        for (AudioDeviceInfo device : audio.getAvailableCommunicationDevices()) {
            if (kind.equals(kindOf(device.getType(), true))) {
                if (!audio.setCommunicationDevice(device)) {
                    throw new IllegalStateException("Communication device refused");
                }
                return;
            }
        }
        throw new IllegalStateException("Communication device unavailable");
    }

    @Override
    public void unroute() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            audio.clearCommunicationDevice();
        } else {
            clearLegacySpeaker();
        }
    }

    @SuppressWarnings("deprecation")
    private void clearLegacySpeaker() {
        if (legacySpeakerEnabled) {
            audio.setSpeakerphoneOn(false);
            legacySpeakerEnabled = false;
        }
    }

    @Override
    public int volume() {
        return audio.getStreamVolume(CALL_STREAM);
    }

    @Override
    public int maxVolume() {
        return audio.getStreamMaxVolume(CALL_STREAM);
    }

    @Override
    public boolean volumeFixed() {
        return audio.isVolumeFixed();
    }

    @Override
    public void setVolume(int volume) {
        audio.setStreamVolume(CALL_STREAM, volume, 0);
    }

    @Override
    public String ringer() {
        switch (audio.getRingerMode()) {
            case AudioManager.RINGER_MODE_NORMAL: return "normal";
            case AudioManager.RINGER_MODE_VIBRATE: return "vibrate";
            case AudioManager.RINGER_MODE_SILENT: return "silent";
            default: return "unknown";
        }
    }

    @Override
    public void volumeKeysToCall(boolean enabled) {
        activity.setVolumeControlStream(enabled ? CALL_STREAM : AudioManager.USE_DEFAULT_STREAM_TYPE);
    }

    @Override
    public void watch(CallAudio call) {
        deviceCallback = new AudioDeviceCallback() {
            @Override
            public void onAudioDevicesAdded(AudioDeviceInfo[] added) {
                if (deviceCallback == this) {
                    call.devicesChanged();
                }
            }

            @Override
            public void onAudioDevicesRemoved(AudioDeviceInfo[] removed) {
                if (deviceCallback == this) {
                    call.devicesChanged();
                }
            }
        };
        try {
            audio.registerAudioDeviceCallback(deviceCallback, main);
        } finally {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                watchCommunicationDevice(call);
            }
        }
    }

    @RequiresApi(Build.VERSION_CODES.S)
    private void watchCommunicationDevice(CallAudio call) {
        communicationListener = new AudioManager.OnCommunicationDeviceChangedListener() {
            @Override
            public void onCommunicationDeviceChanged(AudioDeviceInfo device) {
                if (communicationListener == this) {
                    call.routedElsewhere(device == null ? null : kindOf(device.getType(), true));
                }
            }
        };
        audio.addOnCommunicationDeviceChangedListener(activity.getMainExecutor(), communicationListener);
    }

    @Override
    public void unwatch() {
        try {
            if (deviceCallback != null) {
                AudioDeviceCallback callback = deviceCallback;
                deviceCallback = null;
                audio.unregisterAudioDeviceCallback(callback);
            }
        } finally {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && communicationListener != null) {
                AudioManager.OnCommunicationDeviceChangedListener listener = communicationListener;
                communicationListener = null;
                audio.removeOnCommunicationDeviceChangedListener(listener);
            }
        }
    }

    @Override
    public void report(String json) {
        if (webView != null) {
            webView.evaluateJavascript(REPORT_JS + "(" + json + ")", null);
        }
    }

    @Override
    public void log(String event) {
        Logger.warn("MarongCall", event);
    }

    @Override
    public int[] saved() {
        if (!preferences.contains(ORIGINAL) || !preferences.contains(RAISED)) {
            return null;
        }
        return new int[] {preferences.getInt(ORIGINAL, 0), preferences.getInt(RAISED, 0)};
    }

    @Override
    public void save(int original, int raised) {
        if (!preferences.edit().putInt(ORIGINAL, original).putInt(RAISED, raised).commit()) {
            throw new IllegalStateException("Call volume backup failed");
        }
    }

    @Override
    public void clear() {
        if (!preferences.edit().remove(ORIGINAL).remove(RAISED).commit()) {
            throw new IllegalStateException("Call volume backup could not be cleared");
        }
    }
}
