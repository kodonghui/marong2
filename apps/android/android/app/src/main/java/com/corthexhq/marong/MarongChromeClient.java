package com.corthexhq.marong;

import android.net.Uri;
import android.webkit.PermissionRequest;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;

/**
 * Capacitor's chrome client, except that only the call site may ask for the microphone (SPEC-106).
 * Capacitor would pass a request from any page in the app window, such as the sign-in pages, on to
 * Android's permission prompt.
 */
class MarongChromeClient extends BridgeWebChromeClient {

    private final String appUrl;

    MarongChromeClient(Bridge bridge) {
        super(bridge);
        this.appUrl = bridge.getServerUrl();
    }

    @Override
    public void onPermissionRequest(PermissionRequest request) {
        Uri origin = request.getOrigin();
        if (origin == null || appUrl == null || !AppUrls.isAppPage(origin.toString(), appUrl)) {
            request.deny();
            return;
        }
        super.onPermissionRequest(request);
    }
}
