package com.corthexhq.marong;

import androidx.annotation.NonNull;
import com.getcapacitor.Logger;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;

/**
 * Messages from Marong's server through FCM (docs/app-chat.md SPEC-121, docs/app-ring.md
 * SPEC-132). The server sends to this installation's Firebase installation id (FID).
 */
public class MarongMessagingService extends FirebaseMessagingService {

    private static final String TAG = "MarongPush";

    @Override
    public void onRegistered(@NonNull String installationId) {
        PushState.setFid(this, installationId);
        Logger.info(TAG, "fcm_registered");
        PushEvents.registered();
    }

    @Override
    public void onUnregistered(@NonNull String installationId) {
        PushState.clearFid(this, installationId);
        Logger.info(TAG, "fcm_unregistered");
        PushEvents.registered();
    }

    /** Not used: the server addresses this installation by its FID, never by a token (SPEC-117). */
    @Override
    public void onNewToken(@NonNull String token) {}

    @Override
    public void onMessageReceived(@NonNull RemoteMessage message) {
        Map<String, String> data = message.getData();
        if ("ring".equals(data.get("kind"))) {
            Ring.receive(this, data.get("ringId"), message.getSentTime());
            return;
        }
        RemoteMessage.Notification notification = message.getNotification();
        if (notification == null) {
            return;
        }
        // The app is in front. With the chat on screen the message shows there already (SPEC-121).
        if (PushEvents.chatVisible()) {
            return;
        }
        Talk.show(this, notification, data);
    }
}
