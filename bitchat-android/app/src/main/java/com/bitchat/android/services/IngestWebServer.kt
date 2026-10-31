package com.bitchat.android.services

import android.content.Context
import android.util.Log
import com.bitchat.android.net.CivilizationSyncClient
import com.bitchat.android.ui.map.parseGeoTag
import org.json.JSONObject
import java.io.IOException

/**
 * Local NanoHTTPD server exposing a `/ingest` POST endpoint so a demo can run
 * without needing a cloud relay: a second phone hitting the same local Wi-Fi
 * can POST received incidents. Enabled only when explicitly toggled in the
 * sync settings sheet.
 */
class IngestWebServer(
    private val context: Context,
    private val port: Int = 8420
) : fi.iki.elonen.NanoHTTPD(port) {

    companion object {
        private const val TAG = "IngestWebServer"
        @Volatile private var running: IngestWebServer? = null

        fun start(context: Context, port: Int) {
            stop()
            try {
                val server = IngestWebServer(context.applicationContext, port)
                server.start(SOCKET_READ_TIMEOUT, false)
                running = server
                Log.i(TAG, "Ingest server on :$port")
            } catch (e: IOException) {
                Log.w(TAG, "Ingest start failed: ${e.message}")
            }
        }

        fun stop() {
            try { running?.stop() } catch (_: Exception) { }
            running = null
        }
    }

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri
        if (uri != "/ingest" || session.method != Method.POST) {
            return newFixedLengthResponse(Response.Status.NOT_FOUND, MIME_PLAINTEXT, "not found")
        }
        try {
            val body = HashMap<String, String>()
            session.parseBody(body)
            val raw = body["postData"] ?: ""
            val json = JSONObject(raw)
            val bundle = json.optJSONArray("incidents")
            val shelters = json.optJSONArray("shelters")
            val incCount = bundle?.length() ?: 0
            val shCount = shelters?.length() ?: 0
            Log.i(TAG, "Ingest received inc=$incCount sh=$shCount")
            // Mirror remote shelters + incidents into our local AppStateStore so the receiver sees them on the map.
            for (i in 0 until shCount) {
                val s = shelters!!.getJSONObject(i)
                val shelter = com.bitchat.android.model.Shelter(
                    id = s.getString("id"),
                    name = s.getString("name"),
                    lat = s.getDouble("lat"),
                    lon = s.getDouble("lon"),
                    capacity = s.getInt("capacity"),
                    role = com.bitchat.android.model.Role.fromValue(
                        com.bitchat.android.model.Role.valueOf(s.optString("role", "UNSET")).value
                    ),
                    status = com.bitchat.android.model.ShelterStatus.valueOf(s.optString("status", "OPEN")),
                    version = s.getLong("version"),
                    originPeerID = s.getString("originPeerID")
                )
                val verified = s.optBoolean("verified", false)
                AppStateStore.recordShelter(shelter, verified)
            }
            for (i in 0 until incCount) {
                val obj = bundle!!.getJSONObject(i)
                // Re-hydrate as a BitchatMessage so it surfaces on the public timeline + map
                val msg = com.bitchat.android.model.BitchatMessage(
                    id = obj.getString("id"),
                    sender = obj.optString("sender", "remote"),
                    content = obj.optString("content", ""),
                    timestamp = java.util.Date(obj.optLong("timestamp", System.currentTimeMillis())),
                    senderPeerID = null,
                    category = com.bitchat.android.model.Role.valueOf(obj.optString("role", "UNSET"))
                )
                if (parseGeoTag(msg.content) != null) {
                    AppStateStore.addPublicMessage(msg)
                }
            }
            return newFixedLengthResponse(Response.Status.OK, "application/json", "{\"ok\":true}")
        } catch (e: Exception) {
            Log.e(TAG, "ingest parse failed: ${e.message}")
            return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", "{\"ok\":false,\"error\":\"${e.message?.replace("\"", "'")}\"}")
        }
    }
}