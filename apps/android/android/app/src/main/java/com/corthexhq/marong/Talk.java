package com.corthexhq.marong;

import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.service.notification.StatusBarNotification;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import com.getcapacitor.Logger;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 선톡, replies, reminders and missed-call notes (docs/app-chat.md SPEC-117 to SPEC-122,
 * docs/app-ring.md SPEC-138). FCM shows them itself while the app is in the background; this
 * shows them the same way while the app is in front, and clears them once the chat is on screen.
 */
final class Talk {

    /** The page a tap opens; FCM puts the message's data values in the tap's extras too. */
    static final String EXTRA_OPEN = "open";

    private static final String TAG = "MarongPush";
    private static final String NOTIFICATION_TAG = "marong_talk";
    private static final AtomicInteger NEXT_ID = new AtomicInteger((int) (System.currentTimeMillis() & 0xffff));

    private Talk() {}

    /** A notification message that arrived while the app was in front (SPEC-121). */
    static void show(Context context, RemoteMessage.Notification message, Map<String, String> data) {
        Channels.ensure(context);
        boolean reminder = Channels.REMINDER.equals(message.getChannelId());
        String title = message.getTitle() != null ? message.getTitle() : context.getString(R.string.app_name);
        String body = message.getBody() != null ? message.getBody() : "";

        Intent open = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        String path = PushLinks.openPath(data.get(EXTRA_OPEN));
        if (path != null) {
            open.putExtra(EXTRA_OPEN, path);
        }
        int id = NEXT_ID.incrementAndGet() & 0x7fffffff;
        PendingIntent tap = PendingIntent.getActivity(context, id, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(context, reminder ? Channels.REMINDER : Channels.TALK)
            .setSmallIcon(R.drawable.ic_stat_marong)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(tap)
            .setAutoCancel(true)
            .setCategory(reminder ? NotificationCompat.CATEGORY_REMINDER : NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(reminder ? NotificationCompat.PRIORITY_HIGH : NotificationCompat.PRIORITY_DEFAULT)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE);
        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_TAG, id, builder.build());
        } catch (SecurityException e) {
            // No notification permission: the message is in the chat when the friend opens it.
            Logger.warn(TAG, "talk_not_shown " + e.getClass().getSimpleName());
        }
    }

    /**
     * The chat is on screen: its messages need no notification any more (SPEC-123). Clears every
     * notification of this app except the call in progress and a ring that is still sounding.
     */
    static void clear(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        try {
            for (StatusBarNotification shown : manager.getActiveNotifications()) {
                if (shown.getTag() == null && (shown.getId() == CallService.NOTIFICATION_ID || shown.getId() == Ring.NOTIFICATION_ID)) {
                    continue;
                }
                manager.cancel(shown.getTag(), shown.getId());
            }
        } catch (RuntimeException e) {
            Logger.warn(TAG, "talk_not_cleared " + e.getClass().getSimpleName());
        }
    }
}
