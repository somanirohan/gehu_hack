package com.bitchat.android.ui.theme

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * App theme preference: System default, Light, or Dark.
 */
enum class ThemePreference {
    System,
    Light,
    Dark;

    val isSystem : Boolean get() = this == System
    val isLight : Boolean get() = this == Light
    val isDark : Boolean get() = this == Dark
}

/**
 * Simple SharedPreferences-backed manager for theme preference with a StateFlow.
 * Avoids adding DataStore dependency for now.
 */
object ThemePreferenceManager {
    private const val PREFS_NAME = "bitchat_settings"
    private const val KEY_THEME = "theme_preference"

    private val _themeFlow = MutableStateFlow(ThemePreference.Light)
    val themeFlow: StateFlow<ThemePreference> = _themeFlow

    fun init(context: Context) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val saved = prefs.getString(KEY_THEME, ThemePreference.Light.name)
        val pref = runCatching { ThemePreference.valueOf(saved!!) }.getOrDefault(ThemePreference.Light)
        _themeFlow.value = pref
        applyNightMode(pref)
    }

    fun set(context: Context, preference: ThemePreference) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_THEME, preference.name).apply()
        _themeFlow.value = preference
        applyNightMode(preference)
    }

    fun applyNightMode(preference: ThemePreference) {
        val mode = when (preference) {
            ThemePreference.Light -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_NO
            ThemePreference.Dark -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_YES
            ThemePreference.System -> androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
        }
        if (androidx.appcompat.app.AppCompatDelegate.getDefaultNightMode() != mode) {
            androidx.appcompat.app.AppCompatDelegate.setDefaultNightMode(mode)
        }
    }

    /** Helper to easily toggle theme later when dark mode toggle button is added */
    fun toggleTheme(context: Context) {
        val next = if (_themeFlow.value == ThemePreference.Dark) ThemePreference.Light else ThemePreference.Dark
        set(context, next)
    }
}
