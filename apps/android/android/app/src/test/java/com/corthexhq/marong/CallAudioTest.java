package com.corthexhq.marong;

import static org.junit.Assert.*;

import android.media.AudioDeviceInfo;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.List;
import org.junit.Test;

public class CallAudioTest {
    private final TestPhone phone = new TestPhone();
    private final CallAudio audio = new CallAudio(phone, phone);

    @Test
    public void picksInPriorityOrderAndNeverPicksEarpiece() {
        assertEquals("wired", CallAudio.pick(Arrays.asList("speaker", "bluetooth", "usb", "wired")));
        assertEquals("usb", CallAudio.pick(Arrays.asList("speaker", "bluetooth", "usb")));
        assertEquals("bluetooth", CallAudio.pick(Arrays.asList("speaker", "bluetooth")));
        assertEquals("speaker", CallAudio.pick(Arrays.asList("earpiece", "speaker")));
        assertNull(CallAudio.pick(Collections.singletonList("earpiece")));
        assertNull(CallAudio.pick(Collections.emptyList()));
        phone.outputs = Collections.singletonList("earpiece");
        audio.start();
        assertNull(phone.route);
        assertTrue(phone.report.contains("\"device\":\"unknown\""));
        audio.end();
        assertEquals(0, phone.unroutes);
    }

    @Test
    public void mapsOnlyCommunicationOutputs() {
        for (boolean modern : new boolean[] {false, true}) {
            assertEquals("wired", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, modern));
            assertEquals("wired", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_WIRED_HEADPHONES, modern));
            assertEquals("usb", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_USB_HEADSET, modern));
            assertEquals("bluetooth", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BLUETOOTH_SCO, modern));
            assertEquals("speaker", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BUILTIN_SPEAKER, modern));
            assertEquals("earpiece", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BUILTIN_EARPIECE, modern));
            assertNull(CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, modern));
        }
        assertEquals("bluetooth", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BLE_HEADSET, true));
        assertEquals("bluetooth", CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_HEARING_AID, true));
        assertNull(CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_BLE_HEADSET, false));
        assertNull(CallAudioPhone.kindOf(AudioDeviceInfo.TYPE_HEARING_AID, false));
    }

    @Test
    public void roundsUpTheVolumeFloor() {
        assertEquals(9, CallAudio.floor(15));
        assertEquals(5, CallAudio.floor(7));
        assertEquals(6, CallAudio.floor(10));
        assertEquals(1, CallAudio.floor(1));
    }

    @Test
    public void raisesVolumeAndRestoresCallSettingsOnce() {
        audio.start();
        audio.start();
        assertEquals("speaker", phone.route);
        assertEquals(3, phone.mode);
        assertTrue(phone.callKeys);
        assertEquals(9, phone.volume);
        assertArrayEquals(new int[] {3, 9}, phone.saved);
        assertEquals("{\"device\":\"speaker\",\"voiceVolume\":9,\"voiceVolumeMax\":15,\"ringer\":\"vibrate\"}",
            phone.report);
        audio.end();
        audio.end();
        assertFalse(phone.callKeys);
        assertEquals(0, phone.mode);
        assertEquals(3, phone.volume);
        assertNull(phone.saved);
        assertEquals(1, phone.watches);
        assertEquals(1, phone.unwatches);
        assertEquals(1, phone.unroutes);
    }

    @Test
    public void keepsAnExistingCommunicationModeAndManualVolumeChange() {
        phone.mode = 3;
        audio.start();
        phone.volume = 12;
        audio.end();
        assertEquals(3, phone.mode);
        assertEquals(12, phone.volume);
        assertEquals(0, phone.modeChanges);
        assertNull(phone.saved);
    }

    @Test
    public void skipsVolumeAlreadyAboveFloor() {
        phone.volume = 13;
        audio.start();
        audio.end();
        assertEquals(13, phone.volume);
        assertEquals(0, phone.volumeChanges);
    }

    @Test
    public void fixedVolumeIsReportedAndDoesNotBlockCall() {
        phone.fixed = true;
        audio.start();
        assertEquals(3, phone.volume);
        assertTrue(phone.report.contains("\"voiceVolume\":3"));
        assertTrue(phone.callKeys);
        assertNull(phone.saved);
        assertEquals(Collections.singletonList("volume_raise_failed"), phone.logs);
    }

    @Test
    public void volumeFailureClearsTheBackupAndDoesNotBlockCall() {
        phone.failSetVolume = true;
        audio.start();
        assertEquals(3, phone.volume);
        assertNull(phone.saved);
        assertTrue(phone.callKeys);
        assertEquals(Collections.singletonList("volume_raise_failed"), phone.logs);
    }

    @Test
    public void leftoverRecoveryDoesNotOverwriteManualVolume() {
        phone.saved = new int[] {3, 9};
        phone.volume = 12;
        audio.restoreLeftover();
        assertEquals(12, phone.volume);
        assertNull(phone.saved);
        phone.saved = new int[] {3, 9};
        phone.volume = 9;
        audio.restoreLeftover();
        assertEquals(3, phone.volume);
        assertNull(phone.saved);
    }

    @Test
    public void startRecoversTheOriginalVolumeBeforeRaisingAgain() {
        phone.saved = new int[] {3, 9};
        phone.volume = 9;
        audio.start();
        assertArrayEquals(new int[] {3, 9}, phone.saved);
        audio.end();
        assertEquals(3, phone.volume);
    }

    @Test
    public void deviceEventsDoNotConsumeRouteRetriesOrReapplyTheVolume() {
        audio.start();
        phone.volume = 4;
        phone.outputs = Arrays.asList("wired", "speaker");
        audio.devicesChanged();
        assertEquals("wired", phone.route);
        phone.outputs = Collections.singletonList("speaker");
        audio.devicesChanged();
        assertEquals("speaker", phone.route);
        assertEquals(4, phone.volume);
        for (int i = 0; i < 3; i++) {
            audio.routedElsewhere("earpiece");
        }
        assertEquals(6, phone.routes);
        audio.routedElsewhere("earpiece");
        audio.routedElsewhere(null);
        assertEquals(6, phone.routes);
        assertEquals(Collections.singletonList("audio_route_contested"), phone.logs);
        assertTrue(phone.report.contains("\"device\":\"unknown\""));
    }

    @Test
    public void acceptsSystemRouteToNewPreferredDeviceAndRetriesNullDevice() {
        audio.start();
        phone.outputs = Arrays.asList("speaker", "bluetooth");
        audio.routedElsewhere("bluetooth");
        audio.routedElsewhere("bluetooth");
        assertEquals(1, phone.routes);
        assertTrue(phone.report.contains("\"device\":\"bluetooth\""));
        audio.routedElsewhere(null);
        assertEquals(2, phone.routes);
        assertEquals("bluetooth", phone.route);
        audio.end();
        audio.devicesChanged();
        audio.routedElsewhere("earpiece");
        assertEquals(2, phone.routes);
    }

    @Test
    public void routeAndVolumeReadFailuresLeaveOtherSettingsAvailable() {
        phone.failRoute = true;
        phone.failReadVolume = true;
        audio.start();
        assertTrue(phone.callKeys);
        assertEquals(1, phone.watches);
        assertEquals("{\"device\":\"unknown\",\"voiceVolume\":null,\"voiceVolumeMax\":15,\"ringer\":\"vibrate\"}",
            phone.report);
        assertEquals(Arrays.asList("audio_route_failed", "volume_raise_failed"), phone.logs);
    }

    private static final class TestPhone implements CallAudio.Phone, CallAudio.Store {
        private int mode;
        private int volume = 3;
        private int[] saved;
        private boolean fixed;
        private boolean failSetVolume;
        private boolean failReadVolume;
        private boolean failRoute;
        private boolean callKeys;
        private int routes;
        private int unroutes;
        private int watches;
        private int unwatches;
        private int modeChanges;
        private int volumeChanges;
        private String route;
        private String report;
        private List<String> outputs = Collections.singletonList("speaker");
        private final List<String> logs = new ArrayList<>();

        public int mode() { return mode; }
        public void setMode(int value) { mode = value; modeChanges++; }
        public Collection<String> outputs() { return outputs; }
        public void route(String kind) {
            if (failRoute) throw new IllegalStateException();
            route = kind;
            routes++;
        }
        public void unroute() { route = null; unroutes++; }
        public int volume() {
            if (failReadVolume) throw new IllegalStateException();
            return volume;
        }
        public int maxVolume() { return 15; }
        public boolean volumeFixed() { return fixed; }
        public void setVolume(int value) {
            if (failSetVolume) throw new SecurityException();
            volume = value;
            volumeChanges++;
        }
        public String ringer() { return "vibrate"; }
        public void volumeKeysToCall(boolean enabled) { callKeys = enabled; }
        public void watch(CallAudio audio) { watches++; }
        public void unwatch() { unwatches++; }
        public void report(String json) { report = json; }
        public void log(String event) { logs.add(event); }
        public int[] saved() { return saved; }
        public void save(int original, int raised) {
            assertEquals(volume, original);
            saved = new int[] {original, raised};
        }
        public void clear() { saved = null; }
    }
}
