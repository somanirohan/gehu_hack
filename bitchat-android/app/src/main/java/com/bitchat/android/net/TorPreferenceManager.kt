package com.bitchat.android.net

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

object TorPreferenceManager {
    private const val PREFS_NAME = "bitchat_settings"
    private const val KEY_TOR_MODE = "tor_mode"

    private val defaultMode: TorMode
        get() = if (org.torproject.arti.ArtiNative.isSupported) TorMode.ON else TorMode.OFF

    private val _modeFlow = MutableStateFlow(TorMode.OFF)
    val modeFlow: StateFlow<TorMode> = _modeFlow

    fun init(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val defaultName = defaultMode.name
        val saved = prefs.getString(KEY_TOR_MODE, defaultName)
        val mode = runCatching { TorMode.valueOf(saved ?: defaultName) }.getOrDefault(defaultMode)
        // If native library is missing, force OFF
        _modeFlow.value = if (org.torproject.arti.ArtiNative.isSupported) mode else TorMode.OFF
    }

    fun set(context: Context, mode: TorMode) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_TOR_MODE, mode.name).apply()
        _modeFlow.value = if (org.torproject.arti.ArtiNative.isSupported) mode else TorMode.OFF
    }

    fun get(context: Context): TorMode {
        if (!org.torproject.arti.ArtiNative.isSupported) return TorMode.OFF
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val defaultName = defaultMode.name
        val saved = prefs.getString(KEY_TOR_MODE, defaultName)
        return runCatching { TorMode.valueOf(saved ?: defaultName) }.getOrDefault(defaultMode)
    }
}

