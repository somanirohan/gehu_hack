package com.bitchat.android.net

import android.content.Context
import android.util.Log
import com.bitchat.android.model.BitchatMessage
import com.bitchat.android.model.BitchatMessageType
import com.bitchat.android.services.SyncPreferences
import com.bitchat.android.ui.map.parseGeoTag
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.net.InetSocketAddress
import java.net.Proxy
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Uploads photos and voice notes from the public mesh timeline to the control room:
 *   images → POST {server}/api/v1/field/photo   (vision check: fallen tree, landslide…)
 *   audio  → POST {server}/api/v1/field/voice   (speech to text in any language → triage)
 *
 * {server} is taken from the Sync endpoint URL (everything before "/api/"), so no new
 * setting is needed. Both sent and received media are uploaded, so any online phone acts as
 * a gateway for nearby offline phones, the same as for text.
 *
 * The event id is a hash of the file bytes: the sender and every phone that received the
 * same file produce the same id, and the server stores it once.
 */
class FieldMediaUploader(context: Context) {

    companion object {
        private const val TAG = "FieldMediaUploader"
        private const val DONE_PREFS = "bitchat_field_media_uploads_v1"
        private const val KEY_DONE = "done_ids"
        private const val MAX_DONE = 400
        private const val MAX_FILE_BYTES = 15L * 1024 * 1024
        private const val MAX_AGE_MS = 24L * 60 * 60 * 1000
        private const val MAX_PER_FLUSH = 10
        /** A media message borrows the location of the same sender's geo-tagged message within this window. */
        private const val LOCATION_WINDOW_MS = 30L * 60 * 1000
    }

    enum class Outcome { UPLOADED, NOTHING, RETRY_LATER }

    private val appContext = context.applicationContext
    private val prefs = SyncPreferences.getInstance(context)
    private val done = appContext.getSharedPreferences(DONE_PREFS, Context.MODE_PRIVATE)

    private fun client(): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            // the server transcribes / checks the photo before answering
            .readTimeout(90, TimeUnit.SECONDS)
        if (prefs.useTor) {
            try {
                builder.proxy(Proxy(Proxy.Type.SOCKS, InetSocketAddress("127.0.0.1", 39060)))
            } catch (_: Exception) { }
        }
        return builder.build()
    }

    /** "https://x.trycloudflare.com/api/v1/bitchat/civ-sync" → "https://x.trycloudflare.com" */
    private fun serverBase(): String? {
        val url = prefs.endpointUrl.trim()
        if (!url.startsWith("http")) return null
        val idx = url.indexOf("/api/")
        return (if (idx > 0) url.substring(0, idx) else url).trimEnd('/')
    }

    private fun doneIds(): MutableSet<String> = HashSet(done.getStringSet(KEY_DONE, emptySet()) ?: emptySet())

    private fun markDone(id: String) {
        val ids = doneIds().apply { add(id) }
        val trimmed = if (ids.size > MAX_DONE) ids.toList().takeLast(MAX_DONE).toSet() else ids
        done.edit().putStringSet(KEY_DONE, trimmed).apply()
    }

    private fun sha256(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }.take(32)
    }

    /** Media worth uploading: public, photo or voice, file present, recent, not too big. */
    fun pending(messages: List<BitchatMessage>): List<BitchatMessage> {
        val now = System.currentTimeMillis()
        return messages.filter { m ->
            (m.type == BitchatMessageType.Image || m.type == BitchatMessageType.Audio) &&
                m.channel.isNullOrBlank() && !m.isPrivate &&
                now - m.timestamp.time <= MAX_AGE_MS &&
                File(m.content.trim()).let { it.isFile && it.length() in 1..MAX_FILE_BYTES }
        }
    }

    /**
     * Location for a media message: the same sender's nearest geo-tagged message in time
     * (every public text now carries one); for our own media, the phone's current position.
     */
    private suspend fun locationFor(m: BitchatMessage, all: List<BitchatMessage>, myPeerID: String?): Pair<Double, Double>? {
        val sameSender = all.asSequence()
            .filter { it.type == BitchatMessageType.Message }
            .filter { o ->
                (m.senderPeerID != null && o.senderPeerID == m.senderPeerID) ||
                    (m.senderPeerID == null && o.sender == m.sender)
            }
            .filter { kotlin.math.abs(it.timestamp.time - m.timestamp.time) <= LOCATION_WINDOW_MS }
            .mapNotNull { o -> parseGeoTag(o.content)?.let { geo -> geo to kotlin.math.abs(o.timestamp.time - m.timestamp.time) } }
            .minByOrNull { it.second }
            ?.first
        if (sameSender != null) return sameSender
        val mine = myPeerID != null && m.senderPeerID == myPeerID
        return if (mine) com.bitchat.android.util.LocationFetcher.fetch(appContext) else null
    }

    suspend fun uploadPending(all: List<BitchatMessage>): Outcome {
        val base = serverBase() ?: return Outcome.NOTHING
        val already = doneIds()
        val myPeerID = try { com.bitchat.android.service.MeshServiceHolder.meshService?.myPeerID } catch (_: Exception) { null }
        val candidates = pending(all)
            .mapNotNull { m -> runCatching { m to "bitchat-media-" + sha256(File(m.content.trim())) }.getOrNull() }
            .filter { (_, id) -> id !in already }
            .distinctBy { (_, id) -> id }
            .takeLast(MAX_PER_FLUSH)
        if (candidates.isEmpty()) return Outcome.NOTHING

        var needRetry = false
        var uploaded = false
        val http = client()
        for ((m, eventId) in candidates) {
            val file = File(m.content.trim())
            val isAudio = m.type == BitchatMessageType.Audio
            val coords = try { locationFor(m, all, myPeerID) } catch (_: Exception) { null }
            val mime = mimeFor(file, isAudio)
            val body = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("file", uploadName(file, isAudio), file.asRequestBody(mime.toMediaTypeOrNull()))
                .addFormDataPart("event_id", eventId)
                .addFormDataPart("sender", m.sender)
                .addFormDataPart("role", m.category.name)
                .addFormDataPart("created_at", java.time.Instant.ofEpochMilli(m.timestamp.time).toString())
                .apply {
                    if (coords != null) {
                        addFormDataPart("lat", "%.6f".format(java.util.Locale.US, coords.first))
                        addFormDataPart("lon", "%.6f".format(java.util.Locale.US, coords.second))
                    }
                }
                .build()
            val url = base + if (isAudio) "/api/v1/field/voice" else "/api/v1/field/photo"
            try {
                http.newCall(Request.Builder().url(url).post(body).build()).execute().use { resp ->
                    when {
                        resp.isSuccessful -> {
                            markDone(eventId)
                            uploaded = true
                            Log.i(TAG, "Uploaded ${if (isAudio) "voice" else "photo"} $eventId -> ${resp.code}")
                        }
                        // the server refused this file for good (too big, bad format): don't loop on it
                        resp.code in 400..499 && resp.code !in setOf(404, 408, 429) -> {
                            markDone(eventId)
                            prefs.lastSyncError = "media upload refused: HTTP ${resp.code}"
                            Log.w(TAG, "Server refused $eventId: HTTP ${resp.code}")
                        }
                        resp.code == 404 -> {
                            // server too old for voice/photo: keep the file for a later server, no retry storm
                            prefs.lastSyncError = "server has no voice/photo endpoint (HTTP 404)"
                        }
                        else -> {
                            needRetry = true
                            prefs.lastSyncError = "media upload: HTTP ${resp.code}"
                        }
                    }
                }
            } catch (e: Exception) {
                needRetry = true
                prefs.lastSyncError = "media upload: ${e.message?.take(160)}"
                Log.w(TAG, "Upload failed for $eventId: ${e.message}")
            }
        }
        if (uploaded && !needRetry) prefs.lastSyncedAt = System.currentTimeMillis()
        return when {
            needRetry -> Outcome.RETRY_LATER
            uploaded -> Outcome.UPLOADED
            else -> Outcome.NOTHING
        }
    }

    /** Speech-to-text services pick the decoder from the file name, so never send "x.bin". */
    private fun uploadName(file: File, isAudio: Boolean): String {
        val ext = file.extension.lowercase()
        val audioExt = setOf("m4a", "mp4", "mp3", "wav", "ogg", "oga", "opus", "webm", "aac", "amr", "3gp", "flac")
        val imageExt = setOf("jpg", "jpeg", "png", "webp", "heic")
        return when {
            isAudio && ext in audioExt -> file.name
            isAudio -> file.nameWithoutExtension + ".m4a"
            ext in imageExt -> file.name
            else -> file.nameWithoutExtension + ".jpg"
        }
    }

    private fun mimeFor(file: File, isAudio: Boolean): String {
        val ext = file.extension.lowercase()
        return if (isAudio) when (ext) {
            "mp3" -> "audio/mpeg"; "wav" -> "audio/wav"; "ogg", "oga", "opus" -> "audio/ogg"
            "webm" -> "audio/webm"; "aac" -> "audio/aac"; "amr" -> "audio/amr"; "3gp" -> "audio/3gpp"
            else -> "audio/mp4"
        } else when (ext) {
            "png" -> "image/png"; "webp" -> "image/webp"; "heic" -> "image/heic"
            else -> "image/jpeg"
        }
    }
}
