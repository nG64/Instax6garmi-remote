package de.schluesselausgabe.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import java.io.OutputStream;
import java.util.regex.Pattern;

/**
 * Zeigt Schluesselausgabe.html (aus den App-Assets) in einem WebView an.
 * Die Seite speichert PDFs über die Brücke "AndroidApp" unter
 * Download/Schluesselausgabe/<Raum>/<Datei>.pdf.
 */
public class MainActivity extends Activity {

    private static final String START_URL = "https://appassets.androidplatform.net/assets/index.html";
    private static final int DATEI_WAHL = 1;
    private static final String BASIS_ORDNER = Environment.DIRECTORY_DOWNLOADS + "/Schluesselausgabe/";
    // erlaubt: "Datei.pdf" oder "Ordner/Datei.pdf" mit einfachen Zeichen (Namen werden in der Seite bereits bereinigt)
    private static final Pattern ERLAUBTER_PFAD = Pattern.compile("([A-Za-z0-9_\\-][A-Za-z0-9._\\-]*/)?[A-Za-z0-9_\\-][A-Za-z0-9._\\-]*\\.pdf");

    private WebView web;
    private ValueCallback<Uri[]> dateiCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        web = new WebView(this);
        setContentView(web);

        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(true);   // für die ausgewählte Excel-Datei

        final WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return loader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                // Keine Navigation weg von der App-Seite
                return !"appassets.androidplatform.net".equals(request.getUrl().getHost());
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (dateiCallback != null) dateiCallback.onReceiveValue(null);
                dateiCallback = callback;
                Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                i.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "application/vnd.ms-excel",
                        "application/vnd.ms-excel.sheet.macroEnabled.12",
                        "application/vnd.oasis.opendocument.spreadsheet",
                        "text/csv", "text/comma-separated-values", "text/plain",
                        "application/octet-stream"});
                try {
                    startActivityForResult(i, DATEI_WAHL);
                } catch (ActivityNotFoundException e) {
                    dateiCallback = null;
                    callback.onReceiveValue(null);
                }
                return true;
            }
        });

        web.addJavascriptInterface(new Bruecke(), "AndroidApp");

        if (savedInstanceState == null) web.loadUrl(START_URL);
        else web.restoreState(savedInstanceState);
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == DATEI_WAHL && dateiCallback != null) {
            Uri[] ergebnis = (resultCode == RESULT_OK && data != null && data.getData() != null)
                    ? new Uri[]{data.getData()} : null;
            dateiCallback.onReceiveValue(ergebnis);
            dateiCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        // Zurück schließt zuerst das Unterschriftsfenster; sonst App in den Hintergrund (Zustand bleibt erhalten)
        web.evaluateJavascript("window.appZurueck ? window.appZurueck() : false", wert -> {
            if (!"true".equals(wert)) moveTaskToBack(true);
        });
    }

    /** Wird aus JavaScript aufgerufen: window.AndroidApp.speichere(pfad, base64) */
    private class Bruecke {
        @JavascriptInterface
        public String speichere(String relPfad, String base64) {
            try {
                if (relPfad == null || !ERLAUBTER_PFAD.matcher(relPfad).matches() || relPfad.contains("..")) {
                    return "FEHLER: ungültiger Dateiname";
                }
                byte[] daten = Base64.decode(base64, Base64.DEFAULT);
                int trenner = relPfad.lastIndexOf('/');
                String ordner = BASIS_ORDNER + (trenner > 0 ? relPfad.substring(0, trenner) + "/" : "");
                String name = relPfad.substring(trenner + 1);

                ContentResolver cr = getContentResolver();
                Uri sammlung = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY);

                // Gibt es die Datei (von dieser App) schon, wird sie überschrieben, z. B. bei „Neu unterschreiben“
                Uri ziel = null;
                try (Cursor c = cr.query(sammlung, new String[]{MediaStore.MediaColumns._ID},
                        MediaStore.MediaColumns.RELATIVE_PATH + "=? AND " + MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                        new String[]{ordner, name}, null)) {
                    if (c != null && c.moveToFirst()) ziel = ContentUris.withAppendedId(sammlung, c.getLong(0));
                }
                if (ziel == null) {
                    ContentValues v = new ContentValues();
                    v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                    v.put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf");
                    v.put(MediaStore.MediaColumns.RELATIVE_PATH, ordner);
                    ziel = cr.insert(sammlung, v);
                    if (ziel == null) return "FEHLER: Datei konnte nicht angelegt werden";
                }
                try (OutputStream os = cr.openOutputStream(ziel, "wt")) {
                    if (os == null) return "FEHLER: Datei konnte nicht geöffnet werden";
                    os.write(daten);
                }
                return "Downloads/Schluesselausgabe/" + relPfad;
            } catch (Exception e) {
                return "FEHLER: " + e.getMessage();
            }
        }
    }
}
