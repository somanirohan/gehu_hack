package com.bitchat.android.mesh

import java.util.concurrent.ConcurrentHashMap

/**
 * Per-node cache mapping a broadcast message ID to the immediate upstream peer
 * (the peer from which this node received the message). Used to forward ACK
 * packets back toward the original sender.
 *
 * Entries expire after [TTL_MS] to bound memory growth.
 */
object AckPathCache {
    private const val TTL_MS = 60_000L

    private data class Entry(val upstreamPeerID: String, val expiresAt: Long)

    private val map = ConcurrentHashMap<String, Entry>()

    fun record(messageID: String, upstreamPeerID: String) {
        map[messageID] = Entry(upstreamPeerID, System.currentTimeMillis() + TTL_MS)
    }

    fun lookup(messageID: String): String? {
        val e = map[messageID] ?: return null
        if (System.currentTimeMillis() > e.expiresAt) {
            map.remove(messageID)
            return null
        }
        return e.upstreamPeerID
    }

    fun touch(messageID: String) {
        val e = map[messageID] ?: return
        map[messageID] = e.copy(expiresAt = System.currentTimeMillis() + TTL_MS)
    }

    fun cleanup() {
        val now = System.currentTimeMillis()
        map.entries.removeAll { now > it.value.expiresAt }
    }

    fun size(): Int = map.size
}