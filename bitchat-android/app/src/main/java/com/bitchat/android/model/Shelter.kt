package com.bitchat.android.model

import android.os.Parcelable
import kotlinx.parcelize.Parcelize
import java.nio.ByteBuffer
import java.nio.ByteOrder

enum class ShelterStatus(val value: UByte) {
    OPEN(0x01u),
    FULL(0x02u),
    CLOSED(0x03u);

    companion object {
        fun fromValue(value: UByte): ShelterStatus =
            values().firstOrNull { it.value == value } ?: OPEN
    }
}

/**
 * Append-only shelter-registry entry gossiped as a [com.bitchat.android.protocol.MessageType.SHELTER]
 * packet on every mesh contact. Encoded as a TLV blob so unknown extensions are skipped by
 * legacy peers while staying decodable on this build.
 *
 * Trust: a shelter is treated as **verified** only when the routing layer has confirmed the
 * origin peer's Ed25519-signed BitchatPacket and that peer's announced [Role] == [Role.GOV].
 * Otherwise the shelter is rendered muted (unverified) on the map.
 */
@Parcelize
data class Shelter(
    val id: String,
    val name: String,
    val lat: Double,
    val lon: Double,
    val capacity: Int,
    val role: Role,
    val status: ShelterStatus,
    val version: Long,
    val originPeerID: String
) : Parcelable {

    private enum class TLV(val value: UByte) {
        ID(0x01u),
        NAME(0x02u),
        LAT(0x03u),
        LON(0x04u),
        CAPACITY(0x05u),
        ROLE(0x06u),
        STATUS(0x07u),
        VERSION(0x08u),
        ORIGIN(0x09u);

        companion object {
            fun fromValue(v: UByte): TLV? = values().firstOrNull { it.value == v }
        }
    }

    fun encode(): ByteArray? {
        val idBytes = id.toByteArray(Charsets.UTF_8)
        val nameBytes = name.toByteArray(Charsets.UTF_8)
        val originBytes = originPeerID.toByteArray(Charsets.UTF_8)
        if (idBytes.size > 255 || nameBytes.size > 255 || originBytes.size > 255) return null

        val cap = capacity.coerceIn(0, 0xFFFF)
        val result = mutableListOf<Byte>()

        fun tlv(t: TLV, single: Byte) {
            result.add(t.value.toByte())
            result.add(1)
            result.add(single)
        }
        fun tlvl(t: TLV, payload: ByteArray) {
            val len = payload.size.coerceAtMost(255)
            result.add(t.value.toByte())
            result.add(len.toByte())
            result.addAll(payload.take(len).toList())
        }

        tlvl(TLV.ID, idBytes)
        tlvl(TLV.NAME, nameBytes)

        val latBytes = ByteArray(8).also {
            ByteBuffer.wrap(it).order(ByteOrder.BIG_ENDIAN).putDouble(lat)
        }
        tlvl(TLV.LAT, latBytes)

        val lonBytes = ByteArray(8).also {
            ByteBuffer.wrap(it).order(ByteOrder.BIG_ENDIAN).putDouble(lon)
        }
        tlvl(TLV.LON, lonBytes)

        val capBytes = ByteArray(2).also {
            ByteBuffer.wrap(it).order(ByteOrder.BIG_ENDIAN).putShort(cap.toShort())
        }
        tlvl(TLV.CAPACITY, capBytes)

        if (role != Role.UNSET) tlv(TLV.ROLE, role.value.toByte())
        if (status != ShelterStatus.OPEN) tlv(TLV.STATUS, status.value.toByte())

        val verBytes = ByteArray(8).also {
            ByteBuffer.wrap(it).order(ByteOrder.BIG_ENDIAN).putLong(version)
        }
        tlvl(TLV.VERSION, verBytes)
        tlvl(TLV.ORIGIN, originBytes)

        return result.toByteArray()
    }

    companion object {
        fun decode(data: ByteArray): Shelter? {
            var offset = 0
            var id: String? = null
            var name: String? = null
            var lat = 0.0
            var lon = 0.0
            var capacity = 0
            var role = Role.UNSET
            var status = ShelterStatus.OPEN
            var version = 0L
            var origin: String? = null

            while (offset + 2 <= data.size) {
                val t = TLV.fromValue(data[offset].toUByte()) ?: run {
                    offset += 2 + (data[offset + 1].toUByte().toInt() and 0xFF)
                    if (offset > data.size) return null
                    continue
                }
                val len = data[offset + 1].toUByte().toInt() and 0xFF
                offset += 2
                if (offset + len > data.size) return null
                val value = data.sliceArray(offset until offset + len)
                offset += len

                when (t) {
                    TLV.ID -> id = String(value, Charsets.UTF_8)
                    TLV.NAME -> name = String(value, Charsets.UTF_8)
                    TLV.LAT -> if (value.size >= 8) lat = ByteBuffer.wrap(value).order(ByteOrder.BIG_ENDIAN).double
                    TLV.LON -> if (value.size >= 8) lon = ByteBuffer.wrap(value).order(ByteOrder.BIG_ENDIAN).double
                    TLV.CAPACITY -> if (value.size >= 2) capacity = ByteBuffer.wrap(value).order(ByteOrder.BIG_ENDIAN).short.toInt() and 0xFFFF
                    TLV.ROLE -> if (value.isNotEmpty()) role = Role.fromValue(value[0].toUByte())
                    TLV.STATUS -> if (value.isNotEmpty()) status = ShelterStatus.fromValue(value[0].toUByte())
                    TLV.VERSION -> if (value.size >= 8) version = ByteBuffer.wrap(value).order(ByteOrder.BIG_ENDIAN).long
                    TLV.ORIGIN -> origin = String(value, Charsets.UTF_8)
                }
            }

            if (id == null || name == null || origin == null) return null
            return Shelter(
                id = id,
                name = name,
                lat = lat,
                lon = lon,
                capacity = capacity,
                role = role,
                status = status,
                version = version,
                originPeerID = origin
            )
        }
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        other as Shelter
        return id == other.id &&
            name == other.name &&
            lat == other.lat &&
            lon == other.lon &&
            capacity == other.capacity &&
            role == other.role &&
            status == other.status &&
            version == other.version &&
            originPeerID == other.originPeerID
    }

    override fun hashCode(): Int {
        var r = id.hashCode()
        r = 31 * r + name.hashCode()
        r = 31 * r + lat.hashCode()
        r = 31 * r + lon.hashCode()
        r = 31 * r + capacity
        r = 31 * r + role.hashCode()
        r = 31 * r + status.hashCode()
        r = 31 * r + version.hashCode()
        r = 31 * r + originPeerID.hashCode()
        return r
    }

    override fun toString(): String =
        "Shelter(id=$id, name='$name', lat=$lat, lon=$lon, cap=$capacity, role=$role, status=$status, v=$version, origin=${originPeerID.take(8)})"
}