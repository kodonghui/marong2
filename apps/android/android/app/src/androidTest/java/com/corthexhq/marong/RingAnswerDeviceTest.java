package com.corthexhq.marong;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import android.Manifest;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.SystemClock;
import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class RingAnswerDeviceTest {
    private Context context;

    @Before
    public void grantPermissions() {
        Instrumentation tools = InstrumentationRegistry.getInstrumentation();
        context = tools.getTargetContext();
        tools.getUiAutomation().grantRuntimePermission(context.getPackageName(), Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= 33) {
            tools.getUiAutomation().grantRuntimePermission(context.getPackageName(), Manifest.permission.POST_NOTIFICATIONS);
        }
    }

    @Test
    public void coldRingIsTheBridgeStartPath() {
        String ring = UUID.randomUUID().toString();
        long now = System.currentTimeMillis();
        assertTrue(PushState.firstRing(context, ring, now));
        Intent answer = Ring.answerIntent(context, ring).putExtra(Ring.EXTRA_ANSWERED_AT, now);
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(answer)) {
            scenario.onActivity(activity -> {
                String url = activity.getBridge().getServerUrl();
                assertEquals(PushLinks.ringUrl(url, ring), activity.getBridge().getAppUrl());
                assertTrue(activity.coldRingScript().contains(Long.toString(now)));
            });
        }
    }

    @Test
    public void warmRingCallsThePageHookWithoutReloading() throws Exception {
        String ring = UUID.randomUUID().toString();
        long now = System.currentTimeMillis();
        assertTrue(PushState.firstRing(context, ring, now));
        try (ActivityScenario<MainActivity> scenario = ActivityScenario.launch(MainActivity.class)) {
            scenario.onActivity(activity -> {
                String base = PushLinks.pageUrl(activity.getBridge().getServerUrl(), "/");
                activity.getBridge().getWebView().loadDataWithBaseURL(base, """
                    <!doctype html><script>
                    window.__marongCall = {
                      prepareCall() { window.prepared = true; return true; },
                      answerRing(id, at) { window.answer = id; window.answeredAt = at; return true; }
                    };
                    </script>
                    """, "text/html", "UTF-8", null);
            });
            awaitScript(scenario, "typeof window.__marongCall === 'object'", "true");
            scenario.onActivity(activity -> CallControl.prepareForRing());
            awaitScript(scenario, "window.prepared === true", "true");
            scenario.onActivity(activity -> activity.onNewIntent(
                Ring.answerIntent(context, ring).putExtra(Ring.EXTRA_ANSWERED_AT, now)));
            awaitScript(scenario, "window.answer === '" + ring + "' && window.answeredAt === " + now, "true");
            assertEquals("true", script(scenario, "location.search === ''"));
        }
    }

    private static String script(ActivityScenario<MainActivity> scenario, String code) throws Exception {
        CompletableFuture<String> answer = new CompletableFuture<>();
        scenario.onActivity(activity -> activity.getBridge().getWebView().evaluateJavascript(code, answer::complete));
        return answer.get(3, TimeUnit.SECONDS);
    }

    private static void awaitScript(ActivityScenario<MainActivity> scenario, String code, String expected) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 5000;
        String actual;
        do {
            actual = script(scenario, code);
            if (expected.equals(actual)) {
                return;
            }
            SystemClock.sleep(50);
        } while (SystemClock.uptimeMillis() < deadline);
        assertEquals(expected, actual);
    }
}
