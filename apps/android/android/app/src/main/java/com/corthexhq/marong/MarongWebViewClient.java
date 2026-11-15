package com.corthexhq.marong;

import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * Capacitor's client, except that only a server outage (HTTP 5xx) swaps in the app's
 * "can't connect" page (SPEC-108). Capacitor would also swap it in for 4xx pages, which would
 * hide the Access sign-in messages, such as a wrong code or an email that is not allowed.
 * Network failures (no internet) still show the page through Capacitor's onReceivedError.
 */
class MarongWebViewClient extends BridgeWebViewClient {

    MarongWebViewClient(Bridge bridge) {
        super(bridge);
    }

    @Override
    public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
        if (request.isForMainFrame() && !AppUrls.isServerOutage(errorResponse.getStatusCode())) {
            return; // Keep the page the server or Access sent, with its own explanation.
        }
        super.onReceivedHttpError(view, request, errorResponse);
    }
}
