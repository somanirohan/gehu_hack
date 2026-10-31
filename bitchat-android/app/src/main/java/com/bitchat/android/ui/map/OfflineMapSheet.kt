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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.MyLocation
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
 * - Tiles: MAPNIK raster source. Internet fetches live tiles; cached tiles are reused
 *   offline, so the map degrades gracefully if connectivity drops mid-mission.
 * - Own position: [FusedLocationProviderClient] feeds [MyLocationNewOverlay] (the blue GPS
 *   dot) plus a [LocationCallback] that drives the title "you @ lat, lon" line.
 * - Incidents: role-colored markers parsed from broadcast messages carrying a
 *   `geo:lat,lon` tag.
 * - Shelters: registry markers with verification status from
 *   [com.bitchat.android.services.ShelterRegistry].
 */
data class IncidentMarker(
    val id: String,
    val lat: Double,
    val lon: Double,
    val role: Role,
    val label: String
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
    ownPosition: OwnPosition?,
    onDismiss: () -> Unit
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val context = LocalContext.current

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
    var needsCameraTarget by remember { mutableStateOf(ownPosition == null) }

    LaunchedEffect(needsCameraTarget, livePosition, ownPosition) {
        val mv = mapView ?: return@LaunchedEffect
        if (needsCameraTarget) {
            val focusPos = livePosition
                ?: ownPosition
                ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
            mv.controller.setCenter(GeoPoint(focusPos.lat, focusPos.lon))
            mv.controller.setZoom(DEFAULT_ZOOM)
            needsCameraTarget = false
        }
    }

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
                        controller.setZoom(DEFAULT_ZOOM)
                        val startPos = ownPosition
                            ?: OwnPosition(SCENE_CENTER_LAT, SCENE_CENTER_LON)
                        controller.setCenter(GeoPoint(startPos.lat, startPos.lon))
                        // Show the user a real GPS dot when we have permission
                        if (hasLocationPermission) {
                            try {
                                val myLoc = MyLocationNewOverlay(GpsMyLocationProvider(ctx), this)
                                myLoc.enableMyLocation()
                                myLoc.enableFollowLocation()
                                overlays.add(myLoc)
                            } catch (_: Exception) { }
                        }
                        mapView = this
                    }
                },
                update = { mv ->
                    val myLoc = livePosition ?: ownPosition
                    mv.overlays.removeAll { it is Marker }

                    shelters.forEach { vs ->
                        val s: Shelter = vs.shelter
                        val emoji = roleEmoji(s.role)
                        val bgArgb = roleAccentArgb(s.role)
                        val ringTint = when {
                            vs.verified -> reachTintArgb(com.bitchat.android.ui.map.ReachTint.REACHED)
                            else -> reachTintArgb(com.bitchat.android.ui.map.ReachTint.UNKNOWN)
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
                    
                    incidents.forEach { inc ->
                        val emoji = roleEmoji(inc.role)
                        val bgArgb = roleAccentArgb(inc.role)
                        val reachTint = reachTintArgb(com.bitchat.android.ui.map.ReachTint.UNKNOWN)
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
                    mv.invalidate()
                }
            )

            // Top overlay: title bar + close button (osmdroid renders over everything)
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