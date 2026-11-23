package com.corthexhq.marong;

import android.app.Application;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import com.google.firebase.messaging.RemoteMessage;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import org.json.JSONException;
import org.json.JSONObject;

/** Android 16 fixture APKs only. The local fake FCM site delivers the envelope over HTTP. */
public final class FixtureFcmApp extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        final Handler main = new Handler(Looper.getMainLooper());
        Thread receiver = new Thread(() -> receive(main), "fixture-fcm");
        receiver.setDaemon(true);
        receiver.start();
    }

    private void receive(Handler main) {
        final long code;
        try {
            PackageInfo own = getPackageManager().getPackageInfo(getPackageName(), 0);
            code = own.getLongVersionCode();
        } catch (android.content.pm.PackageManager.NameNotFoundException failure) {
            throw new IllegalStateException(failure);
        }
        for (;;) {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL("http://127.0.0.1:18788/inbox/" + code).openConnection();
                connection.setConnectTimeout(1200);
                connection.setReadTimeout(1200);
                if (connection.getResponseCode() == 200) {
                    try (BufferedReader source = new BufferedReader(new InputStreamReader(
                            connection.getInputStream(), StandardCharsets.UTF_8))) {
                        JSONObject message = new JSONObject(source.readLine());
                        main.post(() -> deliver(message));
                    }
                }
            } catch (IOException | JSONException ignored) {
                // The fake site may be offline during another emulator test.
            } finally {
                if (connection != null) connection.disconnect();
            }
            SystemClock.sleep(350L);
        }
    }

    private void deliver(JSONObject message) {
        Bundle payload = new Bundle();
        JSONObject data = message.optJSONObject("data");
        if (data != null) for (Iterator<String> keys = data.keys(); keys.hasNext();) {
            String key = keys.next();
            payload.putString(key, data.optString(key));
        }
        JSONObject notification = message.optJSONObject("notification");
        if (notification != null) {
            payload.putString("gcm.n.e", "1");
            payload.putString("gcm.n.title", notification.optString("title"));
            payload.putString("gcm.n.body", notification.optString("body"));
        }
        RemoteMessage incoming = new RemoteMessage(payload);
        new FixtureMessaging(this).onMessageReceived(incoming);
        Log.i("FixtureFcm", "callback kind=" + incoming.getData().get("kind") +
            " notification=" + (incoming.getNotification() != null));
    }

    private static final class FixtureMessaging extends MarongMessagingService {
        FixtureMessaging(Context context) {
            attachBaseContext(context);
        }
    }
}
