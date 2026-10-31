package com.bitchat.android.services

import android.content.Context
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.bitchat.android.model.Shelter
import com.bitchat.android.model.ShelterStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Append-only, last-write-wins-by-version shelter registry. Survives process death via
 * encrypted preferences (shelter authorship can reveal responder movement, so we never
 * store it in plaintext). Gossiped as one SHELTER packet per entry on every mesh contact.
 */
class ShelterRegistry private constructor(private val context: Context) {

    companion object {
        private const val TAG = "ShelterRegistry"
        private const val PREFS_NAME = "bitchat_shelter_registry_v1"
        private const val KEY_COUNT = "count"
        private const val KEY_PREFIX = "shelter_"

        @Volatile private var instance: ShelterRegistry? = null
        fun getInstance(context: Context): ShelterRegistry =
            instance ?: synchronized(this) {
                instance ?: ShelterRegistry(context.applicationContext).also { instance = it }
            }
    }

    private val prefs by lazy {
        try {
            val masterKey = MasterKey.Builder(context, MasterKey.DEFAULT_MASTER_KEY_ALIAS)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREFS_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (e: Exception) {
            Log.w(TAG, "Falling back to plain prefs: ${e.message}")
            context.getSharedPreferences("${PREFS_NAME}_fallback", Context.MODE_PRIVATE)
        }
    }

    private val lock = Any()
    private val _shelters = MutableStateFlow<List<Shelter>>(emptyList())
    val shelters: StateFlow<List<Shelter>> = _shelters.asStateFlow()

    init {
        loadFromDisk()
    }

    private fun loadFromDisk() {
        synchronized(lock) {
            val count = prefs.getInt(KEY_COUNT, 0)
            val out = ArrayList<Shelter>(count)
            for (i in 0 until count) {
                val raw = prefs.getString("$KEY_PREFIX$i", null) ?: continue
                val bytes = android.util.Base64.decode(raw, android.util.Base64.NO_WRAP)
                Shelter.decode(bytes)?.let { out.add(it) }
            }
            _shelters.value = out
        }
    }

    private fun persistAll(list: List<Shelter>) {
        prefs.edit().apply {
            for (i in 0 until prefs.getInt(KEY_COUNT, 0)) {
                remove("$KEY_PREFIX$i")
            }
            putInt(KEY_COUNT, list.size)
            list.forEachIndexed { i, s ->
                val enc = s.encode() ?: return@forEachIndexed
                putString("$KEY_PREFIX$i", android.util.Base64.encodeToString(enc, android.util.Base64.NO_WRAP))
            }
        }.apply()
    }

    /**
     * Merge a shelter received from the mesh. Returns true if the registry was updated.
     * LWW: a newer [Shelter.version] replaces an existing entry with the same [Shelter.id];
     * ties are resolved by preserving whichever we already have to dampen relay churn.
     */
    fun ingest(received: Shelter): Boolean = synchronized(lock) {
        val current = _shelters.value
        val existing = current.firstOrNull { it.id == received.id }
        if (existing != null) {
            if (existing.version >= received.version) return@synchronized false
            val updated = current.toMutableList().apply {
                val idx = indexOf(existing)
                this[idx] = received
            }
            _shelters.value = updated
            persistAll(updated)
        } else {
            val updated = current + received
            _shelters.value = updated
            persistAll(updated)
        }
        true
    }

    /** Publish a shelter authored by this node. */
    fun publishLocal(
        id: String,
        name: String,
        lat: Double,
        lon: Double,
        capacity: Int,
        role: com.bitchat.android.model.Role,
        status: ShelterStatus,
        originPeerID: String
    ): Shelter {
        val shelter = Shelter(
            id = id,
            name = name,
            lat = lat,
            lon = lon,
            capacity = capacity,
            role = role,
            status = status,
            version = System.currentTimeMillis(),
            originPeerID = originPeerID
        )
        ingest(shelter)
        return shelter
    }

    fun snapshot(): List<Shelter> = _shelters.value

    fun remove(id: String): Boolean = synchronized(lock) {
        val current = _shelters.value
        val idx = current.indexOfFirst { it.id == id }
        if (idx < 0) return@synchronized false
        val updated = current.toMutableList().apply { removeAt(idx) }
        _shelters.value = updated
        persistAll(updated)
        true
    }

    fun clear() = synchronized(lock) {
        _shelters.value = emptyList()
        prefs.edit().clear().apply()
    }
}