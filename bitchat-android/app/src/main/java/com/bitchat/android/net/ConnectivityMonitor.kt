package com.bitchat.android.net

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Reports whether general internet connectivity (Wi-Fi / Cellular / Ethernet) is
 * available, regardless of mesh activity. Used by [SyncFlushWorker] to publish
 * local incident and shelter logs back to a configurable REST endpoint when the
 * node "returns to civilization".
 *
 * Mirrors are NOT triggered by Wi-Fi Aware data subscriptions: those are local
 * NAN clusters without real internet. Only [NetworkCapabilities.NET_CAPABILITY_VALIDATED]
 * adds count.
 */
class ConnectivityMonitor private constructor(context: Context) {

    companion object {
        private const val TAG = "ConnectivityMonitor"
        private const val NET_CAPS_VALIDATED_MIN = "NET_CAPABILITY_VALIDATED"
        @Volatile private var instance: ConnectivityMonitor? = null
        fun getInstance(context: Context): ConnectivityMonitor =
            instance ?: synchronized(this) {
                instance ?: ConnectivityMonitor(context.applicationContext).also { instance = it }
            }
    }

    private val appContext = context.applicationContext
    private val connectivity by lazy {
        appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    }
    private val _hasInternet = MutableStateFlow(false)
    val hasInternet: StateFlow<Boolean> = _hasInternet.asStateFlow()

    @Volatile private var registered = false

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            Log.d(TAG, "Network available: $network")
            ping()
        }
        override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
            Log.d(TAG, "Caps changed: $caps")
            _hasInternet.value = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) &&
                (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))
        }
        override fun onLost(network: Network) {
            Log.d(TAG, "Network lost: $network")
            _hasInternet.value = false
        }
    }

    fun start() {
        if (registered) return
        try {
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            connectivity.registerNetworkCallback(request, callback)
            registered = true
            ping()
        } catch (e: Exception) {
            Log.w(TAG, "registerNetworkCallback failed: ${e.message}")
        }
    }

    fun stop() {
        if (!registered) return
        try { connectivity.unregisterNetworkCallback(callback) } catch (_: Exception) { }
        registered = false
    }

    private fun ping() {
        try {
            val active = connectivity.activeNetwork
            val caps = connectivity.getNetworkCapabilities(active)
            _hasInternet.value = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
        } catch (_: Exception) { }
    }
}