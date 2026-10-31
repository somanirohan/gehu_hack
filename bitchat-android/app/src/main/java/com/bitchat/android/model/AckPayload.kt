package com.bitchat.android.model

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Ack status codes carried over the wire as the first byte of [AckPayload].
 */
enum class AckStatus(val value: UByte) {
    RELAYED(0x01u),
    REACHED_RESPONDER(0x02u);

    companion object {
        fun fromValue(v: UByte): AckStatus? = values().firstOrNull { it.value == v }
    }
}

/**
 * Compact payload of an ACK packet (MessageType.ACK 0x23).
 *
 * Wire layout (big-endian):
 *   - 1 byte: status (AckStatus value)
 *   - 1 byte: hopCount (unsigned, distance from original sender)
 *   - 1 byte: messageID length N
 *   - N bytes: messageID (UTF-8)
 *
 * The packet's [com.bitchat.android.protocol.BitchatPacket.senderID] is the relayer's
 * peer ID, so the sender can attribute the ack to a specific hop on the visualization.
 */
data class AckPayload(
    val status: AckStatus,
    val hopCount: Int,
    val messageID: String
) {
    fun encode(): ByteArray? {
        val idBytes = messageID.toByteArray(Charsets.UTF_8)
        if (idBytes.size > 255) return null
        val buf = ByteArray(3 + idBytes.size)
        buf[0] = status.value.toByte()
        buf[1] = hopCount.coerceIn(0, 255).toByte()
        buf[2] = idBytes.size.toByte()
        System.arraycopy(idBytes, 0, buf, 3, idBytes.size)
        return buf
    }

    companion object {
        fun decode(data: ByteArray): AckPayload? {
            if (data.size < 3) return null
            val status = AckStatus.fromValue(data[0].toUByte()) ?: return null
            val hopCount = data[1].toInt() and 0xFF
            val idLen = data[2].toInt() and 0xFF
            if (data.size < 3 + idLen) return null
            val id = String(data, 3, idLen, Charsets.UTF_8)
            return AckPayload(status, hopCount, id)
        }
    }
}