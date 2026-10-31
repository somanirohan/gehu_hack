package com.bitchat.android.sync

import com.bitchat.android.protocol.BitchatPacket
import com.bitchat.android.protocol.MessageType
import java.security.MessageDigest

/**
 * Deterministic packet ID helper for sync purposes.
 * Uses SHA-256 over a canonical subset of packet fields:
 * [type | senderID | timestamp | payload] to generate a stable ID.
 * Returns a 16-byte (128-bit) truncated hash for compactness.
 */
object PacketIdUtil {
    fun computeIdBytes(packet: BitchatPacket): ByteArray {
        val md = MessageDigest.getInstance("SHA-256")
        md.update(packet.type.toByte())
        md.update(packet.senderID)
        // Timestamp as 8 bytes big-endian
        val ts = packet.timestamp.toLong()
        for (i in 7 downTo 0) {
            md.update(((ts ushr (i * 8)) and 0xFF).toByte())
        }
        md.update(packet.payload)
        val digest = md.digest()
        return digest.copyOf(16) // 128-bit ID
    }

    fun computeIdHex(packet: BitchatPacket): String {
        return computeIdBytes(packet).joinToString("") { b -> "%02x".format(b) }
    }

    /**
     * Compute the same hash the receiver will compute for an outgoing broadcast
     * MESSAGE, without needing to build a full [BitchatPacket]. Callers must pass
     * the exact `timestamp` that will be used on the wire so the hashes match.
     */
    fun computeBroadcastMessageIdHex(
        senderPeerIDHex: String,
        timestamp: ULong,
        payload: ByteArray
    ): String {
        val md = MessageDigest.getInstance("SHA-256")
        md.update(MessageType.MESSAGE.value.toByte())
        // senderID is 8 bytes on the wire (taken left-to-right from the hex peer ID).
        val senderBytes = ByteArray(8)
        val hex = senderPeerIDHex
        var idx = 0
        var out = 0
        while (idx + 1 < hex.length && out < 8) {
            val b = hex.substring(idx, idx + 2).toIntOrNull(16)?.toByte() ?: 0
            senderBytes[out++] = b
            idx += 2
        }
        md.update(senderBytes)
        val ts = timestamp.toLong()
        for (i in 7 downTo 0) {
            md.update(((ts ushr (i * 8)) and 0xFF).toByte())
        }
        md.update(payload)
        return md.digest().copyOf(16).joinToString("") { b -> "%02x".format(b) }
    }
}

