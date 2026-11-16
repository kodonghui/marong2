package com.corthexhq.marong;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * 거절 on the ring notification: stops the ring only. The server is not told; after the answer
 * window it counts the ring as missed, as if nobody had answered (docs/app-ring.md SPEC-132).
 */
public class RingDeclineReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        Ring.cancel(context);
    }
}
