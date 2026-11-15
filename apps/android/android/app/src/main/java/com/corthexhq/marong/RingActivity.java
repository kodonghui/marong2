package com.corthexhq.marong;

import android.app.KeyguardManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowManager;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import java.lang.ref.WeakReference;

/**
 * The full-screen ring (SCR-110, docs/app-ring.md SPEC-133): over the lock screen, it turns the
 * screen on and offers 받기 and 거절. 받기 asks Android to unlock first when the phone is locked.
 */
public class RingActivity extends AppCompatActivity {

    private static WeakReference<RingActivity> shown = new WeakReference<>(null);

    private final Handler main = new Handler(Looper.getMainLooper());
    private String ringId;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ringId = getIntent().getStringExtra(Ring.EXTRA_RING_ID);
        long shownAt = getIntent().getLongExtra(Ring.EXTRA_SHOWN_AT, 0L);
        long left = Ring.RING_MS - (System.currentTimeMillis() - shownAt);
        // A late tap or a ring that already stopped opens nothing.
        if (!PushLinks.isRingId(ringId) || left <= 0 || !Ring.isRinging(this, ringId)) {
            finish();
            return;
        }
        showOverLockScreen();
        setContentView(R.layout.activity_ring);
        findViewById(R.id.ring_answer).setOnClickListener(v -> answer());
        findViewById(R.id.ring_decline).setOnClickListener(v -> {
            Ring.cancel(this);
            finish();
        });
        // Back leaves the ring screen; the notification keeps ringing until its time is up.
        getOnBackPressedDispatcher()
            .addCallback(
                this,
                new OnBackPressedCallback(true) {
                    @Override
                    public void handleOnBackPressed() {
                        finish();
                    }
                }
            );
        main.postDelayed(this::finish, Math.min(left, Ring.RING_MS));
        shown = new WeakReference<>(this);
    }

    private void showOverLockScreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
    }

    private void answer() {
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        if (keyguard != null && keyguard.isKeyguardLocked()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                keyguard.requestDismissKeyguard(
                    this,
                    new KeyguardManager.KeyguardDismissCallback() {
                        @Override
                        public void onDismissSucceeded() {
                            openCall();
                        }
                        // Cancelled or failed: the ring screen stays, and the ring keeps sounding.
                    }
                );
                return;
            }
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);
        }
        openCall();
    }

    private void openCall() {
        startActivity(Ring.answerIntent(this, ringId));
        finish();
    }

    /** The ring stopped elsewhere (answered from the notification, declined, call started). */
    static void closeShown() {
        new Handler(Looper.getMainLooper()).post(() -> {
            RingActivity activity = shown.get();
            if (activity != null && !activity.isFinishing()) {
                activity.finish();
            }
        });
    }

    @Override
    protected void onDestroy() {
        main.removeCallbacksAndMessages(null);
        if (shown.get() == this) {
            shown = new WeakReference<>(null);
        }
        super.onDestroy();
    }
}
