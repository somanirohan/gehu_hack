package com.bitchat.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.bitchat.android.services.SyncPreferences
import com.bitchat.android.util.SyncWorkScheduler
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
    val prefs = SyncPreferences.getInstance(androidx.compose.ui.platform.LocalContext.current)

    var enabled by remember { mutableStateOf(prefs.enabled) }
    var url by remember { mutableStateOf(prefs.endpointUrl) }
    var useTor by remember { mutableStateOf(prefs.useTor) }
    var ingestEnabled by remember { mutableStateOf(prefs.localIngestEnabled) }
    var port by remember { mutableStateOf(prefs.localIngestPort.toString()) }

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
                onCheckedChange = { enabled = it; prefs.enabled = it }
            )

            OutlinedTextField(
                value = url,
                onValueChange = { url = it; prefs.endpointUrl = it },
                label = { Text("REST endpoint URL (HTTPS recommended)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            Spacer(Modifier.height(8.dp))
            ToggleRow(
                label = "Route via local Tor (Arti) when available",
                checked = useTor,
                onCheckedChange = { useTor = it; prefs.useTor = it }
            )
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            ToggleRow(
                label = "Run local ingest server (self-contained demo)",
                checked = ingestEnabled,
                onCheckedChange = { ingestEnabled = it; prefs.localIngestEnabled = it }
            )
            OutlinedTextField(
                value = port,
                onValueChange = { port = it.filter { c -> c.isDigit() }; prefs.localIngestPort = port.toIntOrNull() ?: prefs.localIngestPort },
                label = { Text("Local port (POST /ingest)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(Modifier.height(12.dp))
            val ctx = androidx.compose.ui.platform.LocalContext.current
            Button(
                onClick = { SyncWorkScheduler.scheduleFlush(ctx) },
                enabled = enabled && url.isNotBlank()
            ) { Text("Send now") }

            Spacer(Modifier.height(8.dp))
            val lastAt = prefs.lastSyncedAt
            val lastStr = if (lastAt > 0) DateFormat.getDateTimeInstance().format(Date(lastAt)) else "never"
            val err = prefs.lastSyncError
            Text("Last sync: $lastStr", style = MaterialTheme.typography.bodySmall)
            if (!err.isNullOrBlank()) {
                Text("Last error: $err", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(16.dp))
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