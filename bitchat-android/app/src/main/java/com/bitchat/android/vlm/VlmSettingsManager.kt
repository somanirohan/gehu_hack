package com.bitchat.android.vlm

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class VlmDestination(
    val type: String,
    val id: String
)

data class VlmSettings(
    val enabled: Boolean = false,
    val httpPort: Int = 8765,
    val defaultDestination: VlmDestination? = null,
    val rateLimitMs: Long = 5000,
    val silenceEnabled: Boolean = false
)

object VlmSettingsManager {
    private const val PREFS_NAME = "vlm_api_settings"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_HTTP_PORT = "http_port"
    private const val KEY_DEST_TYPE = "dest_type"
    private const val KEY_DEST_ID = "dest_id"
    private const val KEY_RATE_LIMIT_MS = "rate_limit_ms"
    private const val KEY_SILENCE_ENABLED = "silence_enabled"

    private var prefs: SharedPreferences? = null

    private val _settings = MutableStateFlow(VlmSettings())
    val settings: StateFlow<VlmSettings> = _settings.asStateFlow()

    fun initialize(context: Context) {
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        loadSettings()
    }

    private fun loadSettings() {
        val p = prefs ?: return
        val destType = p.getString(KEY_DEST_TYPE, null)
        val destId = p.getString(KEY_DEST_ID, null)
        val destination = if (destType != null && destId != null) {
            VlmDestination(destType, destId)
        } else null

        _settings.value = VlmSettings(
            enabled = p.getBoolean(KEY_ENABLED, false),
            httpPort = p.getInt(KEY_HTTP_PORT, 8765),
            defaultDestination = destination,
            rateLimitMs = p.getLong(KEY_RATE_LIMIT_MS, 5000),
            silenceEnabled = p.getBoolean(KEY_SILENCE_ENABLED, false)
        )
    }

    fun setEnabled(enabled: Boolean) {
        prefs?.edit()?.putBoolean(KEY_ENABLED, enabled)?.apply()
        loadSettings()
    }

    fun setHttpPort(port: Int) {
        if (port in 1024..65535) {
            prefs?.edit()?.putInt(KEY_HTTP_PORT, port)?.apply()
            loadSettings()
        }
    }

    fun setDefaultDestination(destination: VlmDestination?) {
        val editor = prefs?.edit()
        if (destination == null) {
            editor?.remove(KEY_DEST_TYPE)?.remove(KEY_DEST_ID)
        } else {
            editor?.putString(KEY_DEST_TYPE, destination.type)
            editor?.putString(KEY_DEST_ID, destination.id)
        }
        editor?.apply()
        loadSettings()
    }

    fun setRateLimitMs(limitMs: Long) {
        prefs?.edit()?.putLong(KEY_RATE_LIMIT_MS, limitMs)?.apply()
        loadSettings()
    }

    fun setSilenceEnabled(enabled: Boolean) {
        prefs?.edit()?.putBoolean(KEY_SILENCE_ENABLED, enabled)?.apply()
        loadSettings()
    }

    fun isEnabled(): Boolean = _settings.value.enabled

    fun getHttpPort(): Int = _settings.value.httpPort

    fun getDefaultDestination(): VlmDestination? = _settings.value.defaultDestination

    fun isSilenceEnabled(): Boolean = _settings.value.silenceEnabled

    fun getRateLimitMs(): Long = _settings.value.rateLimitMs
}
