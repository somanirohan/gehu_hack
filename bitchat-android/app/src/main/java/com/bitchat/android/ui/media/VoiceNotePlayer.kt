package com.bitchat.android.ui.media

import com.bitchat.android.ui.theme.BitchatFontFamily
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import android.media.MediaPlayer
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun VoiceNotePlayer(
    path: String,
    progressOverride: Float? = null,
    progressColor: Color? = null,
    isSelf: Boolean = false,
    waveformBaseColor: Color? = null,
    waveformFillColor: Color? = null
) {
    var isPlaying by remember { mutableStateOf(false) }
    var isPrepared by remember { mutableStateOf(false) }
    var isError by remember { mutableStateOf(false) }
    var progress by remember { mutableStateOf(0f) }
    var durationMs by remember { mutableStateOf(0) }
    val player = remember { MediaPlayer() }

    // Seek function - position is a fraction from 0.0 to 1.0
    val seekTo: (Float) -> Unit = { position ->
        if (isPrepared && durationMs > 0) {
            val seekMs = (position * durationMs).toInt().coerceIn(0, durationMs)
            try {
                player.seekTo(seekMs)
                progress = position  // Update progress immediately for UI responsiveness
            } catch (_: Exception) {}
        }
    }

    LaunchedEffect(path) {
        isPrepared = false
        isError = false
        progress = 0f
        durationMs = 0
        isPlaying = false
        try {
            player.reset()
            player.setOnPreparedListener {
                isPrepared = true
                durationMs = try { player.duration } catch (_: Exception) { 0 }
            }
            player.setOnCompletionListener {
                isPlaying = false
                progress = 1f
            }
            player.setOnErrorListener { _, _, _ ->
                isError = true
                isPlaying = false
                true
            }
            player.setDataSource(path)
            player.prepareAsync()
        } catch (_: Exception) {
            isError = true
        }
    }

    LaunchedEffect(isPlaying, isPrepared) {
        try {
            if (isPlaying && isPrepared) player.start() else if (isPrepared && player.isPlaying) player.pause()
        } catch (_: Exception) {}
    }
    LaunchedEffect(isPlaying, isPrepared) {
        while (isPlaying && isPrepared) {
            progress = try { player.currentPosition.toFloat() / (player.duration.toFloat().coerceAtLeast(1f)) } catch (_: Exception) { 0f }
            kotlinx.coroutines.delay(100)
        }
    }
    DisposableEffect(Unit) { onDispose { try { player.release() } catch (_: Exception) {} } }

    val controlsEnabled = isPrepared && !isError && progressOverride == null
    val playBtnBg = if (isSelf) Color.White else Color(0xFF1E293B)
    val playBtnTint = if (isSelf) Color(0xFF1B64F2) else Color.White
    val baseColor = waveformBaseColor ?: if (isSelf) Color.White.copy(alpha = 0.45f) else Color(0xFFCBD5E1)
    val fillColor = waveformFillColor ?: if (isSelf) Color.White else Color(0xFF334155)
    val textColor = if (isSelf) Color.White.copy(alpha = 0.9f) else Color(0xFF64748B)

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Box(
            modifier = Modifier
                .size(32.dp)
                .background(playBtnBg, CircleShape)
                .clickable(enabled = controlsEnabled) { if (controlsEnabled) isPlaying = !isPlaying },
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                contentDescription = if (isPlaying) "Pause" else "Play",
                tint = playBtnTint,
                modifier = Modifier.size(18.dp)
            )
        }
        com.bitchat.android.ui.media.WaveformPreview(
            modifier = Modifier
                .height(26.dp)
                .weight(1f)
                .padding(horizontal = 4.dp, vertical = 2.dp),
            path = path,
            sendProgress = progressOverride,
            playbackProgress = if (progressOverride == null) progress else null,
            baseColor = baseColor,
            fillColor = fillColor,
            onSeek = seekTo
        )
        val durText = if (durationMs > 0) String.format("%02d:%02d", (durationMs / 1000) / 60, (durationMs / 1000) % 60) else "--:--"
        Text(text = durText, fontFamily = BitchatFontFamily, fontSize = 12.sp, color = textColor)
    }
}

