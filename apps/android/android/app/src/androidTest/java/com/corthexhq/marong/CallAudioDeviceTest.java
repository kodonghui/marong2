package com.corthexhq.marong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.Manifest;
import android.app.Instrumentation;
import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.os.Build;
import android.os.SystemClock;
import android.view.KeyEvent;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.filters.SdkSuppress;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import java.util.function.BooleanSupplier;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
@SdkSuppress(minSdkVersion = 31)
public class CallAudioDeviceTest {
    @Test
    public void callUsesTheSpeakerAndVolumeKeysThenRestoresDeviceSettings() {
        Instrumentation instrumentation = InstrumentationRegistry.getInstrumentation();
        Context context = instrumentation.getTargetContext();
        instrumentation.getUiAutomation().grantRuntimePermission(context.getPackageName(), Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= 33) {
            instrumentation.getUiAutomation().grantRuntimePermission(context.getPackageName(), Manifest.permission.POST_NOTIFICATIONS);
        }
        AudioManager manager = context.getSystemService(AudioManager.class);
        int stream = AudioManager.STREAM_VOICE_CALL;
        int modeBefore = manager.getMode();
        int routeBefore = outputType(manager);
        int volumeBefore = manager.getStreamVolume(stream);
        assertEquals(AudioManager.MODE_NORMAL, modeBefore);

        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                assertEquals(AudioManager.USE_DEFAULT_STREAM_TYPE, activity.getVolumeControlStream());
                plugin(activity).callStarted(pageCall("callStarted"));
            });
            try {
                await(() -> manager.getMode() == AudioManager.MODE_IN_COMMUNICATION
                    && outputType(manager) == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER);
                scenario.onActivity(activity -> assertEquals(stream, activity.getVolumeControlStream()));
                int inCallVolume = manager.getStreamVolume(stream);
                assertTrue(inCallVolume >= CallAudio.floor(manager.getStreamMaxVolume(stream)));
                instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_VOLUME_DOWN);
                await(() -> manager.getStreamVolume(stream) < inCallVolume);
            } finally {
                scenario.onActivity(activity -> plugin(activity).callEnded(pageCall("callEnded")));
            }
            await(() -> manager.getMode() == modeBefore && outputType(manager) == routeBefore);
            scenario.onActivity(activity ->
                assertEquals(AudioManager.USE_DEFAULT_STREAM_TYPE, activity.getVolumeControlStream()));
        } finally {
            manager.setStreamVolume(stream, volumeBefore, 0);
        }
    }

    private static MarongCallPlugin plugin(MainActivity activity) {
        return (MarongCallPlugin) activity.getBridge().getPlugin("MarongCall").getInstance();
    }

    private static PluginCall pageCall(String method) {
        return new PluginCall(null, "MarongCall", "test", method, new JSObject()) {
            @Override
            public void resolve() {}
        };
    }

    private static int outputType(AudioManager manager) {
        AudioDeviceInfo output = manager.getCommunicationDevice();
        return output == null ? AudioDeviceInfo.TYPE_UNKNOWN : output.getType();
    }

    private static void await(BooleanSupplier condition) {
        long deadline = SystemClock.uptimeMillis() + 3000;
        while (!condition.getAsBoolean() && SystemClock.uptimeMillis() < deadline) {
            SystemClock.sleep(30);
        }
        assertTrue("Expected audio settings were not applied", condition.getAsBoolean());
    }
}
