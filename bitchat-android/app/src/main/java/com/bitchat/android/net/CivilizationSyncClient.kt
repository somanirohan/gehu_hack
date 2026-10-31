package com.bitchat.android.net

import android.content.Context
import android.util.Log
import com.bitchat.android.services.SyncPreferences
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.InetSocketAddress
import java.net.Proxy
import java.util.concurrent.TimeUnit

/**
 * Posts the structured "civilization bridge" bundle to the user-configured REST
 * endpoint when internet becomes available. Honors the Tor preference by
 * routing through the local SOCKS5 proxy when ArtiTor is enabled.
 */
class CivilizationSyncClient(context: Context) {

    companion object {
        private const val TAG = "CivilizationSyncClient"
        private const val JSON = "application/json; charset=utf-8"
    }

    private val appContext = context.applicationContext
    private val prefs = SyncPreferences.getInstance(context)

    private fun client(): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
        if (prefs.useTor) {
            try {
                builder.proxy(Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", 39060)))
            } catch (_: Exception) { }
        }
        return builder.build()
    }

    /**
     * Returns true on HTTP 2xx. Updates [SyncPreferences.lastSyncedAt] and
     * [SyncPreferences.lastSyncError] accordingly.
     */
    fun postBundle(json: String): Boolean {
        val url = prefs.endpointUrl.trim()
        if (url.isEmpty() || !url.startsWith("http")) {
            prefs.lastSyncError = "endpoint disabled or malformed"
            return false
        }
        return try {
            val request = Request.Builder()
                .url(url)
                .post(json.toRequestBody(JSON.toMediaType()))
                .addHeader("Content-Type", JSON)
                .build()
            client().newCall(request).execute().use { response ->
                val ok = response.code in 200..299
                prefs.lastSyncedAt = System.currentTimeMillis()
                prefs.lastSyncError = if (ok) null else "HTTP ${response.code}"
                Log.i(TAG, "Sync post $url -> ${response.code}")
                ok
            }
        } catch (e: Exception) {
            prefs.lastSyncError = e.message?.take(200)
            Log.w(TAG, "Sync post failed: ${e.message}")
            false
        }
    }
}