package com.bitchat.android.ui.media

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bitchat.android.R
import com.bitchat.android.mesh.MeshService
import com.bitchat.android.model.BitchatMessage
import com.bitchat.android.ui.PeerAvatar
import com.bitchat.android.ui.isFromSelf
import com.bitchat.android.ui.splitSuffix
import com.bitchat.android.ui.theme.BitchatFontFamily
import com.bitchat.android.ui.theme.LocalBitchatPalette
import com.bitchat.android.ui.theme.colorForPeer
import java.text.SimpleDateFormat

@Composable
fun AudioMessageItem(
    message: BitchatMessage,
    currentUserNickname: String,
    meshService: MeshService,
    colorScheme: ColorScheme,
    timeFormatter: SimpleDateFormat,
    onNicknameClick: ((String) -> Unit)?,
    onMessageLongPress: ((BitchatMessage) -> Unit)?,
    onCancelTransfer: ((BitchatMessage) -> Unit)?,
    modifier: Modifier = Modifier,
    showSender: Boolean = true
) {
    val palette = LocalBitchatPalette.current
    val path = message.content.trim()
    val isSelf = message.isFromSelf(currentUserNickname, meshService.myPeerID)

    val (overrideProgress, overrideColor) = when (val st = message.deliveryStatus) {
        is com.bitchat.android.model.DeliveryStatus.PartiallyDelivered -> {
            if (st.total > 0 && st.reached < st.total) {
                (st.reached.toFloat() / st.total.toFloat()) to Color(0xFF1E88E5)
            } else null to null
        }
        else -> null to null
    }

    val bubbleShape = if (isSelf) {
        RoundedCornerShape(topStart = 18.dp, topEnd = 6.dp, bottomEnd = 18.dp, bottomStart = 18.dp)
    } else {
        RoundedCornerShape(topStart = 6.dp, topEnd = 18.dp, bottomEnd = 18.dp, bottomStart = 18.dp)
    }
    val bubbleBg = if (isSelf) colorScheme.primary else colorScheme.surface

    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = if (isSelf) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.Bottom
    ) {
        if (!isSelf && showSender) {
            val (baseName, _) = splitSuffix(message.sender)
            PeerAvatar(
                name = baseName,
                color = colorForPeer(message.senderPeerID ?: message.sender, palette),
                modifier = Modifier
                    .size(32.dp)
                    .clickable { onNicknameClick?.invoke(baseName) },
                showActiveIndicator = true
            )
            Spacer(Modifier.width(8.dp))
        } else if (!isSelf && !showSender) {
            Spacer(Modifier.width(40.dp))
        }

        Box(
            modifier = Modifier
                .widthIn(min = 180.dp, max = 290.dp)
                .padding(bottom = if (isSelf) 8.dp else 0.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(bubbleBg, bubbleShape)
                    .then(
                        if (!isSelf) Modifier.border(0.5.dp, colorScheme.outlineVariant, bubbleShape)
                        else Modifier
                    )
                    .clickable { onMessageLongPress?.invoke(message) }
                    .padding(horizontal = 14.dp, vertical = 10.dp)
            ) {
                if (!isSelf && showSender) {
                    val (baseName, _) = splitSuffix(message.sender)
                    Text(
                        text = baseName,
                        fontFamily = BitchatFontFamily,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 12.sp,
                        color = colorForPeer(message.senderPeerID ?: message.sender, palette),
                        modifier = Modifier.padding(bottom = 4.dp)
                    )
                }

                VoiceNotePlayer(
                    path = path,
                    progressOverride = overrideProgress,
                    progressColor = overrideColor,
                    isSelf = isSelf,
                    waveformBaseColor = if (isSelf) Color.White.copy(alpha = 0.45f) else Color(0xFFCBD5E1),
                    waveformFillColor = if (isSelf) Color.White else Color(0xFF475569)
                )

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 4.dp),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = timeFormatter.format(message.timestamp),
                        fontSize = 10.sp,
                        fontFamily = BitchatFontFamily,
                        color = if (isSelf) Color.White.copy(alpha = 0.8f) else colorScheme.onSurfaceVariant.copy(alpha = 0.65f)
                    )
                    if (isSelf) {
                        Spacer(Modifier.width(4.dp))
                        Text(
                            text = "✓✓",
                            fontSize = 10.sp,
                            fontFamily = BitchatFontFamily,
                            color = Color.White.copy(alpha = 0.85f),
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }

            // Mockup reaction badge: funny reaction emoji floating at the bottom edge for sent voice note
            if (isSelf) {
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .offset(x = 6.dp, y = 8.dp)
                        .size(20.dp)
                        .background(colorScheme.surface, CircleShape)
                        .border(1.dp, colorScheme.outlineVariant, CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    Text(text = "😂", fontSize = 11.sp)
                }
            }

            // Cancel sending transfer if active
            val showCancel = message.sender == currentUserNickname && (message.deliveryStatus is com.bitchat.android.model.DeliveryStatus.PartiallyDelivered)
            if (showCancel) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 4.dp, y = (-4).dp)
                        .size(22.dp)
                        .background(Color.Gray.copy(alpha = 0.7f), CircleShape)
                        .clickable { onCancelTransfer?.invoke(message) },
                    contentAlignment = Alignment.Center
                ) {
                    Icon(imageVector = Icons.Filled.Close, contentDescription = stringResource(R.string.cd_cancel), tint = Color.White, modifier = Modifier.size(14.dp))
                }
            }
        }
    }
}
