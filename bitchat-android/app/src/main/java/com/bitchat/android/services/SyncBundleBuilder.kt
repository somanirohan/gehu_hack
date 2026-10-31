package com.bitchat.android.services

import com.bitchat.android.model.Role
import com.bitchat.android.model.Shelter
import com.bitchat.android.ui.map.parseGeoTag
import com.google.gson.GsonBuilder
import com.google.gson.JsonObject

/**
 * Builds the structured JSON bundle sent to civilization when internet becomes
 * available. The shape is stable so external coordinators / dashboards receiving
 * the POST can parse incidents and shelters uniformly.
 *
 * Incidents derive their location from the broadcast message content when it
 * carries a `geo:lat,lon` tag. Shelters come from [AppStateStore.shelters].
 */
object SyncBundleBuilder {

    data class Bundle(
        val json: String,
        val bytes: Int,
        val incidentCount: Int,
        val shelterCount: Int,
        val incidentIds: List<String>
    )

    private val gson = GsonBuilder().disableHtmlEscaping().create()

    fun build(shelters: List<AppStateStore.VerifiedShelter>, incidents: List<BitchatIncident>): Bundle {
        val incidentsJson = incidents.map { inc ->
            JsonObject().apply {
                addProperty("id", inc.id)
                addProperty("timestamp", inc.timestamp)
                addProperty("sender", inc.sender)
                addProperty("role", inc.role.name)
                addProperty("lat", inc.lat)
                addProperty("lon", inc.lon)
                addProperty("content", inc.content)
            }
        }
        val sheltersJson = shelters.map { vs ->
            val s: Shelter = vs.shelter
            JsonObject().apply {
                addProperty("id", s.id)
                addProperty("name", s.name)
                addProperty("lat", s.lat)
                addProperty("lon", s.lon)
                addProperty("capacity", s.capacity)
                addProperty("status", s.status.name)
                addProperty("role", s.role.name)
                addProperty("version", s.version)
                addProperty("originPeerID", s.originPeerID)
                addProperty("verified", vs.verified)
            }
        }
        val root = JsonObject().apply {
            addProperty("bundle_schema", "bitchat.civ.sync/v1")
            addProperty("produced_at", System.currentTimeMillis())
            add("incidents", gson.toJsonTree(incidentsJson))
            add("shelters", gson.toJsonTree(sheltersJson))
        }
        val json = gson.toJson(root)
        return Bundle(
            json = json,
            bytes = json.toByteArray(Charsets.UTF_8).size,
            incidentCount = incidents.size,
            shelterCount = shelters.size,
            incidentIds = incidents.map { it.id }
        )
    }

    fun extractIncidents(messages: List<com.bitchat.android.model.BitchatMessage>): List<BitchatIncident> {
        return messages.mapNotNull { msg ->
            val geo = parseGeoTag(msg.content) ?: return@mapNotNull null
            BitchatIncident(
                id = msg.id,
                timestamp = msg.timestamp.time,
                sender = msg.sender,
                role = msg.category,
                lat = geo.first,
                lon = geo.second,
                content = msg.content.take(280)
            )
        }
    }
}

data class BitchatIncident(
    val id: String,
    val timestamp: Long,
    val sender: String,
    val role: Role,
    val lat: Double,
    val lon: Double,
    val content: String
)