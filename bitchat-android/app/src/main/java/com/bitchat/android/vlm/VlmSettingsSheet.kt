package com.bitchat.android.vlm

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bitchat.android.core.ui.component.sheet.BitchatBottomSheet
import com.bitchat.android.core.ui.component.sheet.BitchatSheetTopBar
import com.bitchat.android.core.ui.component.sheet.BitchatSheetTitle
import com.bitchat.android.ui.theme.BitchatFontFamily

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VlmSettingsSheet(
    isPresented: Boolean,
    onDismiss: () -> Unit
) {
    val context = LocalContext.current
    val colorScheme = MaterialTheme.colorScheme

    VlmSettingsManager.initialize(context)

    var enabled by remember { mutableStateOf(VlmSettingsManager.isEnabled()) }
    var httpPort by remember { mutableStateOf(VlmSettingsManager.getHttpPort().toString()) }
    var silenceEnabled by remember { mutableStateOf(VlmSettingsManager.isSilenceEnabled()) }
    var rateLimit by remember { mutableStateOf(VlmSettingsManager.getRateLimitMs().toString()) }
    var defaultDestType by remember { mutableStateOf(VlmSettingsManager.getDefaultDestination()?.type ?: "") }
    var defaultDestId by remember { mutableStateOf(VlmSettingsManager.getDefaultDestination()?.id ?: "") }

    if (!isPresented) return

    BitchatBottomSheet(
        onDismissRequest = onDismiss
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
        ) {
            BitchatSheetTopBar(
                onClose = onDismiss,
                title = { BitchatSheetTitle("VLM API Settings") }
            )

            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    VlmStatusSection(enabled = enabled)
                }

                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column {
                                    Text(
                                        "Enable VLM API",
                                        fontFamily = BitchatFontFamily,
                                        fontWeight = FontWeight.Medium
                                    )
                                    Text(
                                        "Allow external apps to send messages",
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 12.sp,
                                        color = colorScheme.onSurface.copy(alpha = 0.6f)
                                    )
                                }
                                Switch(
                                    checked = enabled,
                                    onCheckedChange = { newEnabled ->
                                        enabled = newEnabled
                                        VlmSettingsManager.setEnabled(newEnabled)
                                    }
                                )
                            }
                        }
                    }
                }

                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                "HTTP Port",
                                fontFamily = BitchatFontFamily,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedTextField(
                                value = httpPort,
                                onValueChange = { port ->
                                    httpPort = port
                                    port.toIntOrNull()?.let { VlmSettingsManager.setHttpPort(it) }
                                },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                placeholder = { Text("8765") }
                            )
                            Text(
                                "ADB forwarding: adb forward tcp:$httpPort tcp:$httpPort",
                                fontFamily = BitchatFontFamily,
                                fontSize = 11.sp,
                                color = colorScheme.onSurface.copy(alpha = 0.5f)
                            )
                        }
                    }
                }

                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                "Default Destination",
                                fontFamily = BitchatFontFamily,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedTextField(
                                    value = defaultDestType,
                                    onValueChange = { defaultDestType = it },
                                    modifier = Modifier.weight(1f),
                                    placeholder = { Text("peer or channel") },
                                    singleLine = true
                                )
                                OutlinedTextField(
                                    value = defaultDestId,
                                    onValueChange = { defaultDestId = it },
                                    modifier = Modifier.weight(1f),
                                    placeholder = { Text("ID") },
                                    singleLine = true
                                )
                            }
                            Spacer(modifier = Modifier.height(8.dp))
                            Button(
                                onClick = {
                                    if (defaultDestType.isNotBlank() && defaultDestId.isNotBlank()) {
                                        VlmSettingsManager.setDefaultDestination(
                                            VlmDestination(defaultDestType, defaultDestId)
                                        )
                                    }
                                },
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text("Save Destination", fontFamily = BitchatFontFamily)
                            }
                            Text(
                                "Messages without explicit destination go here",
                                fontFamily = BitchatFontFamily,
                                fontSize = 11.sp,
                                color = colorScheme.onSurface.copy(alpha = 0.5f)
                            )
                        }
                    }
                }

                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column {
                                    Text(
                                        "Silence Mode",
                                        fontFamily = BitchatFontFamily,
                                        fontWeight = FontWeight.Medium
                                    )
                                    Text(
                                        "Pause all VLM messages",
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 12.sp,
                                        color = colorScheme.onSurface.copy(alpha = 0.6f)
                                    )
                                }
                                Switch(
                                    checked = silenceEnabled,
                                    onCheckedChange = { newSilence ->
                                        silenceEnabled = newSilence
                                        VlmSettingsManager.setSilenceEnabled(newSilence)
                                    }
                                )
                            }
                        }
                    }
                }

                item {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text(
                                "Rate Limit (ms)",
                                fontFamily = BitchatFontFamily,
                                fontWeight = FontWeight.Medium
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedTextField(
                                value = rateLimit,
                                onValueChange = { limit ->
                                    rateLimit = limit
                                    limit.toLongOrNull()?.let { VlmSettingsManager.setRateLimitMs(it) }
                                },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                placeholder = { Text("5000") }
                            )
                            Text(
                                "Minimum time between messages",
                                fontFamily = BitchatFontFamily,
                                fontSize = 11.sp,
                                color = colorScheme.onSurface.copy(alpha = 0.5f)
                            )
                        }
                    }
                }

                item {
                    VlmApiUsageInfo()
                }
            }
        }
    }
}

@Composable
private fun VlmStatusSection(enabled: Boolean) {
    val colorScheme = MaterialTheme.colorScheme
    val context = LocalContext.current

    val status by remember(enabled) {
        mutableStateOf(VlmMessageHandler.getStatus(context))
    }
    
    val wifiIp = status["wifi_ip"] as? String ?: "0.0.0.0"
    val hasValidWifi = wifiIp != "0.0.0.0"

    Surface(
        shape = RoundedCornerShape(12.dp),
        color = if (enabled && hasValidWifi) Color(0xFF34C759).copy(alpha = 0.15f)
                else colorScheme.surfaceVariant.copy(alpha = 0.2f)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .padding(2.dp)
                ) {
                    Surface(
                        shape = androidx.compose.foundation.shape.CircleShape,
                        color = if (enabled && hasValidWifi) Color(0xFF34C759)
                                else Color(0xFF8E8E93),
                        modifier = Modifier.fillMaxSize()
                    ) {}
                }
                Text(
                    when {
                        !enabled -> "VLM API Disabled"
                        !hasValidWifi -> "VLM API Active (No WiFi)"
                        else -> "VLM API Active"
                    },
                    fontFamily = BitchatFontFamily,
                    fontWeight = FontWeight.Bold,
                    color = if (enabled && hasValidWifi) Color(0xFF34C759)
                            else colorScheme.onSurface
                )
            }
            
            if (enabled && hasValidWifi) {
                Spacer(modifier = Modifier.height(12.dp))
                
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = Color(0xFF34C759).copy(alpha = 0.1f)
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            "Connect from PC:",
                            fontFamily = BitchatFontFamily,
                            fontSize = 11.sp,
                            color = colorScheme.onSurface.copy(alpha = 0.6f)
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            "http://$wifiIp:${status["http_port"]}",
                            fontFamily = BitchatFontFamily,
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFF34C759)
                        )
                    }
                }
                
                Spacer(modifier = Modifier.height(8.dp))
                
                Text(
                    "Peers: ${status["peers_count"]}",
                    fontFamily = BitchatFontFamily,
                    fontSize = 12.sp,
                    color = colorScheme.onSurface.copy(alpha = 0.7f)
                )
            } else if (enabled && !hasValidWifi) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    "Connect to WiFi to expose API",
                    fontFamily = BitchatFontFamily,
                    fontSize = 12.sp,
                    color = Color(0xFFFF9500),
                    fontWeight = FontWeight.Medium
                )
            }
        }
    }
}

@Composable
private fun VlmApiUsageInfo() {
    val colorScheme = MaterialTheme.colorScheme

    Surface(
        shape = RoundedCornerShape(12.dp),
        color = colorScheme.surfaceVariant.copy(alpha = 0.2f)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "API Usage",
                fontFamily = BitchatFontFamily,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            )
            Spacer(modifier = Modifier.height(12.dp))

            val endpoints = listOf(
                "POST /send/text" to "Send text message",
                "POST /send/image" to "Send image (multipart)",
                "POST /send/analysis" to "Send image + description",
                "GET /status" to "Get API status",
                "POST /silence" to "Toggle silence mode"
            )

            endpoints.forEach { (endpoint, desc) ->
                Text(
                    endpoint,
                    fontFamily = BitchatFontFamily,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Medium,
                    color = Color(0xFF5856D6)
                )
                Text(
                    "   $desc",
                    fontFamily = BitchatFontFamily,
                    fontSize = 11.sp,
                    color = colorScheme.onSurface.copy(alpha = 0.6f)
                )
                Spacer(modifier = Modifier.height(4.dp))
            }

            Spacer(modifier = Modifier.height(12.dp))
            Text(
                "Broadcast Intent: com.bitchat.android.VLM_API",
                fontFamily = BitchatFontFamily,
                fontSize = 10.sp,
                color = colorScheme.onSurface.copy(alpha = 0.5f)
            )
        }
    }
}
