package com.corthexhq.marong;

import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;

/**
 * Capacitor's client, except that:
 *
 * <ul>
 *   <li>Only a server outage (HTTP 5xx) swaps in the app's "can't connect" page (SPEC-108).
 *       Capacitor would also swap it in for 4xx pages, which would hide the Access sign-in
 *       messages, such as a wrong code or an email that is not allowed. Network failures (no
 *       internet) still show the page through Capacitor's onReceivedError.
 *   <li>A page that belongs in the other app window opens that window instead (D20,
 *       docs/app-chat.md SPEC-144): the chat from the call window, the call page from the chat
 *       window. The page in this window stays, so a call in the call window goes on.
 * </ul>
 */
class MarongWebViewClient extends BridgeWebViewClient {

    private final Bridge bridge;
    private final boolean chatWindow;

    MarongWebViewClient(Bridge bridge, boolean chatWindow) {
        super(bridge);
        this.bridge = bridge;
        this.chatWindow = chatWindow;
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        if (request.isForMainFrame()) {
            switch (AppWindows.move(request.getUrl().toString(), bridge.getServerUrl(), chatWindow)) {
                case OPEN_CHAT:
                    ChatActivity.open(bridge.getActivity());
                    return true;
                case BACK_TO_CALL:
                    ChatActivity.backToCall(bridge.getActivity());
                    return true;
                default:
                    break;
            }
        }
        return super.shouldOverrideUrlLoading(view, request);
    }

    @Override
    public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
        if (request.isForMainFrame() && !AppUrls.isServerOutage(errorResponse.getStatusCode())) {
            return; // Keep the page the server or Access sent, with its own explanation.
        }
        super.onReceivedHttpError(view, request, errorResponse);
    }
}
