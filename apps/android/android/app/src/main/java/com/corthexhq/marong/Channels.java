package com.corthexhq.marong;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.os.Build;

/**
 * The notification channels for Marong's messages and calls (docs/app-chat.md SPEC-121,
 * docs/app-ring.md SPEC-132). The friend can turn each one off in Android's settings.
 */
final class Channels {

    /** 선톡 and replies: sound, no heads-up. */
    static final String TALK = "marong_talk";
    /** Reminders the friend asked for: heads-up. */
    static final String REMINDER = "marong_reminder";
    /** Marong's own call: the phone's ringtone as a call. */
    static final String RING = "marong_ring";
    static final String UPDATE = "marong_update";

    static final long[] RING_VIBRATION = { 0, 800, 800 };

    private Channels() {}

    /** Creating a channel that exists only refreshes its name and description. */
    static void ensure(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel talk = new NotificationChannel(
            TALK,
            context.getString(R.string.talk_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT
        );
        talk.setDescription(context.getString(R.string.talk_channel_description));
        talk.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);

        NotificationChannel reminder = new NotificationChannel(
            REMINDER,
            context.getString(R.string.reminder_channel_name),
            NotificationManager.IMPORTANCE_HIGH
        );
        reminder.setDescription(context.getString(R.string.reminder_channel_description));
        reminder.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);

        NotificationChannel ring = new NotificationChannel(
            RING,
            context.getString(R.string.ring_channel_name),
            NotificationManager.IMPORTANCE_HIGH
        );
        ring.setDescription(context.getString(R.string.ring_channel_description));
        ring.setSound(
            RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
            new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
        );
        ring.enableVibration(true);
        ring.setVibrationPattern(RING_VIBRATION);
        ring.setShowBadge(false);
        // The ring shows only "약속한 전화예요": nothing private on the lock screen (REQ-130).
        ring.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);

        manager.createNotificationChannel(talk);
        manager.createNotificationChannel(reminder);
        manager.createNotificationChannel(ring);
        NotificationChannel update = new NotificationChannel(UPDATE, context.getString(R.string.update_channel_name),
            NotificationManager.IMPORTANCE_LOW);
        update.setDescription(context.getString(R.string.update_channel_description));
        update.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
        manager.createNotificationChannel(update);
    }
}
