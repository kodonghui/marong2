package com.corthexhq.marong;

import android.app.AlarmManager;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.Build;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.os.OperationCanceledException;
import android.os.SystemClock;
import android.service.notification.StatusBarNotification;
import android.util.Log;
import android.webkit.CookieManager;

import com.getcapacitor.CapConfig;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Fetches, verifies and installs a release outside the UI thread (SPEC-289~295). */
public final class AppUpdateJob extends JobService {
    static final String TAG = "MarongUpdate";
    static final int CHECK_JOB = 2210;
    static final int DAILY_JOB = 2211;
    static final int INSTALL_JOB = 2212;
    private static final int QUIET_INSTALL_JOB = 2213;
    private static final int RING_EXPIRY_JOB = 2214;
    private static final int ALARM_INSTALL_JOB = 2215;
    private static final int FORCED_CHECK_JOB = 2216;
    private static final long DAY_MS = 24L * 60 * 60 * 1000;
    private static final long DEFER_MS = 14 * 60_000L;
    private static final long BACKOFF_MS = 15 * 60_000L;
    private static final long FIRST_ALARM_MS = 2 * 60_000L;
    private static final long NEXT_ALARM_MS = 5 * 60_000L;
    private static final int ALARM_FLAGS = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_ONE_SHOT;
    private static final int BUFFER_SIZE = 65536;
    static final Object STATE_LOCK = new Object();
    private static final ScheduledExecutorService RETRIES = Executors.newSingleThreadScheduledExecutor();

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Map<Integer, CancellationSignal> active = new HashMap<>();

    static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("marong_update", Context.MODE_PRIVATE);
    }

    static void check(Context context) {
        schedule(context, DAILY_JOB, false);
        schedule(context, CHECK_JOB, false);
        AppUpdateReport.wake(context);
    }

    static void checkFromPush(Context context, String value) {
        int offered = AppUpdate.pushVersion(value);
        if (offered == 0) {
            Log.i(TAG, "update_push bad");
            return;
        }
        long installed = installed(context);
        synchronized (STATE_LOCK) {
            SharedPreferences prefs = preferences(context);
            long now = System.currentTimeMillis();
            if (AppUpdate.shouldForce(offered, installed, prefs.getLong("forcedAt", 0), now)) {
                prefs.edit().putLong("forcedAt", now).apply();
                schedule(context, DAILY_JOB, false);
                scheduleForcedCheck(context);
                AppUpdateReport.wake(context);
                return;
            }
        }
        Log.i(TAG, "update_push ordinary");
        check(context);
    }

    private static void scheduleForcedCheck(Context context) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler == null) return;
        if (scheduler.getPendingJob(FORCED_CHECK_JOB) != null) return;
        JobInfo.Builder builder = new JobInfo.Builder(FORCED_CHECK_JOB, new ComponentName(context, AppUpdateJob.class))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (submit(scheduler, builder.setExpedited(true).build())) {
                Log.i(TAG, "update_push expedited");
                return;
            }
            builder.setExpedited(false);
        }
        Log.i(TAG, submit(scheduler, builder.build()) ? "update_push fallback" : "update_push unavailable");
    }

    static void rearm(Context context) {
        schedule(context, DAILY_JOB, true);
    }

    static void retryWhenQuiet(Context source) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return;
        Context context = source.getApplicationContext();
        RETRIES.execute(() -> {
            if (!hasStagedInstall(context) || scheduleQuietInstall(context)) return;
            // The window and notification state can change after the lifecycle callback returns.
            RETRIES.schedule(() -> {
                if (hasStagedInstall(context)) scheduleQuietInstall(context);
            }, 900, TimeUnit.MILLISECONDS);
        });
    }

    private static boolean scheduleQuietInstall(Context context) {
        if (!quiet(context)) return false;
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler == null) return false;
        if (scheduler.getPendingJob(QUIET_INSTALL_JOB) != null) return true;
        boolean scheduled = scheduleInstallTrigger(context, scheduler, QUIET_INSTALL_JOB, false);
        Log.i(TAG, scheduled ? "update_install expedited_scheduled" : "update_install expedited_unavailable");
        return scheduled;
    }

    private static boolean hasStagedInstall(Context context) {
        SharedPreferences prefs = preferences(context);
        Candidate cached = candidate(prefs);
        if (cached == null || !apk(context, cached.release.code).isFile()) return false;
        boolean permissionGranted = cached.permissionBlocked && !installPermissionMissing(context);
        if (cached.permissionBlocked && !permissionGranted
                && prefs.getInt("notified", -1) == cached.release.code) return false;
        return cached.session < 0 || permissionGranted
            || context.getPackageManager().getPackageInstaller().getSessionInfo(cached.session) == null;
    }

    private static boolean scheduleInstallTrigger(Context context, JobScheduler scheduler, int id, boolean allowOrdinary) {
        ComponentName service = new ComponentName(context, AppUpdateJob.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
                && submit(scheduler, new JobInfo.Builder(id, service).setExpedited(true).build())) return true;
        return allowOrdinary && submit(scheduler, new JobInfo.Builder(id, service).build());
    }

    static boolean submit(JobScheduler scheduler, JobInfo job) {
        try {
            return scheduler.schedule(job) == JobScheduler.RESULT_SUCCESS;
        } catch (IllegalStateException | SecurityException error) {
            return false;
        }
    }

    static void backupAlarmFired(Context context, Runnable completion) {
        RETRIES.execute(() -> {
            try {
                // A window check may need the main thread, so take it before locking candidate state.
                boolean ready = quiet(context);
                synchronized (STATE_LOCK) {
                    if (!hasStagedInstall(context)) return;
                    Log.i(TAG, "update_install alarm_fired");
                    // The process can be reclaimed as soon as the app stops being busy.
                    armBackupAlarmLocked(context, ready ? NEXT_ALARM_MS : FIRST_ALARM_MS);
                    if (!ready) {
                        Log.i(TAG, "update_install alarm_busy");
                        return;
                    }
                    JobScheduler scheduler = context.getSystemService(JobScheduler.class);
                    if (scheduler == null || scheduler.getPendingJob(ALARM_INSTALL_JOB) != null) return;
                    if (!scheduleInstallTrigger(context, scheduler, ALARM_INSTALL_JOB, true)) {
                        Log.i(TAG, "update_install alarm_job_unavailable");
                    }
                }
            } finally {
                completion.run();
            }
        });
    }

    private static PendingIntent backupIntent(Context context, int flags) {
        Intent intent = new Intent(context, AppUpdateReceiver.class).setAction(AppUpdateReceiver.RETRY);
        return PendingIntent.getBroadcast(context, 0, intent, ALARM_FLAGS | flags);
    }

    private static void armBackupAlarm(Context context, long delay) {
        synchronized (STATE_LOCK) {
            if (hasStagedInstall(context)) armBackupAlarmLocked(context, delay);
        }
    }

    private static void armBackupAlarmLocked(Context context, long delay) {
        AlarmManager alarms = context.getSystemService(AlarmManager.class);
        if (alarms == null || backupIntent(context, PendingIntent.FLAG_NO_CREATE) != null) return;
        PendingIntent pending = backupIntent(context, 0);
        try {
            alarms.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + delay, pending);
            Log.i(TAG, "update_install alarm_armed delay_ms=" + delay);
        } catch (SecurityException error) {
            pending.cancel();
            Log.i(TAG, "update_install alarm_unavailable");
        }
    }

    static void cancelBackupAlarm(Context context) {
        PendingIntent pending = backupIntent(context, PendingIntent.FLAG_NO_CREATE);
        if (pending == null) return;
        AlarmManager alarms = context.getSystemService(AlarmManager.class);
        if (alarms != null) alarms.cancel(pending);
        pending.cancel();
    }

    static void observeRingExpiry(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return;
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler == null) return;
        // Android expires the alert itself and does not send its dismissal intent.
        JobInfo job = new JobInfo.Builder(RING_EXPIRY_JOB, new ComponentName(context, AppUpdateJob.class))
            .setMinimumLatency(Ring.RING_MS + 1200)
            .setOverrideDeadline(Ring.RING_MS + 5000)
            .build();
        scheduler.schedule(job);
    }

    static boolean installPermissionMissing(Context context) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            && !context.getPackageManager().canRequestPackageInstalls();
    }

    private static void schedule(Context context, int job, boolean replace) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler == null || (!replace && scheduler.getPendingJob(job) != null)) return;
        JobInfo.Builder builder = new JobInfo.Builder(job, new ComponentName(context, AppUpdateJob.class));
        if (job == INSTALL_JOB) {
            builder.setMinimumLatency(DEFER_MS);
            builder.setOverrideDeadline(DEFER_MS);
            builder.setBackoffCriteria(BACKOFF_MS, JobInfo.BACKOFF_POLICY_LINEAR);
        } else builder.setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY);
        if (job == DAILY_JOB) builder.setPeriodic(DAY_MS);
        if (!submit(scheduler, builder.build())) {
            Log.i(TAG, job == INSTALL_JOB ? "update_install backup_unavailable" : "update_check scheduling_failed");
        } else if (job == INSTALL_JOB) {
            Log.i(TAG, "update_install backup_scheduled");
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        int job = params.getJobId();
        if (job == RING_EXPIRY_JOB) {
            retryWhenQuiet(this);
            return false;
        }
        CancellationSignal cancel = new CancellationSignal();
        CancellationSignal previous = active.put(job, cancel);
        if (previous != null) previous.cancel();
        executor.execute(() -> {
            boolean defer = false;
            try {
                if (installOnly(job)) Log.i(TAG, "update_install started job=" + job);
                defer = update(job, cancel);
                if (defer) {
                    cancel.throwIfCanceled();
                    armBackupAlarm(this, FIRST_ALARM_MS);
                }
            } catch (OperationCanceledException ignored) {
                // onStopJob decides whether JobScheduler should retry.
            } catch (Exception error) {
                Log.i(TAG, "update_check unavailable");
            } finally {
                boolean retryInstall = defer;
                main.post(() -> {
                    if (active.get(job) != cancel) return;
                    active.remove(job);
                    jobFinished(params, false);
                    if (retryInstall) RETRIES.execute(() -> {
                        if (!hasStagedInstall(this)) return;
                        schedule(this, INSTALL_JOB, job == INSTALL_JOB);
                        // The last activity may have stopped before the backup triggers were armed.
                        if (job != QUIET_INSTALL_JOB && job != ALARM_INSTALL_JOB) retryWhenQuiet(this);
                    });
                });
            }
        });
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        int job = params.getJobId();
        CancellationSignal cancel = active.remove(job);
        if (cancel == null) return false;
        cancel.cancel();
        if (job != INSTALL_JOB) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            int reason = params.getStopReason();
            if (reason == JobParameters.STOP_REASON_USER || reason == JobParameters.STOP_REASON_CANCELLED_BY_APP) {
                return false;
            }
        }
        Log.i(TAG, "update_install interrupted retry");
        return true;
    }

    @Override
    public void onDestroy() {
        for (CancellationSignal cancel : active.values()) cancel.cancel();
        active.clear();
        executor.shutdownNow();
        super.onDestroy();
    }

    private static boolean installOnly(int job) {
        return job == INSTALL_JOB || job == QUIET_INSTALL_JOB || job == ALARM_INSTALL_JOB;
    }

    private boolean update(int job, CancellationSignal cancel) throws IOException, PackageManager.NameNotFoundException {
        cancel.throwIfCanceled();
        PackageManager manager = getPackageManager();
        PackageInfo own = manager.getPackageInfo(getPackageName(), signatureFlags());
        long installed = version(own);
        SharedPreferences prefs = preferences(this);
        Candidate cached = candidate(prefs);
        AppUpdate.Release release = cached == null ? null : cached.release;
        long now = System.currentTimeMillis();

        boolean installOnly = installOnly(job);
        if (!installOnly && (job == FORCED_CHECK_JOB || AppUpdate.shouldCheck(prefs.getLong("checkedAt", 0), now))) {
            CheckResponse response = ask(own.versionName, cancel);
            if (response.kind == AppUpdate.Check.SIGNED_OUT || response.kind == AppUpdate.Check.RETRY) return false;
            prefs.edit().putLong("checkedAt", System.currentTimeMillis()).apply();
            release = response.release;
            if (release == null || release.code <= installed) {
                discard(this, prefs, cached, -1);
                return false;
            }
            clearOlderFailures(prefs, release.code - 1);
        }

        if (release == null || !AppUpdate.eligible(release.code, installed, failures(prefs, release.code))) return false;
        if (installOnly && !quiet(this)) {
            Log.i(TAG, "update_install deferred_before_verify job=" + job);
            AppUpdateReport.record(this, release.code, AppUpdateReport.WAITING_QUIET, 0);
            return true;
        }
        File apk = apk(this, release.code);
        if (cached == null || !cached.release.sameAs(release)) {
            discard(this, prefs, cached, release.code);
            if (installOnly) return false;
            if (!apk.isFile()) {
                try {
                    download(release, own.versionName, cancel);
                } catch (IOException error) {
                    cancel.throwIfCanceled();
                    Log.i(TAG, "update_download fail code=" + release.code);
                    fail(this, prefs, release.code, error instanceof SizeLimit ? 102 : 101);
                    return false;
                }
            }
            cached = new Candidate(release, -1, false, false);
        }
        cancel.throwIfCanceled();
        int check;
        try {
            check = verify(manager, own, release, apk, cancel);
        } catch (IOException error) {
            check = 1;
        }
        if (check != 0) {
            cancel.throwIfCanceled();
            Log.i(TAG, "update_verify fail=" + check + " code=" + release.code);
            fail(this, prefs, release.code, 110 + check);
            return false;
        }

        synchronized (STATE_LOCK) {
            cancel.throwIfCanceled();
            Candidate latest = candidate(prefs);
            if (cached.session >= 0 && (latest == null || latest.session != cached.session)) {
                // The receiver finished while the file was being checked.
                return false;
            }
            if (latest != null && latest.release.sameAs(release)) {
                cached = latest;
            } else if (!candidateEdit(prefs, cached).commit()) {
                Log.i(TAG, "update_install candidate_unavailable");
                return false;
            } else {
                AppUpdateReport.record(this, release.code, AppUpdateReport.DOWNLOADED, 0);
            }
        }
        if (cached.permissionBlocked && installPermissionMissing(this)
                && prefs.getInt("notified", -1) == release.code) return false;
        if (!installOnly && !quiet(this)) {
            Log.i(TAG, "update_install deferred code=" + release.code);
            AppUpdateReport.record(this, release.code, AppUpdateReport.WAITING_QUIET, 0);
            return true;
        }
        return install(cached, apk, cancel);
    }

    private static final class CheckResponse {
        final AppUpdate.Check kind;
        final AppUpdate.Release release;
        CheckResponse(AppUpdate.Check kind, AppUpdate.Release release) {
            this.kind = kind;
            this.release = release;
        }
    }

    private CheckResponse ask(String versionName, CancellationSignal cancel) throws IOException {
        HttpURLConnection connection = connection(this, AppUpdate.RELEASE_PATH, versionName, "application/json");
        try {
            AppUpdate.Check kind = AppUpdate.check(connection.getResponseCode());
            cancel.throwIfCanceled();
            if (kind == AppUpdate.Check.SIGNED_OUT) Log.i(TAG, "update_check signed_out");
            if (kind != AppUpdate.Check.RELEASE) return new CheckResponse(kind, null);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream input = connection.getInputStream()) {
                transfer(input, bytes, 16384, cancel);
            } catch (SizeLimit error) {
                return new CheckResponse(kind, null);
            }
            return new CheckResponse(kind, parse(bytes.toString(StandardCharsets.UTF_8.name())));
        } finally {
            connection.disconnect();
        }
    }

    static HttpURLConnection connection(Context context, String path, String versionName, String accept) throws IOException {
        String serverUrl = CapConfig.loadDefault(context).getServerUrl();
        if (serverUrl == null) throw new IOException("Missing app URL");
        URL url = new URL(AppUrls.origin(serverUrl) + path);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setUseCaches(false);
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("User-Agent", "MarongApp/" + versionName);
        connection.setRequestProperty("Accept", accept);
        String cookie = CookieManager.getInstance().getCookie(url.toString());
        if (cookie != null && !cookie.isEmpty()) connection.setRequestProperty("Cookie", cookie);
        return connection;
    }

    private void download(AppUpdate.Release release, String versionName, CancellationSignal cancel) throws IOException {
        File target = apk(this, release.code);
        File folder = target.getParentFile();
        if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Update cache");
        clean(this, release.code);
        File part = new File(target.getPath() + ".part");
        HttpURLConnection connection = connection(this, release.url, versionName, "application/vnd.android.package-archive");
        try {
            if (connection.getResponseCode() != 200) throw new IOException("APK unavailable");
            long size;
            try (InputStream input = connection.getInputStream(); OutputStream output = new FileOutputStream(part)) {
                size = transfer(input, output, release.size, cancel);
            }
            cancel.throwIfCanceled();
            if (size != release.size || !part.renameTo(target)) throw new IOException("Incomplete APK");
        } finally {
            connection.disconnect();
            remove(part);
        }
    }

    private static final class SizeLimit extends IOException {}

    private static long transfer(InputStream input, OutputStream output, long limit, CancellationSignal cancel)
            throws IOException {
        long bytes = 0;
        byte[] buffer = new byte[BUFFER_SIZE];
        for (int read; (read = input.read(buffer)) != -1;) {
            cancel.throwIfCanceled();
            bytes += read;
            if (bytes > limit) throw new SizeLimit();
            output.write(buffer, 0, read);
        }
        return bytes;
    }

    private static boolean quiet(Context context) {
        if (CallControl.isActive() || CallService.isRunning() || Ring.alertInProgress()) return false;
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) return false;
        boolean calling = false;
        boolean ringing = false;
        for (StatusBarNotification notification : manager.getActiveNotifications()) {
            calling |= notification.getId() == CallService.NOTIFICATION_ID;
            ringing |= notification.getId() == Ring.NOTIFICATION_ID;
        }
        return AppUpdate.quiet(calling, ringing, AppUpdateWindows.visible(context));
    }

    private enum Commit { SUBMITTED, DEFERRED, STALE }

    private Commit commitOnMain(SharedPreferences prefs, AppUpdate.Release release, PackageInstaller.Session session,
                                int sessionId, PendingIntent callback, CancellationSignal cancel) {
        CompletableFuture<Commit> result = new CompletableFuture<>();
        if (!main.post(() -> {
            try {
                synchronized (STATE_LOCK) {
                    cancel.throwIfCanceled();
                    Candidate latest = candidate(prefs);
                    if (latest == null || !latest.release.sameAs(release)) {
                        result.complete(Commit.STALE);
                    } else if (!quiet(this)) {
                        result.complete(Commit.DEFERRED);
                    } else {
                        // Activity and call-service callbacks cannot interleave on the main thread.
                        // The worker retains the open session until this decision is complete.
                        save(prefs, new Candidate(release, sessionId, false, false));
                        session.commit(callback.getIntentSender());
                        result.complete(Commit.SUBMITTED);
                    }
                }
            } catch (RuntimeException error) {
                result.completeExceptionally(error);
            }
        })) return Commit.DEFERRED;
        try {
            return result.join();
        } catch (CompletionException error) {
            if (error.getCause() instanceof RuntimeException) throw (RuntimeException) error.getCause();
            throw error;
        }
    }

    private boolean install(Candidate candidate, File apk, CancellationSignal cancel) {
        AppUpdate.Release release = candidate.release;
        SharedPreferences prefs = preferences(this);
        PackageInstaller installer = getPackageManager().getPackageInstaller();
        int sessionId = -1;
        boolean committed = false;
        try {
            synchronized (STATE_LOCK) {
                Candidate latest = candidate(prefs);
                if (latest == null || !latest.release.sameAs(release)) return false;
                boolean permissionGranted = latest.permissionBlocked && !installPermissionMissing(this);
                if (latest.session >= 0 && installer.getSessionInfo(latest.session) != null) {
                    // An ordinary pending confirmation still owns its install session.
                    if (!permissionGranted && (!latest.waitingForUser
                            || prefs.getInt("notified", -1) == release.code)) return false;
                    save(prefs, new Candidate(release, -1, false, false));
                    try {
                        installer.abandonSession(latest.session);
                    } catch (IllegalStateException alreadyClosed) {
                        // Android can close the old permission-gated session from Settings.
                    }
                }
                if (permissionGranted) AppUpdateReceiver.cancelNotification(this);
            }
            cancel.throwIfCanceled();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(getPackageName());
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            }
            sessionId = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(sessionId)) {
                try (InputStream input = new FileInputStream(apk);
                     OutputStream output = session.openWrite("base.apk", 0, release.size)) {
                    if (transfer(input, output, release.size, cancel) != release.size) throw new IOException("APK changed");
                    session.fsync(output);
                }
                Intent result = new Intent(this, AppUpdateReceiver.class)
                    .setAction(AppUpdateReceiver.RESULT)
                    .putExtra(AppUpdateReceiver.VERSION, release.code)
                    .putExtra(AppUpdateReceiver.SESSION, sessionId);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent callback = PendingIntent.getBroadcast(this, sessionId, result, flags);
                Commit outcome = commitOnMain(prefs, release, session, sessionId, callback, cancel);
                if (outcome != Commit.SUBMITTED) {
                    callback.cancel();
                    if (outcome == Commit.DEFERRED) {
                        Log.i(TAG, "update_install deferred_before_commit");
                        AppUpdateReport.record(this, release.code, AppUpdateReport.WAITING_QUIET, 0);
                    }
                    return outcome == Commit.DEFERRED;
                }
                committed = true;
                cancelBackupAlarm(this);
                Log.i(TAG, "update_install committed code=" + release.code);
            }
        } catch (IOException | RuntimeException error) {
            if (error instanceof OperationCanceledException) throw (OperationCanceledException) error;
            Log.i(TAG, "update_install fail=session code=" + release.code);
            fail(this, prefs, release.code, 121);
        } finally {
            if (sessionId >= 0 && !committed) {
                try {
                    installer.abandonSession(sessionId);
                } catch (RuntimeException ignored) {
                    // The installer may already have discarded it.
                }
            }
        }
        return false;
    }

    private static int verify(PackageManager manager, PackageInfo own, AppUpdate.Release release, File apk,
                              CancellationSignal cancel) throws IOException {
        long size = apk.length();
        if (size != release.size) return 1;
        MessageDigest hash = sha256();
        try (InputStream input = new FileInputStream(apk)) {
            byte[] buffer = new byte[BUFFER_SIZE];
            for (int read; (read = input.read(buffer)) != -1;) {
                cancel.throwIfCanceled();
                hash.update(buffer, 0, read);
            }
        }
        cancel.throwIfCanceled();
        String digest = hex(hash.digest());
        if (!release.sha256.equals(digest)) return 2;
        PackageInfo archive = manager.getPackageArchiveInfo(apk.getPath(), signatureFlags());
        return AppUpdate.verify(release, size, digest, archive == null ? null : archive.packageName, own.packageName,
            archive == null ? -1 : version(archive), version(own), keys(archive), keys(own));
    }

    @SuppressWarnings("deprecation")
    private static long version(PackageInfo info) {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P ? info.getLongVersionCode() : info.versionCode;
    }

    @SuppressWarnings("deprecation")
    private static int signatureFlags() {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.P ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
    }

    @SuppressWarnings("deprecation")
    private static Set<String> keys(PackageInfo info) {
        Set<String> keys = new HashSet<>();
        if (info == null) return keys;
        Signature[] signatures = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            ? (info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners()) : info.signatures;
        if (signatures != null) {
            for (Signature signature : signatures) keys.add(hex(sha256().digest(signature.toByteArray())));
        }
        return keys;
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException(error);
        }
    }

    private static String hex(byte[] bytes) {
        final String digits = "0123456789abcdef";
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            result.append(digits.charAt((value & 0xff) >>> 4)).append(digits.charAt(value & 0xf));
        }
        return result.toString();
    }

    static final class Candidate {
        final AppUpdate.Release release;
        final int session;
        final boolean waitingForUser;
        final boolean permissionBlocked;
        Candidate(AppUpdate.Release release, int session, boolean waitingForUser, boolean permissionBlocked) {
            this.release = release;
            this.session = session;
            this.waitingForUser = waitingForUser;
            this.permissionBlocked = permissionBlocked;
        }
    }

    private static AppUpdate.Release parse(String text) {
        try {
            return parse(new JSONObject(text));
        } catch (JSONException error) {
            return null;
        }
    }

    private static AppUpdate.Release parse(JSONObject data) {
        return AppUpdate.release(data.opt("versionCode"), data.opt("versionName"), data.opt("size"),
            data.opt("sha256"), data.opt("url"));
    }

    static Candidate candidate(SharedPreferences prefs) {
        String saved = prefs.getString("release", null);
        if (saved == null) return null;
        try {
            JSONObject data = new JSONObject(saved);
            AppUpdate.Release release = parse(data);
            return release == null ? null : new Candidate(release, data.optInt("session", -1),
                data.optBoolean("waitingForUser"), data.optBoolean("permissionBlocked"));
        } catch (JSONException error) {
            return null;
        }
    }

    static void save(SharedPreferences prefs, Candidate candidate) {
        candidateEdit(prefs, candidate).apply();
    }

    private static SharedPreferences.Editor candidateEdit(SharedPreferences prefs, Candidate candidate) {
        AppUpdate.Release release = candidate.release;
        try {
            JSONObject data = new JSONObject()
                .put("versionCode", release.code).put("versionName", release.name).put("size", release.size)
                .put("sha256", release.sha256).put("url", release.url).put("session", candidate.session)
                .put("waitingForUser", candidate.waitingForUser).put("permissionBlocked", candidate.permissionBlocked);
            return prefs.edit().putString("release", data.toString());
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
    }

    private static int failures(SharedPreferences prefs, int version) {
        return prefs.getInt("fail." + version, 0);
    }

    static void clearOlderFailures(SharedPreferences prefs, long through) {
        SharedPreferences.Editor edit = prefs.edit();
        for (String key : prefs.getAll().keySet()) {
            if (key.matches("fail\\.[0-9]{1,10}") && Long.parseLong(key.substring(5)) <= through) edit.remove(key);
        }
        edit.apply();
    }

    static void fail(Context context, SharedPreferences prefs, int version, int status) {
        synchronized (STATE_LOCK) {
            cancelBackupAlarm(context);
            clean(context, -1);
            prefs.edit().remove("release").putInt("fail." + version, AppUpdate.afterFailure(failures(prefs, version))).apply();
            AppUpdateReport.record(context, version, AppUpdateReport.FAILED, status);
        }
    }

    private static void discard(Context context, SharedPreferences prefs, Candidate candidate, int keep) {
        synchronized (STATE_LOCK) {
            cancelBackupAlarm(context);
            prefs.edit().remove("release").apply();
            clean(context, keep);
            if (candidate == null || candidate.session < 0) return;
            PackageInstaller installer = context.getPackageManager().getPackageInstaller();
            if (installer.getSessionInfo(candidate.session) != null) {
                try {
                    installer.abandonSession(candidate.session);
                } catch (RuntimeException ignored) {
                    // The old installer session may have just finished.
                }
            }
        }
    }

    static long installed(Context context) {
        try {
            return version(context.getPackageManager().getPackageInfo(context.getPackageName(), 0));
        } catch (PackageManager.NameNotFoundException error) {
            return 0;
        }
    }

    private static File apk(Context context, int code) {
        return new File(new File(context.getCacheDir(), "update"), "marong-" + code + ".apk");
    }

    static void clean(Context context, int keep) {
        File[] cached = new File(context.getCacheDir(), "update").listFiles();
        if (cached == null) return;
        for (File file : cached) {
            if (file.getName().matches("marong-[0-9]{1,10}\\.apk(?:\\.part)?") && !file.equals(apk(context, keep))) {
                remove(file);
            }
        }
    }

    private static void remove(File file) {
        if (file.exists() && !file.delete()) Log.i(TAG, "update_cache cleanup_failed");
    }
}
