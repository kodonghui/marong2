package com.corthexhq.marong;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import androidx.activity.OnBackPressedCallback;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.CapConfig;
import com.getcapacitor.Logger;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/**
 * The chat window (D20, docs/app-chat.md SPEC-143 to SPEC-147): the in-app chat in a window of its
 * own, above the call window in the same task. Opening it never changes the call window's page,
 * so a call goes on under it. It has the chat's app calls (MarongPush) and no call plugin.
 */
public class ChatActivity extends BridgeActivity {

    /** The "can't connect" page comes back to the chat, not to the call page (SPEC-143). */
    private static final String CHAT_ERROR_PATH = "error.html?page=chat";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        registerPlugin(MarongWindowPlugin.class);
        registerPlugin(MarongPushPlugin.class);
        config = chatConfig();
        super.onCreate(savedInstanceState);
        if (config == null) {
            // Never happens with the app's own settings file; without it this window would open the call page.
            finish();
            return;
        }
        // Back closes only this window; the call window under it keeps its call (SPEC-143, REQ-135).
        getOnBackPressedDispatcher()
            .addCallback(
                this,
                new OnBackPressedCallback(true) {
                    @Override
                    public void handleOnBackPressed() {
                        backToCall(ChatActivity.this);
                    }
                }
            );
    }

    /** Opens the chat window above the call window (SPEC-144, SPEC-146). It always starts at /chat/. */
    static void open(Activity from) {
        if (from == null || from.isFinishing()) {
            return;
        }
        from.startActivity(new Intent(from, ChatActivity.class));
    }

    /**
     * Closes the chat window, so the call window under it shows again as it was, its call going on
     * (REQ-135). Should the chat window be the task's only window, the call window opens first.
     */
    static void backToCall(Activity chat) {
        if (chat == null || chat.isFinishing()) {
            return;
        }
        if (chat.isTaskRoot()) {
            chat.startActivity(new Intent(chat, MainActivity.class));
        }
        chat.finish();
    }

    @Override
    public void onStart() {
        AppUpdateJob.activityStarted(this);
        super.onStart();
    }

    @Override
    public void onStop() {
        super.onStop();
        AppUpdateJob.activityStopped(this);
    }

    @Override
    public void onResume() {
        super.onResume();
        AppUpdateJob.check(this);
    }

    /**
     * The app's own Capacitor settings with two changes: the start path /chat/ and the chat's
     * "can't connect" page. Capacitor reads the debug flag only when it loads the file itself, and
     * its WebView debugging and logging switches apply to the whole app, so they are kept as the
     * call window sets them.
     */
    @SuppressWarnings("deprecation") // The JSON constructor is the one way to start from the app's own file.
    private CapConfig chatConfig() {
        try (InputStream in = getAssets().open("capacitor.config.json")) {
            JSONObject json = new JSONObject(readAll(in));
            JSONObject server = json.optJSONObject("server");
            if (server == null || server.optString("url", "").isEmpty()) {
                return null;
            }
            server.put("appStartPath", AppWindows.CHAT_PATH);
            server.put("errorPath", CHAT_ERROR_PATH);
            JSONObject android = json.optJSONObject("android");
            if (android == null) {
                android = new JSONObject();
                json.put("android", android);
            }
            boolean debuggable = (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
            if (!android.has("webContentsDebuggingEnabled")) {
                android.put("webContentsDebuggingEnabled", debuggable);
            }
            if ("debug".equals(android.optString("loggingBehavior", "debug"))) {
                android.put("loggingBehavior", debuggable ? "production" : "none");
            }
            return new CapConfig(getAssets(), json);
        } catch (Exception e) {
            Logger.error("MarongWindow", "Chat window settings not read", e);
            return null;
        }
    }

    private static String readAll(InputStream in) throws java.io.IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int read;
        while ((read = in.read(buffer)) != -1) {
            out.write(buffer, 0, read);
        }
        return out.toString(StandardCharsets.UTF_8.name());
    }
}
