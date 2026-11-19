package com.corthexhq.marong;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Bundle;
import android.service.notification.StatusBarNotification;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.app.Person;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.drawable.IconCompat;
import com.getcapacitor.Logger;

/**
 * Marong's own call ringing on this phone (docs/app-ring.md SPEC-132 to SPEC-134): a call-style
 * notification with the phone's ringtone, a full-screen ring screen when the phone is locked or
 * asleep, 받기 that opens the call page with the ring and 거절 that only stops the ring. From 0.2.2 a
 * hello call (reason "hello", docs/04-functional-spec/call-first.md SPEC-267) says '마롱이가 먼저
 * 걸었어요' and its preview line instead of '약속한 전화예요'.
 */
final class Ring {

    static final String ACTION_ANSWER = "com.corthexhq.marong.action.ANSWER_RING";
    static final String EXTRA_RING_ID = "ringId";
    static final String EXTRA_SHOWN_AT = "shownAt";
    static final String EXTRA_REASON = "reason";
    static final String EXTRA_LINE = "line";
    static final String EXTRA_NAME = "botName";
    /** How long the phone rings; the server's answer window is 5 minutes. */
    static final long RING_MS = 45_000L;

    private static final String TAG = "MarongRing";
    static final int NOTIFICATION_ID = 201;

    private Ring() {}

    /** A ring message from FCM (data only: kind "ring", ringId, v, reason, line). Returns quickly (SPEC-132). */
    static void receive(Context context, String ringId, long sentTimeMs, String reason, String line, String name) {
        if (!PushLinks.isRingId(ringId)) {
            Logger.info(TAG, "ring_dropped reason=bad_id");
            return;
        }
        if (!PushLinks.isFresh(sentTimeMs, System.currentTimeMillis())) {
            Logger.info(TAG, "ring_dropped reason=old");
            return;
        }
        if (!PushState.firstRing(context, ringId, System.currentTimeMillis())) {
            Logger.info(TAG, "ring_dropped reason=repeat");
            return;
        }
        if (CallControl.isActive() || phoneInCall(context)) {
            Logger.info(TAG, "ring_dropped reason=in_call");
            return;
        }
        String kind = PushLinks.isHello(reason) ? "hello" : "promise";
        String shownName = name == null || name.trim().isEmpty() || name.length() > 24
            ? context.getString(R.string.ring_caller) : name.trim();
        show(context, ringId, kind, PushLinks.ringLine(kind, line), shownName);
    }

    /** The phone or another app is in a call (SPEC-132). */
    private static boolean phoneInCall(Context context) {
        AudioManager audio = context.getSystemService(AudioManager.class);
        if (audio == null) {
            return false;
        }
        int mode = audio.getMode();
        return mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION;
    }

    private static void show(Context context, String ringId, String reason, String line, String name) {
        Channels.ensure(context);
        long shownAt = System.currentTimeMillis();
        int code = ringId.hashCode();
        int immutable = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;

        PendingIntent answer = PendingIntent.getActivity(context, code, answerIntent(context, ringId), immutable);
        PendingIntent decline = PendingIntent.getBroadcast(
            context,
            code,
            new Intent(context, RingDeclineReceiver.class).putExtra(EXTRA_RING_ID, ringId),
            immutable
        );
        Intent screen = new Intent(context, RingActivity.class)
            .putExtra(EXTRA_RING_ID, ringId)
            .putExtra(EXTRA_SHOWN_AT, shownAt)
            .putExtra(EXTRA_REASON, reason)
            .putExtra(EXTRA_LINE, line)
            .putExtra(EXTRA_NAME, name)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_USER_ACTION);
        PendingIntent fullScreen = PendingIntent.getActivity(context, code, screen, immutable);

        Person marong = new Person.Builder()
            .setName(name)
            .setIcon(IconCompat.createWithResource(context, R.drawable.splash_face))
            .setImportant(true)
            .build();
        Bundle extras = new Bundle();
        extras.putString(EXTRA_RING_ID, ringId);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, Channels.RING)
            .setSmallIcon(R.drawable.ic_stat_marong)
            .setColor(ContextCompat.getColor(context, R.color.marong_accent))
            .setContentText(
                PushLinks.ringText(reason, line, context.getString(R.string.ring_text), context.getString(R.string.ring_hello_named, name))
            )
            .setStyle(NotificationCompat.CallStyle.forIncomingCall(marong, decline, answer))
            .addPerson(marong)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setFullScreenIntent(fullScreen, true)
            .setContentIntent(fullScreen)
            .setOngoing(true)
            .setAutoCancel(false)
            .setOnlyAlertOnce(true)
            .setTimeoutAfter(RING_MS)
            .addExtras(extras);
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            // Before Android 8 the sound and vibration come from the notification, not the channel.
            builder
                .setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE), AudioManager.STREAM_RING)
                .setVibrate(Channels.RING_VIBRATION);
        }
        Notification notification = builder.build();
        notification.flags |= Notification.FLAG_INSISTENT; // the ringtone repeats until answered or stopped

        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification);
            AppUpdateJob.observeRingExpiry(context);
            Logger.info(TAG, "ring_shown reason=" + reason);
        } catch (SecurityException | IllegalArgumentException e) {
            // No notification permission, or Android refused the call style: the server's
            // missed-call note follows after the answer window.
            Logger.warn(TAG, "ring_not_shown " + e.getClass().getSimpleName());
        }
    }

    /** Opens the call page with this ring (SPEC-134). */
    static Intent answerIntent(Context context, String ringId) {
        return new Intent(context, MainActivity.class)
            .setAction(ACTION_ANSWER)
            .putExtra(EXTRA_RING_ID, ringId)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
    }

    /** True while the ring notification for this id is still up. */
    static boolean isRinging(Context context, String ringId) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || ringId == null) {
            return false;
        }
        for (StatusBarNotification shown : manager.getActiveNotifications()) {
            if (shown.getId() == NOTIFICATION_ID && ringId.equals(shown.getNotification().extras.getString(EXTRA_RING_ID))) {
                return true;
            }
        }
        return false;
    }

    /** Stops the ring: answered, declined, or a call started (SPEC-132, SPEC-133). */
    static void cancel(Context context) {
        NotificationManagerCompat.from(context).cancel(NOTIFICATION_ID);
        AppUpdateJob.retryWhenQuiet(context);
        RingActivity.closeShown();
    }
}
