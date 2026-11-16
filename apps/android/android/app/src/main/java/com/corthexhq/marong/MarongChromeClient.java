package com.corthexhq.marong;

import android.net.Uri;
import android.webkit.PermissionRequest;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;

/**
 * Capacitor's chrome client, except that only the call site in the call window may ask for the
 * microphone (SPEC-106, docs/app-chat.md SPEC-147). Capacitor would pass a request from any page in
 * the app window, such as the sign-in pages, on to Android's permission prompt. The chat window
 * holds no calls, so it refuses every request.
 */
class MarongChromeClient extends BridgeWebChromeClient {

    private final String appUrl;
    private final boolean microphone;

    MarongChromeClient(Bridge bridge, boolean microphone) {
        super(bridge);
        this.appUrl = bridge.getServerUrl();
        this.microphone = microphone;
    }

    @Override
    public void onPermissionRequest(PermissionRequest request) {
        Uri origin = request.getOrigin();
        if (!microphone || origin == null || appUrl == null || !AppUrls.isAppPage(origin.toString(), appUrl)) {
            request.deny();
            return;
        }
        super.onPermissionRequest(request);
    }
}
