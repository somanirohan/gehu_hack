package com.bitchat.android.services

import android.content.Context
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Persistence for the "civilization bridge" sync feature. Stores the user
 * configurable REST endpoint, the local NanoHTTPD ingest toggle, the last
 * successfully synced incident id (watermark), and the Tor preference.
 *
 * Default state is everything disabled, so no incident data ever leaves the
 * device without an explicit consent-driven toggle in the debug sheet.
 */
class SyncPreferences private constructor(context: Context) {

    companion object {
        private const val PREFS = "bitchat_sync_prefs_v1"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_ENDPOINT_URL = "endpoint_url"
        private const val KEY_LOCAL_INGEST_PORT = "local_ingest_port"
        private const val KEY_LOCAL_INGEST_ENABLED = "local_ingest_enabled"
        private const val KEY_USE_TOR = "use_tor"
        private const val KEY_LAST_SYNCED_AT = "last_synced_at"
        private const val KEY_LAST_FLUSH_BYTES = "last_flush_bytes"

        @Volatile private var instance: SyncPreferences? = null
        fun getInstance(context: Context): SyncPreferences =
            instance ?: synchronized(this) {
                instance ?: SyncPreferences(context.applicationContext).also { instance = it }
            }
    }

    private val prefs = try {
        val masterKey = MasterKey.Builder(context, MasterKey.DEFAULT_MASTER_KEY_ALIAS)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREFS,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    } catch (e: Exception) {
        Log.w("SyncPreferences", "Falling back to plain prefs: ${e.message}")
        context.getSharedPreferences("${PREFS}_fallback", Context.MODE_PRIVATE)
    }

    var enabled: Boolean
        get() = prefs.getBoolean(KEY_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_ENABLED, value).apply()

    var endpointUrl: String
        get() = prefs.getString(KEY_ENDPOINT_URL, "") ?: ""
        set(value) = prefs.edit().putString(KEY_ENDPOINT_URL, value).apply()

    var localIngestEnabled: Boolean
        get() = prefs.getBoolean(KEY_LOCAL_INGEST_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_LOCAL_INGEST_ENABLED, value).apply()

    var localIngestPort: Int
        get() = prefs.getInt(KEY_LOCAL_INGEST_PORT, 8420)
        set(value) = prefs.edit().putInt(KEY_LOCAL_INGEST_PORT, value.coerceIn(1024, 65535)).apply()

    var useTor: Boolean
        get() = prefs.getBoolean(KEY_USE_TOR, false)
        set(value) = prefs.edit().putBoolean(KEY_USE_TOR, value).apply()

    var lastSyncedAt: Long
        get() = prefs.getLong(KEY_LAST_SYNCED_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_SYNCED_AT, value).apply()

    var lastFlushBytes: Int
        get() = prefs.getInt(KEY_LAST_FLUSH_BYTES, 0)
        set(value) = prefs.edit().putInt(KEY_LAST_FLUSH_BYTES, value).apply()

    var lastSyncError: String?
        get() = prefs.getString("last_sync_error", null)
        set(value) = prefs.edit().putString("last_sync_error", value).apply()
}