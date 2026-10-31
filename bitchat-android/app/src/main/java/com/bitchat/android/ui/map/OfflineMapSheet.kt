package com.bitchat.android.ui.map

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.location.Location
import android.os.Looper
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.app.ActivityCompat
import com.bitchat.android.model.Role
import com.bitchat.android.model.Shelter
import com.bitchat.android.model.ShelterStatus
import com.bitchat.android.services.AppStateStore
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.mylocation.GpsMyLocationProvider
import org.osmdroid.views.overlay.mylocation.MyLocationNewOverlay

/**
 * Live emergency Common Operating Picture backed by osmdroid (OpenStreetMap raster tiles).
 *
 * - Tiles: MAPNIK raster source with offline caching.
 * - Own position: [FusedLocationProviderClient] feeds [MyLocationNewOverlay] (blue GPS dot).
 * - Incidents: role-colored markers parsed from broadcast messages carrying a `geo:lat,lon` tag.
 * - Shelters: registry markers with verification status from [com.bitchat.android.services.ShelterRegistry].
 * - Detected peers: nearby nodes detected by mesh with roles (Civilian, Ambulance, Shelter, Drone, Rescue).
 * - Admin role: excluded from map markers.
 */
data class IncidentMarker(
    val id: String,
    val lat: Double,
    val lon: Double,
    val role: Role,
    val label: String
)

data class DetectedPeer(
    val peerId: String,
    val nickname: String,
    val role: Role,
    val lastLat: Double? = null,
    val lastLon: Double? = null
)

data class OwnPosition(val lat: Double, val lon: Double)

private const val SCENE_CENTER_LAT = 11.0168
private const val SCENE_CENTER_LON = 76.9558
private const val DEFAULT_ZOOM = 15.0

@SuppressLint("MissingPermission")
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OfflineMapSheet(
    shelters: List<AppStateStore.VerifiedShelter>,
    incidents: List<IncidentMarker>,
    detectedPeers: List<DetectedPeer> = emptyList(),
    ownPosition: OwnPosition?,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val context = LocalContext.current

    // Admin role is filtered out completely from the map
    val visibleShelters = remember(shelters) {
        shelters.filter { it.shelter.role != Role.ADMIN }
    }
    val visibleIncidents = remember(incidents) {
        incidents.filter { it.role != Role.ADMIN }
    }
    val visiblePeers = remember(detectedPeers) {
        detectedPeers.filter { it.role != Role.ADMIN && it.role != Role.UNSET }
    }

    // Configure osmdroid user agent once
    DisposableEffect(Unit) {
        try {
            Configuration.getInstance().apply {
                userAgentValue = "bitchat-android"
                osmdroidBasePath = context.cacheDir
                osmdroidTileCache = java.io.File(context.cacheDir, "osm_tiles").apply { mkdirs() }
                // Allow tile caching so the map keeps working briefly after losing internet
                expirationOverrideDuration = 30L * 24 * 60 * 60 * 1000L
            }
        } catch (_: Exception) { }
        onDispose { }
    }

    var hasLocationPermission by remember {
        mutableStateOf(
            ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                ActivityCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        hasLocationPermission = perms.values.any { it }
    }
    LaunchedEffect(Unit) {
        if (!hasLocationPermission) {
            permissionLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
                )
            )
        }
    }

    // Live GPS
    var livePosition by remember { mutableStateOf<OwnPosition?>(null) }
    DisposableEffect(hasLocationPermission) {
        if (!hasLocationPermission) {
            onDispose { }
        } else {
            val client = LocationServices.getFusedLocationProviderClient(context)
            val request = LocationRequest.Builder(5000L)
                .setMinUpdateDistanceMeters(5f)
                .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
                .build()
            val callback = object : LocationCallback() {
                override fun onLocationResult(result: LocationResult) {
                    result.lastLocation?.let { loc ->
                        livePosition = OwnPosition(loc.latitude, loc.longitude)
                    }
                }
            }
            try {
                client.requestLocationUpdates(request, callback, Looper.getMainLooper())
                client.lastLocation.addOnSuccessListener { loc ->
                    loc?.let { livePosition = OwnPosition(it.latitude, it.longitude) }
                }
            } catch (_: Exception) { }
            onDispose {
                try { client.removeLocationUpdates(callback) } catch (_: Exception) { }
            }
        }
    }

    // The MapView we keep across recompositions
    var mapView by remember { mutableStateOf<MapView?>(null) }
    var hasCenteredCamera by remember { mutableStateOf(false) }

    // MapView lifecycle management
    DisposableEffect(mapView) {
        mapView?.onResume()
        onDispose {
            mapView?.onPause()
        }
    }

    // Center camera ONCE when initial position is known without fighting user zoom later
    LaunchedEffect(livePosition, ownPosition, mapView) {
        val mv = mapView ?: return@LaunchedEffect
        if (!hasCenteredCamera) {
            val focusPos = livePosition
                ?: ownPosition
                ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
            mv.controller.setCenter(GeoPoint(focusPos.lat, focusPos.lon))
            mv.controller.setZoom(DEFAULT_ZOOM)
            hasCenteredCamera = true
        }
    }

    var lastRenderedSig by remember { mutableStateOf("") }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        dragHandle = null
    ) {
        Box(modifier = Modifier.fillMaxWidth().height(600.dp).background(Color(0xFF0B1018))) {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { ctx ->
                    MapView(ctx).apply {
                        setTileSource(TileSourceFactory.MAPNIK)
                        setMultiTouchControls(true)
                        setBuiltInZoomControls(false)
                        isTilesScaledToDpi = true
                        minZoomLevel = 3.0
                        maxZoomLevel = 20.0
                        isFlingEnabled = true
                        isClickable = true
                        controller.setZoom(DEFAULT_ZOOM)
                        val startPos = ownPosition
                            ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
                        controller.setCenter(GeoPoint(startPos.lat, startPos.lon))

                        // Show the user a real GPS dot when we have permission
                        if (hasLocationPermission) {
                            try {
                                val myLoc = MyLocationNewOverlay(GpsMyLocationProvider(ctx), this)
                                myLoc.enableMyLocation()
                                // DO NOT enableFollowLocation() - it fights manual pinch zoom and panning!
                                overlays.add(myLoc)
                            } catch (_: Exception) { }
                        }
                        mapView = this
                    }
                },
                update = { mv ->
                    val myLoc = livePosition ?: ownPosition
                    val currentSig = "${visibleShelters.size}_${visibleIncidents.size}_${visiblePeers.size}_" +
                        "${visibleIncidents.map { it.id }.hashCode()}_${visibleShelters.map { it.shelter.id }.hashCode()}_" +
                        "${visiblePeers.map { it.peerId }.hashCode()}_${myLoc?.lat?.toInt()}_${myLoc?.lon?.toInt()}"

                    if (currentSig != lastRenderedSig) {
                        lastRenderedSig = currentSig
                        mv.overlays.removeAll { it is Marker }

                        visibleShelters.forEach { vs ->
                            val s: Shelter = vs.shelter
                            val emoji = roleEmoji(s.role)
                            val bgArgb = roleAccentArgb(s.role)
                            val ringTint = when {
                                vs.verified -> reachTintArgb(ReachTint.REACHED)
                                else -> reachTintArgb(ReachTint.UNKNOWN)
                            }
                            val distLabel = myLoc?.let { loc ->
                                val arr = FloatArray(1)
                                Location.distanceBetween(loc.lat, loc.lon, s.lat, s.lon, arr)
                                " · ${formatDistance(arr[0])}"
                            } ?: ""
                            val m = Marker(mv).apply {
                                position = GeoPoint(s.lat, s.lon)
                                title = "${roleEmoji(s.role)} ${s.name} (${s.capacity}) · ${s.status.name.lowercase()}$distLabel${if (vs.verified) " ✓" else ""}"
                                icon = buildEmojiMarker(context, emoji, bgArgb, ringTint)
                                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                            }
                            mv.overlays.add(m)
                        }

                        visibleIncidents.forEach { inc ->
                            val emoji = roleEmoji(inc.role)
                            val bgArgb = roleAccentArgb(inc.role)
                            val reachTint = reachTintArgb(ReachTint.UNKNOWN)
                            val distLabel = myLoc?.let { loc ->
                                val arr = FloatArray(1)
                                Location.distanceBetween(loc.lat, loc.lon, inc.lat, inc.lon, arr)
                                " · ${formatDistance(arr[0])}"
                            } ?: ""
                            val m = Marker(mv).apply {
                                position = GeoPoint(inc.lat, inc.lon)
                                title = "$emoji ${inc.label}$distLabel"
                                icon = buildEmojiMarker(context, emoji, bgArgb, reachTint)
                                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                            }
                            mv.overlays.add(m)
                        }

                        // Nearby detected peers with non-admin roles
                        visiblePeers.forEach { peer ->
                            val emoji = roleEmoji(peer.role)
                            val bgArgb = roleAccentArgb(peer.role)
                            val ringTint = reachTintArgb(ReachTint.REACHED)
                            val (peerLat, peerLon) = if (peer.lastLat != null && peer.lastLon != null) {
                                peer.lastLat to peer.lastLon
                            } else {
                                val base = myLoc ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
                                val seed = peer.peerId.hashCode()
                                val angle = Math.toRadians((Math.abs(seed) % 360).toDouble())
                                val distMeters = 30.0 + (Math.abs(seed / 360) % 45)
                                val dLat = (distMeters * Math.cos(angle)) / 111000.0
                                val dLon = (distMeters * Math.sin(angle)) / (111000.0 * Math.cos(Math.toRadians(base.lat)))
                                (base.lat + dLat) to (base.lon + dLon)
                            }
                            val distLabel = myLoc?.let { loc ->
                                val arr = FloatArray(1)
                                Location.distanceBetween(loc.lat, loc.lon, peerLat, peerLon, arr)
                                " · ${formatDistance(arr[0])}"
                            } ?: ""
                            val m = Marker(mv).apply {
                                position = GeoPoint(peerLat, peerLon)
                                title = "$emoji ${peer.nickname} (${Role.displayLabel(peer.role)})$distLabel"
                                snippet = "Detected nearby node · ${peer.peerId.take(8)}"
                                icon = buildEmojiMarker(context, emoji, bgArgb, ringTint)
                                setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                            }
                            mv.overlays.add(m)
                        }

                        mv.invalidate()
                    }
                }
            )

            // Top overlay: title bar + close button
            Surface(
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
                tonalElevation = 4.dp,
                shape = RoundedCornerShape(0.dp)
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                        .align(Alignment.TopCenter),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "Live Map ${livePosition?.let { "(you @ ${"%.4f".format(it.lat)}, ${"%.4f".format(it.lon)})" } ?: ""}",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f)
                    )
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Filled.Close, contentDescription = "Close map")
                    }
                }
            }

            // Zoom Controls (+) and (-)
            if (mapView != null) {
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(end = 16.dp, bottom = 84.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    FloatingActionButton(
                        onClick = { mapView?.controller?.zoomIn() },
                        modifier = Modifier.size(44.dp),
                        shape = CircleShape,
                        containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.95f),
                        contentColor = MaterialTheme.colorScheme.onSurface
                    ) {
                        Icon(Icons.Filled.Add, contentDescription = "Zoom In", modifier = Modifier.size(20.dp))
                    }
                    FloatingActionButton(
                        onClick = { mapView?.controller?.zoomOut() },
                        modifier = Modifier.size(44.dp),
                        shape = CircleShape,
                        containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.95f),
                        contentColor = MaterialTheme.colorScheme.onSurface
                    ) {
                        Icon(Icons.Filled.Remove, contentDescription = "Zoom Out", modifier = Modifier.size(20.dp))
                    }
                }
            }

            // Recenter floating button
            if (mapView != null) {
                FloatingActionButton(
                    onClick = {
                        val mv = mapView ?: return@FloatingActionButton
                        val target = livePosition
                            ?: ownPosition
                            ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
                        mv.controller.animateTo(GeoPoint(target.lat, target.lon))
                        mv.controller.setZoom(DEFAULT_ZOOM.coerceAtLeast(mv.zoomLevelDouble))
                    },
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(16.dp)
                ) {
                    Icon(Icons.Filled.MyLocation, contentDescription = "My location")
                }
            }
        }
    }
}

/** Parse a `geo:lat,lon` tag from arbitrary message content. */
fun parseGeoTag(content: String): Pair<Double, Double>? {
    val regex = Regex("geo:(-?\\d+(?:\\.\\d+)?),(-?\\d+(?:\\.\\d+)?)")
    val m = regex.find(content) ?: return null
    val lat = m.groupValues[1].toDoubleOrNull() ?: return null
    val lon = m.groupValues[2].toDoubleOrNull() ?: return null
    return lat to lon
}