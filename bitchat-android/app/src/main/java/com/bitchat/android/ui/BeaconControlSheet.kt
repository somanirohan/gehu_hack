package com.bitchat.android.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.ActivityCompat
import com.bitchat.android.R
import com.bitchat.android.model.Role
import com.bitchat.android.model.Shelter
import com.bitchat.android.model.ShelterStatus
import com.bitchat.android.services.AppStateStore
import com.google.android.gms.location.LocationServices
import com.google.android.gms.tasks.CancellationTokenSource

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BeaconControlSheet(
    isPresented: Boolean,
    shelters: List<AppStateStore.VerifiedShelter>,
    myPeerID: String,
    onUpdateCapacity: (shelterId: String, newCapacity: Int, newStatus: ShelterStatus) -> Unit,
    onPublishNewBeacon: (name: String, lat: Double, lon: Double, capacity: Int, role: Role, status: ShelterStatus) -> Unit,
    onDeleteBeacon: (Shelter) -> Unit,
    onDismiss: () -> Unit
) {
    if (!isPresented) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val context = LocalContext.current

    // Find any shelter originated by this node
    val myShelters = remember(shelters, myPeerID) {
        shelters.map { it.shelter }.filter { it.originPeerID == myPeerID }
    }
    // a stood-down (CLOSED) beacon is finished: show the "start a new beacon" form instead
    val activeBeacon = myShelters.firstOrNull { it.status != ShelterStatus.CLOSED }

    var liveCapacity by remember(activeBeacon?.id, activeBeacon?.capacity) {
        mutableIntStateOf(activeBeacon?.capacity ?: 50)
    }
    var liveStatus by remember(activeBeacon?.id, activeBeacon?.status) {
        mutableStateOf(activeBeacon?.status ?: ShelterStatus.OPEN)
    }
    var updateSuccessMessage by remember { mutableStateOf<String?>(null) }

    // Deploy form state if no active beacon
    var newName by remember { mutableStateOf("") }
    var newLat by remember { mutableStateOf("") }
    var newLon by remember { mutableStateOf("") }
    var newCap by remember { mutableStateOf("50") }

    fun fetchCurrentGps() {
        val havePermission = ActivityCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED ||
            ActivityCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_COARSE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
        if (!havePermission) return
        val client = LocationServices.getFusedLocationProviderClient(context)
        val cancellation = CancellationTokenSource()
        client.getCurrentLocation(
            com.google.android.gms.location.Priority.PRIORITY_HIGH_ACCURACY,
            cancellation.token
        ).addOnSuccessListener { loc ->
            if (loc != null) {
                newLat = String.format(java.util.Locale.US, "%.6f", loc.latitude)
                newLon = String.format(java.util.Locale.US, "%.6f", loc.longitude)
            }
        }
    }

    LaunchedEffect(Unit) {
        if (activeBeacon == null && newLat.isBlank()) {
            fetchCurrentGps()
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = "🚨",
                    fontSize = 26.sp,
                    modifier = Modifier.padding(end = 10.dp)
                )
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "SOS Beacon Control Center",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "Live capacity & real-time control for your emergency beacon",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }

            Spacer(Modifier.height(14.dp))

            if (updateSuccessMessage != null) {
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 12.dp)
                ) {
                    Row(
                        modifier = Modifier.padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            Icons.Default.CheckCircle,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = updateSuccessMessage ?: "",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }
            }

            if (activeBeacon != null) {
                // Manage Active Beacon Card
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                    ),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = activeBeacon.name,
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold
                                )
                                Text(
                                    text = "📍 ${String.format(java.util.Locale.US, "%.5f", activeBeacon.lat)}, ${String.format(java.util.Locale.US, "%.5f", activeBeacon.lon)}",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Surface(
                                color = when (liveStatus) {
                                    ShelterStatus.OPEN -> Color(0xFF2F6F54)
                                    ShelterStatus.FULL -> Color(0xFFC23A22)
                                    ShelterStatus.CLOSED -> Color(0xFF8C8F86)
                                },
                                shape = RoundedCornerShape(12.dp)
                            ) {
                                Text(
                                    text = liveStatus.name,
                                    color = Color.White,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                                )
                            }
                        }

                        HorizontalDivider(Modifier.padding(vertical = 12.dp))

                        Text(
                            text = "LIVE EVACUEE CAPACITY",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Spacer(Modifier.height(6.dp))

                        // Large capacity counter & steppers
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Center,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            OutlinedButton(
                                onClick = { liveCapacity = (liveCapacity - 10).coerceAtLeast(0) },
                                shape = RoundedCornerShape(8.dp)
                            ) { Text("-10") }

                            Spacer(Modifier.width(4.dp))

                            OutlinedButton(
                                onClick = { liveCapacity = (liveCapacity - 1).coerceAtLeast(0) },
                                shape = RoundedCornerShape(8.dp)
                            ) { Text("-1") }

                            Spacer(Modifier.width(12.dp))

                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(
                                    text = "$liveCapacity",
                                    fontSize = 32.sp,
                                    fontWeight = FontWeight.ExtraBold,
                                    color = MaterialTheme.colorScheme.primary
                                )
                                Text(
                                    text = "people",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }

                            Spacer(Modifier.width(12.dp))

                            OutlinedButton(
                                onClick = { liveCapacity += 1 },
                                shape = RoundedCornerShape(8.dp)
                            ) { Text("+1") }

                            Spacer(Modifier.width(4.dp))

                            OutlinedButton(
                                onClick = { liveCapacity += 10 },
                                shape = RoundedCornerShape(8.dp)
                            ) { Text("+10") }
                        }

                        Spacer(Modifier.height(14.dp))

                        Text(
                            text = "BEACON OPERATIONAL STATUS",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold
                        )
                        Spacer(Modifier.height(6.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            ShelterStatus.entries.forEach { st ->
                                FilterChip(
                                    selected = liveStatus == st,
                                    onClick = { liveStatus = st },
                                    label = { Text(st.name) }
                                )
                            }
                        }

                        Spacer(Modifier.height(16.dp))

                        Button(
                            onClick = {
                                onUpdateCapacity(activeBeacon.id, liveCapacity, liveStatus)
                                updateSuccessMessage = "Live capacity updated to $liveCapacity ($liveStatus) & broadcasted!"
                            },
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            Text("💾 Update Live Capacity & Broadcast")
                        }

                        Spacer(Modifier.height(8.dp))

                        OutlinedButton(
                            onClick = {
                                onDeleteBeacon(activeBeacon)
                                updateSuccessMessage = "Beacon stood down. The control room map will remove it on the next sync."
                            },
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme.colorScheme.error
                            ),
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            Text("🛑 Stand Down / Close Beacon")
                        }
                    }
                }
            } else {
                // Deploy New Beacon Section
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                    ),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "No active SOS beacon originated by this phone.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(Modifier.height(12.dp))
                        Text(
                            text = "Start an SOS Beacon to broadcast your relief/evacuation capacity to the admin COP map:",
                            style = MaterialTheme.typography.bodySmall
                        )

                        Spacer(Modifier.height(12.dp))

                        OutlinedTextField(
                            value = newName,
                            onValueChange = { newName = it },
                            label = { Text("Beacon Name (e.g. Clock Tower Shelter)") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(Modifier.height(8.dp))

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            OutlinedTextField(
                                value = newLat,
                                onValueChange = { newLat = it },
                                label = { Text("Latitude") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f)
                            )
                            Spacer(Modifier.width(8.dp))
                            OutlinedTextField(
                                value = newLon,
                                onValueChange = { newLon = it },
                                label = { Text("Longitude") },
                                singleLine = true,
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                modifier = Modifier.weight(1f)
                            )
                            IconButton(onClick = { fetchCurrentGps() }) {
                                Icon(Icons.Default.MyLocation, contentDescription = "Use My GPS")
                            }
                        }

                        Spacer(Modifier.height(8.dp))

                        OutlinedTextField(
                            value = newCap,
                            onValueChange = { newCap = it.filter { c -> c.isDigit() } },
                            label = { Text("Shelter Capacity (People)") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(Modifier.height(14.dp))

                        Button(
                            onClick = {
                                val la = newLat.toDoubleOrNull() ?: return@Button
                                val lo = newLon.toDoubleOrNull() ?: return@Button
                                val cap = newCap.toIntOrNull() ?: 50
                                val title = newName.trim().ifBlank { "SOS Beacon ${System.currentTimeMillis() % 10000}" }
                                onPublishNewBeacon(title, la, lo, cap, Role.CIVILIAN, ShelterStatus.OPEN)
                                updateSuccessMessage = "SOS Beacon deployed! You can now control its capacity live."
                            },
                            enabled = newLat.isNotBlank() && newLon.isNotBlank(),
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(10.dp)
                        ) {
                            Text("🚨 Launch SOS Beacon & Broadcast Capacity")
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
        }
    }
}
