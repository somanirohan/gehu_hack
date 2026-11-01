package com.bitchat.android.util

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationManager
import androidx.core.content.ContextCompat
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Single place that resolves the device's position for geo-tagging chat messages.
 *
 * Order: a recent cached fix (fast) → a fresh fix (up to [FRESH_FIX_TIMEOUT_MS]) →
 * any older cached fix from GPS/network providers. Returns null when permission is
 * missing or no position can be obtained at all.
 */
object LocationFetcher {
    private const val MAX_CACHED_AGE_MS = 2 * 60_000L
    private const val FRESH_FIX_TIMEOUT_MS = 6_000L

    fun hasPermission(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    suspend fun fetch(context: Context): Pair<Double, Double>? = withContext(Dispatchers.IO) {
        if (!hasPermission(context)) return@withContext null
        val app = context.applicationContext
        val client = try {
            LocationServices.getFusedLocationProviderClient(app)
        } catch (_: Exception) { null }

        val cached: Location? = client?.let { awaitTask { cb -> it.lastLocation.addOnCompleteListener { t -> cb(if (t.isSuccessful) t.result else null) } } }
        if (cached != null && System.currentTimeMillis() - cached.time <= MAX_CACHED_AGE_MS) {
            return@withContext cached.latitude to cached.longitude
        }

        val fresh: Location? = client?.let { c ->
            val cts = CancellationTokenSource()
            val result = withTimeoutOrNull(FRESH_FIX_TIMEOUT_MS) {
                awaitTask { cb ->
                    c.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, cts.token)
                        .addOnCompleteListener { t -> cb(if (t.isSuccessful) t.result else null) }
                }
            }
            if (result == null) cts.cancel()
            result
        }
        if (fresh != null) return@withContext fresh.latitude to fresh.longitude

        val fallback = cached ?: run {
            val lm = app.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            val gps = runCatching { lm?.getLastKnownLocation(LocationManager.GPS_PROVIDER) }.getOrNull()
            val net = runCatching { lm?.getLastKnownLocation(LocationManager.NETWORK_PROVIDER) }.getOrNull()
            listOfNotNull(gps, net).maxByOrNull { it.time }
        }
        fallback?.let { it.latitude to it.longitude }
    }

    /** Builds the ` geo:lat,lon` suffix the dashboard and map parse. */
    fun geoTag(coords: Pair<Double, Double>): String =
        " geo:%.5f,%.5f".format(java.util.Locale.US, coords.first, coords.second)

    private suspend fun awaitTask(register: ((Location?) -> Unit) -> Unit): Location? {
        val deferred = CompletableDeferred<Location?>()
        try {
            register { deferred.complete(it) }
        } catch (_: Exception) {
            deferred.complete(null)
        }
        return deferred.await()
    }
}
