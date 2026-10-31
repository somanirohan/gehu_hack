package com.bitchat.android.ui.theme

import android.app.Activity
import android.os.Build
import android.view.View
import android.view.WindowInsetsController
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView

// Standard UI semantics live in Material so stock components and custom Bitchat composables
// share one source of truth. LocalBitchatPalette below supplies app-specific extra colors.
internal val DarkBitchatColorScheme = darkColorScheme(
    primary = Color(0xFFFFB3AD),
    onPrimary = Color(0xFF68000A),
    primaryContainer = Color(0xFFFF5451),
    onPrimaryContainer = Color(0xFF5C0008),
    inversePrimary = Color(0xFFB91A24),
    secondary = Color(0xFFB4C5FF),
    onSecondary = Color(0xFF002A78),
    secondaryContainer = Color(0xFF0053DB),
    onSecondaryContainer = Color(0xFFCDD7FF),
    tertiary = Color(0xFF4AE176),
    onTertiary = Color(0xFF003915),
    tertiaryContainer = Color(0xFF00A74B),
    onTertiaryContainer = Color(0xFF003111),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
    background = Color(0xFF0B1326),
    onBackground = Color(0xFFDAE2FD),
    surface = Color(0xFF0B1326),
    onSurface = Color(0xFFDAE2FD),
    surfaceVariant = Color(0xFF2D3449),
    onSurfaceVariant = Color(0xFFE4BEBA),
    surfaceTint = Color(0xFFFFB3AD),
    inverseSurface = Color(0xFFDAE2FD),
    inverseOnSurface = Color(0xFF283044),
    outline = Color(0xFFAB8986),
    outlineVariant = Color(0xFF5B403E),
    surfaceDim = Color(0xFF0B1326),
    surfaceBright = Color(0xFF31394D),
    surfaceContainerLowest = Color(0xFF060E20),
    surfaceContainerLow = Color(0xFF131B2E),
    surfaceContainer = Color(0xFF171F33),
    surfaceContainerHigh = Color(0xFF222A3D),
    surfaceContainerHighest = Color(0xFF2D3449)
)

internal val LightBitchatColorScheme = lightColorScheme(
    primary = Color(0xFF004AC6),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFF2563EB),
    onPrimaryContainer = Color(0xFFEEEFFF),
    inversePrimary = Color(0xFFB4C5FF),
    secondary = Color(0xFFBB0112),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE02928),
    onSecondaryContainer = Color(0xFFFFFBFF),
    tertiary = Color(0xFF006329),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFF007F36),
    onTertiaryContainer = Color(0xFFC7FFCA),
    error = Color(0xFFBA1A1A),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF93000A),
    background = Color(0xFFFAF8FF),
    onBackground = Color(0xFF131B2E),
    surface = Color(0xFFFAF8FF),
    onSurface = Color(0xFF131B2E),
    surfaceVariant = Color(0xFFDAE2FD),
    onSurfaceVariant = Color(0xFF434655),
    surfaceTint = Color(0xFF0053DB),
    inverseSurface = Color(0xFF283044),
    inverseOnSurface = Color(0xFFEEF0FF),
    outline = Color(0xFF737686),
    outlineVariant = Color(0xFFC3C6D7),
    surfaceDim = Color(0xFFD2D9F4),
    surfaceBright = Color(0xFFFAF8FF),
    surfaceContainerLowest = Color(0xFFFFFFFF),
    surfaceContainerLow = Color(0xFFF2F3FF),
    surfaceContainer = Color(0xFFEAEDFF),
    surfaceContainerHigh = Color(0xFFE2E7FF),
    surfaceContainerHighest = Color(0xFFDAE2FD)
)

@Composable
fun BitchatTheme(
    darkTheme: Boolean? = null,
    content: @Composable () -> Unit
) {
    // App-level override from ThemePreferenceManager, defaulting to Light
    val themePref by ThemePreferenceManager.themeFlow.collectAsState(initial = ThemePreference.Light)
    val shouldUseDark = when (darkTheme) {
        true -> true
        false -> false
        null -> when (themePref) {
            ThemePreference.Dark -> true
            ThemePreference.Light -> false
            ThemePreference.System -> false // Default to Light mode
        }
    }

    val colorScheme = if (shouldUseDark) DarkBitchatColorScheme else LightBitchatColorScheme
    val palette = if (shouldUseDark) DarkBitchatPalette else LightBitchatPalette

    val view = LocalView.current
    SideEffect {
        (view.context as? Activity)?.window?.let { window ->
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                window.insetsController?.setSystemBarsAppearance(
                    if (!shouldUseDark) WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS else 0,
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                )
            } else {
                @Suppress("DEPRECATION")
                window.decorView.systemUiVisibility = if (!shouldUseDark) {
                    View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                } else 0
            }
            window.navigationBarColor = colorScheme.background.toArgb()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.isNavigationBarContrastEnforced = false
            }
        }
    }

    CompositionLocalProvider(LocalBitchatPalette provides palette) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = Typography,
            content = content
        )
    }
}
