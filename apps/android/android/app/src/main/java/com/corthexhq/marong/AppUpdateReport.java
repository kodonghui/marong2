package com.corthexhq.marong;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.getcapacitor.CapConfig;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Reports native update transitions in order, even when both WebViews are closed (SPEC-433). */
public final class AppUpdateReport extends JobService {
    static final String DOWNLOADED = "downloaded";
    static final String WAITING_QUIET = "waiting_quiet";
    static final String NEEDS_CONFIRM = "needs_confirm";
    static final String FAILED = "failed";
    static final String INSTALLED = "installed";

    static final int JOB_ID = 2217;
    static final long RETRY_MS = 15 * 60_000L;
    static final long LIMIT_MS = 24 * 60 * 60_000L;
    private static final String PENDING = "pendingReport";
    private static final String REPORTED = "reported";
    private static final String WAITING_VERSION = "waitingQuietVersion";
    private static final Object LOCK = new Object();

    private static int pageReports; // Protected by LOCK.
    private static boolean running; // Protected by LOCK.

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private CancellationSignal active;

    enum Response { SENT, SIGN_IN, DROP, RETRY }

    static Response response(int status) {
        if (status == 200 || status == 201) return Response.SENT;
        if ((status >= 300 && status < 400) || status == 401 || status == 403) return Response.SIGN_IN;
        // API-105 has only one 409 response (too_many_devices).
        if (status == 400 || status == 409) return Response.DROP;
        return Response.RETRY;
    }

    static boolean expired(long first, long now) {
        return now >= first && now - first >= LIMIT_MS;
    }

    static long retryDelay(long retryAt, long now) {
        if (retryAt <= now || retryAt - now > RETRY_MS) return 0;
        return retryAt - now;
    }

    static Map<String, Object> body(String fid, String notifications, String version,
                                    String channel, String fullScreen, int code, String state, int status) {
        Map<String, Object> update = new LinkedHashMap<>();
        update.put("versionCode", code);
        update.put("state", state);
        if (FAILED.equals(state)) update.put("status", status);
        Map<String, Object> device = new LinkedHashMap<>();
        device.put("fid", fid);
        device.put("notifications", notifications);
        device.put("appVersion", version);
        Map<String, String> ring = new LinkedHashMap<>();
        ring.put("channel", channel);
        ring.put("fullScreen", fullScreen);
        device.put("ring", ring);
        device.put("update", update);
        return device;
    }

    static boolean same(int code, String state, int status, int otherCode, String otherState, int otherStatus) {
        return code == otherCode && state.equals(otherState) && status == otherStatus;
    }

    static void record(Context context, int code, String state, int status) {
        if (code < 1 || code > AppUpdate.MAX_VERSION || PushState.existingInstallId(context) == null) return;
        synchronized (LOCK) {
            SharedPreferences prefs = AppUpdateJob.preferences(context);
            boolean once = WAITING_QUIET.equals(state);
            if (once && prefs.getInt(WAITING_VERSION, 0) == code) return;

            JSONArray queue = queue(prefs);
            JSONObject tail = queue.optJSONObject(queue.length() - 1);
            if (tail == null) tail = json(prefs.getString(REPORTED, null));
            if (tail != null && same(code, state, status,
                    tail.optInt("versionCode"), tail.optString("state"), tail.optInt("status"))) return;

            JSONObject entry = new JSONObject();
            put(entry, "versionCode", code);
            put(entry, "state", state);
            if (FAILED.equals(state)) put(entry, "status", status);
            put(entry, "firstAt", System.currentTimeMillis());
            queue.put(entry);
            SharedPreferences.Editor edit = prefs.edit().putString(PENDING, queue.toString());
            if (once) edit.putInt(WAITING_VERSION, code);
            edit.apply();
            schedule(context, queue, false);
        }
    }

    static boolean waitingForDeviceReport(Context context) {
        synchronized (LOCK) {
            JSONObject head = queue(AppUpdateJob.preferences(context)).optJSONObject(0);
            return head != null && head.optBoolean("signedOut");
        }
    }

    static void wake(Context context) {
        synchronized (LOCK) {
            schedule(context, queue(AppUpdateJob.preferences(context)), false);
        }
    }

    static void deviceReported(Context context) {
        synchronized (LOCK) {
            pageReports++;
            SharedPreferences prefs = AppUpdateJob.preferences(context);
            JSONArray queue = queue(prefs);
            JSONObject head = queue.optJSONObject(0);
            if (head != null && head.optBoolean("signedOut")) {
                head.remove("signedOut");
                head.remove("retryAt");
                put(head, "firstAt", System.currentTimeMillis());
                prefs.edit().putString(PENDING, queue.toString()).apply();
            }
            schedule(context, queue, false);
        }
    }

    private static void schedule(Context context, JSONArray queue, boolean replace) {
        JSONObject head = queue.optJSONObject(0);
        if (running || head == null || head.optBoolean("signedOut")) return;
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler == null || (!replace && scheduler.getPendingJob(JOB_ID) != null)) return;
        long now = System.currentTimeMillis();
        long wait = retryDelay(head.optLong("retryAt"), now);
        JobInfo.Builder job = new JobInfo.Builder(JOB_ID, new ComponentName(context, AppUpdateReport.class))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setBackoffCriteria(RETRY_MS, JobInfo.BACKOFF_POLICY_LINEAR);
        if (wait > 0) {
            // A deadline lets Android reevaluate an isolated retry even if it has nothing to batch it with.
            // Android can ignore the network constraint at a deadline, so deliver() checks it again.
            job.setMinimumLatency(wait).setOverrideDeadline(wait);
        }
        if (!AppUpdateJob.submit(scheduler, job.build())) Log.i(AppUpdateJob.TAG, "update_report unavailable");
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        CancellationSignal cancel = new CancellationSignal();
        if (active != null) active.cancel();
        active = cancel;
        synchronized (LOCK) {
            running = true;
        }
        worker.execute(() -> {
            try {
                deliver(cancel, networkAvailable(params));
            } finally {
                main.post(() -> {
                    if (active != cancel) return;
                    active = null;
                    jobFinished(params, false);
                    synchronized (LOCK) {
                        running = false;
                        schedule(this, queue(AppUpdateJob.preferences(this)), true);
                    }
                });
            }
        });
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        if (active == null) return false;
        active.cancel();
        active = null;
        synchronized (LOCK) {
            running = false;
        }
        return true;
    }

    @Override
    public void onDestroy() {
        if (active != null) {
            active.cancel();
            active = null;
            synchronized (LOCK) {
                running = false;
            }
        }
        worker.shutdownNow();
        super.onDestroy();
    }

    private boolean networkAvailable(JobParameters params) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && params.getNetwork() != null) return true;
        ConnectivityManager manager = getSystemService(ConnectivityManager.class);
        if (manager == null) return false;
        Network active = manager.getActiveNetwork();
        NetworkCapabilities network = active == null ? null : manager.getNetworkCapabilities(active);
        return network != null && network.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private void deliver(CancellationSignal cancel, boolean online) {
        SharedPreferences prefs = AppUpdateJob.preferences(this);
        while (!cancel.isCanceled()) {
            JSONObject entry;
            int reportsBefore;
            long firstAt;
            synchronized (LOCK) {
                JSONArray queue = queue(prefs);
                entry = queue.optJSONObject(0);
                if (entry == null || entry.optBoolean("signedOut")) return;
                long now = System.currentTimeMillis();
                firstAt = Math.min(entry.optLong("firstAt", now), now);
                if (expired(firstAt, now)) {
                    removeHead(prefs, queue, null);
                    Log.i(AppUpdateJob.TAG, "update_report expired");
                    continue;
                }
                if (retryDelay(entry.optLong("retryAt"), now) > 0) return;
                reportsBefore = pageReports;
            }

            Response result = online ? send(entry, cancel) : Response.RETRY;
            synchronized (LOCK) {
                if (cancel.isCanceled()) return;
                JSONArray queue = queue(prefs);
                JSONObject head = queue.optJSONObject(0);
                if (result == Response.SENT || result == Response.DROP) {
                    removeHead(prefs, queue, result == Response.SENT ? head : null);
                    Log.i(AppUpdateJob.TAG, result == Response.SENT ? "update_report sent" : "update_report rejected");
                    continue;
                }
                if (result == Response.SIGN_IN && pageReports != reportsBefore) continue;
                if (result == Response.SIGN_IN) {
                    put(head, "signedOut", true);
                } else {
                    put(head, "firstAt", firstAt);
                    put(head, "retryAt", System.currentTimeMillis() + RETRY_MS);
                }
                prefs.edit().putString(PENDING, queue.toString()).apply();
                Log.i(AppUpdateJob.TAG, result == Response.SIGN_IN ? "update_report signed_out" : "update_report retry");
                return;
            }
        }
    }

    private Response send(JSONObject entry, CancellationSignal cancel) {
        String id = PushState.existingInstallId(this);
        if (id == null) return Response.DROP;
        HttpURLConnection connection = null;
        try {
            String version = PushState.appVersion(this);
            String origin = AppUrls.origin(CapConfig.loadDefault(this).getServerUrl());
            connection = AppUpdateJob.connection(this, "/chat/api/devices/" + id, version, "application/json");
            connection.setRequestMethod("PUT");
            connection.setRequestProperty("Origin", origin);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setDoOutput(true);
            byte[] bytes = new JSONObject(body(PushState.fid(this), PushState.notifications(this), version,
                PushState.ringChannel(this), PushState.fullScreen(this), entry.optInt("versionCode"),
                entry.optString("state"), entry.optInt("status"))).toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            if (cancel.isCanceled()) return Response.RETRY;
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
            return response(connection.getResponseCode());
        } catch (IOException | RuntimeException error) {
            return Response.RETRY;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static void removeHead(SharedPreferences prefs, JSONArray queue, JSONObject sent) {
        queue.remove(0);
        SharedPreferences.Editor edit = prefs.edit();
        if (queue.length() == 0) edit.remove(PENDING);
        else edit.putString(PENDING, queue.toString());
        if (sent != null) {
            sent.remove("firstAt");
            sent.remove("retryAt");
            sent.remove("signedOut");
            edit.putString(REPORTED, sent.toString());
        }
        edit.apply();
    }

    private static JSONArray queue(SharedPreferences prefs) {
        try {
            return new JSONArray(prefs.getString(PENDING, "[]"));
        } catch (JSONException error) {
            return new JSONArray();
        }
    }

    private static JSONObject json(String data) {
        if (data == null) return null;
        try {
            return new JSONObject(data);
        } catch (JSONException error) {
            return null;
        }
    }

    private static void put(JSONObject json, String key, Object value) {
        try {
            json.put(key, value);
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
    }
}
