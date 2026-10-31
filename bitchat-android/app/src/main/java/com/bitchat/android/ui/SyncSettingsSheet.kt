package com.bitchat.android.ui

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.bitchat.android.net.CivilizationSyncClient
import com.bitchat.android.net.DisasterAiClient
import com.bitchat.android.services.AppStateStore
import com.bitchat.android.services.SyncBundleBuilder
import com.bitchat.android.services.SyncPreferences
import com.bitchat.android.util.SyncWorkScheduler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.DateFormat
import java.util.Date

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SyncSettingsSheet(
    isPresented: Boolean,
    onDismiss: () -> Unit
) {
    if (!isPresented) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs = remember { SyncPreferences.getInstance(ctx) }

    var enabled by remember { mutableStateOf(prefs.enabled) }
    var url by remember { mutableStateOf(prefs.endpointUrl) }
    var useTor by remember { mutableStateOf(prefs.useTor) }
    var ingestEnabled by remember { mutableStateOf(prefs.localIngestEnabled) }
    var port by remember { mutableStateOf(prefs.localIngestPort.toString()) }

    var isSending by remember { mutableStateOf(false) }
    var syncResultStatus by remember { mutableStateOf<Pair<Boolean, String>?>(null) }
    var lastSyncedAtState by remember { mutableStateOf(prefs.lastSyncedAt) }
    var lastSyncErrorState by remember { mutableStateOf(prefs.lastSyncError) }

    val aiClient = remember { DisasterAiClient(ctx) }
    var aiServerUrl by remember { mutableStateOf(aiClient.serverUrl) }
    var isTestingAiServer by remember { mutableStateOf(false) }
    var aiTestResult by remember { mutableStateOf<Pair<Boolean, String>?>(null) }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            Text("Civilization Bridge", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(8.dp))
            Text(
                "On internet reconnect, batch-upload your incident + shelter log to a configurable REST endpoint. " +
                    "Disabled by default; everything you submit comes only from mesh-derived data.",
                style = MaterialTheme.typography.bodySmall
            )

            Spacer(Modifier.height(12.dp))
            ToggleRow(
                label = "Enable sync on reconnect",
                checked = enabled,
                onCheckedChange = {
                    enabled = it
                    prefs.enabled = it
                }
            )

            OutlinedTextField(
                value = url,
                onValueChange = {
                    url = it
                    prefs.endpointUrl = it
                    syncResultStatus = null
                },
                label = { Text("REST endpoint URL (HTTPS recommended)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(8.dp))
            ToggleRow(
                label = "Route via local Tor (Arti) when available",
                checked = useTor,
                onCheckedChange = {
                    useTor = it
                    prefs.useTor = it
                }
            )
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            ToggleRow(
                label = "Run local ingest server (self-contained demo)",
                checked = ingestEnabled,
                onCheckedChange = {
                    ingestEnabled = it
                    prefs.localIngestEnabled = it
                }
            )
            OutlinedTextField(
                value = port,
                onValueChange = {
                    port = it.filter { c -> c.isDigit() }
                    prefs.localIngestPort = port.toIntOrNull() ?: prefs.localIngestPort
                },
                label = { Text("Local port (POST /ingest)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(14.dp))

            Button(
                onClick = {
                    val trimmedUrl = url.trim()
                    if (trimmedUrl.isEmpty() || (!trimmedUrl.startsWith("http://", ignoreCase = true) && !trimmedUrl.startsWith("https://", ignoreCase = true))) {
                        val errMsg = "Invalid URL: Must start with http:// or https://"
                        syncResultStatus = Pair(false, errMsg)
                        Toast.makeText(ctx, errMsg, Toast.LENGTH_SHORT).show()
                        return@Button
                    }

                    if (!enabled) {
                        enabled = true
                        prefs.enabled = true
                    }
                    prefs.endpointUrl = trimmedUrl

                    isSending = true
                    syncResultStatus = null

                    scope.launch {
                        val (success, errorMsg) = withContext(Dispatchers.IO) {
                            try {
                                val shelters = AppStateStore.shelters.value
                                val messages = AppStateStore.publicMessages.value.takeLast(200)
                                val incidents = SyncBundleBuilder.extractIncidents(messages)
                                val bundle = SyncBundleBuilder.build(shelters, incidents)

                                val client = CivilizationSyncClient(ctx)
                                val ok = client.postBundle(bundle.json)
                                if (ok) {
                                    Pair(true, null)
                                } else {
                                    Pair(false, prefs.lastSyncError ?: "Request failed")
                                }
                            } catch (e: Exception) {
                                prefs.lastSyncError = e.message ?: "Unknown error"
                                Pair(false, e.message ?: "Connection error")
                            }
                        }

                        isSending = false
                        lastSyncedAtState = prefs.lastSyncedAt
                        lastSyncErrorState = prefs.lastSyncError

                        if (success) {
                            val msg = "Sync successful! Endpoint reachable."
                            syncResultStatus = Pair(true, msg)
                            Toast.makeText(ctx, "✓ $msg", Toast.LENGTH_SHORT).show()
                            SyncWorkScheduler.scheduleFlush(ctx)
                        } else {
                            val msg = "Sync failed: ${errorMsg ?: "Could not connect to server"}"
                            syncResultStatus = Pair(false, msg)
                            Toast.makeText(ctx, "✕ $msg", Toast.LENGTH_LONG).show()
                        }
                    }
                },
                enabled = !isSending && url.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) {
                if (isSending) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        color = MaterialTheme.colorScheme.onPrimary,
                        strokeWidth = 2.dp
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("Connecting & Syncing...")
                } else {
                    Text("Send / Test now")
                }
            }

            syncResultStatus?.let { (isSuccess, message) ->
                Spacer(Modifier.height(10.dp))
                Surface(
                    color = if (isSuccess) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = if (isSuccess) "✓ $message" else "✕ $message",
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (isSuccess) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer
                        )
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            val lastAt = lastSyncedAtState
            val lastStr = if (lastAt > 0) DateFormat.getDateTimeInstance().format(Date(lastAt)) else "never"
            val err = lastSyncErrorState
            Text("Last sync: $lastStr", style = MaterialTheme.typography.bodySmall)
            if (!err.isNullOrBlank()) {
                Text("Last error: $err", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }

            HorizontalDivider(Modifier.padding(vertical = 14.dp))

            // AI Chatbot Server Section below Civilization Bridge
            Text("AI Chatbot Server", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                "Configure the backend server URL for the Disaster AI Chatbot. The chatbot queries this endpoint to generate emergency and survival advice.",
                style = MaterialTheme.typography.bodySmall
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = aiServerUrl,
                onValueChange = {
                    aiServerUrl = it
                    aiClient.serverUrl = it
                    aiTestResult = null
                },
                label = { Text("AI Server URL (e.g. http://10.0.2.2:8800)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = {
                    val trimmed = aiServerUrl.trim()
                    if (trimmed.isEmpty() || (!trimmed.startsWith("http://", ignoreCase = true) && !trimmed.startsWith("https://", ignoreCase = true))) {
                        val errMsg = "Invalid URL: Must start with http:// or https://"
                        aiTestResult = Pair(false, errMsg)
                        Toast.makeText(ctx, errMsg, Toast.LENGTH_SHORT).show()
                        return@Button
                    }
                    aiClient.serverUrl = trimmed
                    isTestingAiServer = true
                    aiTestResult = null
                    scope.launch {
                        val ok = withContext(Dispatchers.IO) {
                            aiClient.checkHealth()
                        }
                        isTestingAiServer = false
                        aiTestResult = if (ok) {
                            Pair(true, "AI backend server is online & reachable!")
                        } else {
                            Pair(false, "Cannot connect to AI backend at $trimmed")
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                if (isTestingAiServer) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("Testing AI Server...")
                } else {
                    Text("Test AI Server Connection")
                }
            }

            aiTestResult?.let { (isSuccess, message) ->
                Spacer(Modifier.height(8.dp))
                Surface(
                    color = if (isSuccess) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
                    shape = MaterialTheme.shapes.small,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = if (isSuccess) "✓ $message" else "✕ $message",
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (isSuccess) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                    )
                }
            }

            Spacer(Modifier.height(20.dp))
        }
    }
}

@Composable
private fun ToggleRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}