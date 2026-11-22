package com.corthexhq.marong;

import java.util.Collection;
import java.util.function.Supplier;

/** Call audio policy. All entry points run on the main thread. */
final class CallAudio {
    private static final String[] PRIORITY = {"wired", "usb", "bluetooth", "speaker"};
    private static final int MODE_NORMAL = 0;
    private static final int MODE_IN_COMMUNICATION = 3;
    private static final int MAX_ROUTE_RETRIES = 3;
    private static final String ROUTE_FAILED = "audio_route_failed";
    private static final String VOLUME_FAILED = "volume_raise_failed";

    interface Phone {
        int mode();
        void setMode(int mode);
        Collection<String> outputs();
        void route(String kind);
        void unroute();
        int volume();
        int maxVolume();
        boolean volumeFixed();
        void setVolume(int volume);
        String ringer();
        void volumeKeysToCall(boolean enabled);
        void watch(CallAudio audio);
        void unwatch();
        void report(String json);
        void log(String event);
    }

    interface Store {
        int[] saved();
        void save(int original, int raised);
        void clear();
    }

    private final Phone phone;
    private final Store store;
    private boolean active;
    private boolean changedMode;
    private boolean requestedRoute;
    private boolean contestLogged;
    private int routeRetries;
    private String device = "unknown";

    CallAudio(Phone phone, Store store) {
        this.phone = phone;
        this.store = store;
    }

    static String pick(Collection<String> outputs) {
        for (String kind : PRIORITY) {
            if (outputs.contains(kind)) {
                return kind;
            }
        }
        return null;
    }

    static int floor(int max) {
        return (int) ((max * 3L + 4) / 5);
    }

    void start() {
        if (active) {
            return;
        }
        active = true;
        restoreLeftover();
        boolean modeReady = attempt(ROUTE_FAILED, () -> {
            if (phone.mode() == MODE_NORMAL) {
                phone.setMode(MODE_IN_COMMUNICATION);
                changedMode = true;
            }
        });
        attempt(ROUTE_FAILED, this::selectRoute);
        if (!modeReady) {
            device = "unknown";
        }
        attempt(VOLUME_FAILED, this::raiseVolume);
        attempt(ROUTE_FAILED, () -> phone.volumeKeysToCall(true));
        attempt(ROUTE_FAILED, () -> phone.watch(this));
        report();
    }

    private void selectRoute() {
        device = "unknown";
        setRoute(pick(phone.outputs()));
    }

    private void setRoute(String kind) {
        device = "unknown";
        if (kind != null) {
            phone.route(kind);
            requestedRoute = true;
            device = kind;
        }
    }

    private void raiseVolume() {
        int volume = phone.volume();
        int target = floor(phone.maxVolume());
        if (volume >= target) {
            return;
        }
        if (phone.volumeFixed()) {
            phone.log(VOLUME_FAILED);
            return;
        }
        try {
            store.save(volume, target);
            phone.setVolume(target);
        } catch (RuntimeException failure) {
            store.clear();
            throw failure;
        }
    }

    void devicesChanged() {
        if (active) {
            attempt(ROUTE_FAILED, this::selectRoute);
            report();
        }
    }

    void routedElsewhere(String kind) {
        String actual = kind == null ? "unknown" : kind;
        if (!active || actual.equals(device)) {
            return;
        }
        attempt(ROUTE_FAILED, () -> {
            String preferred = pick(phone.outputs());
            if (actual.equals(preferred)) {
                device = actual;
            } else if (routeRetries < MAX_ROUTE_RETRIES) {
                routeRetries++;
                setRoute(preferred);
            } else {
                device = actual;
                if (!contestLogged) {
                    contestLogged = true;
                    phone.log("audio_route_contested");
                }
            }
        });
        report();
    }

    void end() {
        if (!active) {
            return;
        }
        active = false;
        attempt(ROUTE_FAILED, phone::unwatch);
        if (requestedRoute) {
            attempt(ROUTE_FAILED, phone::unroute);
        }
        if (changedMode) {
            attempt(ROUTE_FAILED, () -> phone.setMode(MODE_NORMAL));
        }
        attempt(ROUTE_FAILED, () -> phone.volumeKeysToCall(false));
        restoreLeftover();
        changedMode = false;
        requestedRoute = false;
        contestLogged = false;
        routeRetries = 0;
        device = "unknown";
    }

    void restoreLeftover() {
        attempt(VOLUME_FAILED, () -> {
            int[] saved = store.saved();
            if (saved != null) {
                try {
                    if (phone.volume() == saved[1]) {
                        phone.setVolume(saved[0]);
                    }
                } finally {
                    store.clear();
                }
            }
        });
    }

    void report() {
        Integer volume = read(phone::volume, null);
        Integer max = read(phone::maxVolume, null);
        String ringer = read(phone::ringer, "unknown");
        attempt(ROUTE_FAILED, () -> phone.report("{\"device\":\"" + device + "\",\"voiceVolume\":" + volume
            + ",\"voiceVolumeMax\":" + max + ",\"ringer\":\"" + ringer + "\"}"));
    }

    private static <T> T read(Supplier<T> get, T fallback) {
        try {
            return get.get();
        } catch (RuntimeException failure) {
            return fallback;
        }
    }

    private boolean attempt(String event, Runnable action) {
        try {
            action.run();
            return true;
        } catch (RuntimeException failure) {
            phone.log(event);
            return false;
        }
    }
}
