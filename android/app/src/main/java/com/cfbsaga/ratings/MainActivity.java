package com.cfbsaga.ratings;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.DisplayCutout;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.window.OnBackInvokedDispatcher;

/** Full-screen WebView that shows the bundled ratings board (assets/index.html). */
public class MainActivity extends Activity {

    private static final String BOARD_URL = "file:///android_asset/index.html";

    // Closes whichever detail sheet is open and reports whether one was.
    private static final String CLOSE_SHEET_JS =
            "(function(){var b=document.querySelector('.sheet:not([hidden]) .sheet-close');"
                    + "if(b){b.click();return true;}return false;})()";

    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setBackgroundColor(getColor(R.color.page_bg));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (uri.toString().startsWith("file:///android_asset/")) {
                    return false;
                }
                // Outside links (sagarin.com) open in the user's browser.
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException ignored) {
                    // No browser installed; stay on the board.
                }
                return true;
            }
        });

        // WebView draws its page underneath its own padding, so the safe-area padding goes on a
        // container instead; that keeps the header clear of the status bar and camera cutout.
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(getColor(R.color.page_bg));
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        drawEdgeToEdge(root);
        setContentView(root);

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
        } else {
            webView.loadUrl(BOARD_URL);
        }

        if (Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        }
    }

    /** Lays the window out edge to edge and pads the container by the bars, cutout, and keyboard. */
    private void drawEdgeToEdge(View view) {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
        } else {
            View decor = getWindow().getDecorView();
            decor.setSystemUiVisibility(decor.getSystemUiVisibility()
                    | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
        view.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets i = insets.getInsets(WindowInsets.Type.systemBars()
                        | WindowInsets.Type.displayCutout()
                        | WindowInsets.Type.ime());
                v.setPadding(i.left, i.top, i.right, i.bottom);
                // Consumed here so the page's env(safe-area-inset-*) doesn't pad a second time.
                return WindowInsets.CONSUMED;
            } else {
                // Android 9-10: system window insets cover the bars and keyboard; the cutout's
                // safe area is reported separately, so take whichever is larger on each side.
                DisplayCutout cutout = insets.getDisplayCutout();
                int cl = cutout != null ? cutout.getSafeInsetLeft() : 0;
                int ct = cutout != null ? cutout.getSafeInsetTop() : 0;
                int cr = cutout != null ? cutout.getSafeInsetRight() : 0;
                int cb = cutout != null ? cutout.getSafeInsetBottom() : 0;
                v.setPadding(Math.max(insets.getSystemWindowInsetLeft(), cl),
                        Math.max(insets.getSystemWindowInsetTop(), ct),
                        Math.max(insets.getSystemWindowInsetRight(), cr),
                        Math.max(insets.getSystemWindowInsetBottom(), cb));
                return insets.consumeSystemWindowInsets().consumeDisplayCutout();
            }
        });
    }

    /** Back closes an open detail sheet first, then leaves the app. */
    private void handleBack() {
        webView.evaluateJavascript(CLOSE_SHEET_JS, result -> {
            if (!"true".equals(result)) {
                finish();
            }
        });
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        // Only reached below Android 13; newer versions use the callback registered in onCreate.
        handleBack();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onDestroy() {
        webView.destroy();
        super.onDestroy();
    }
}
