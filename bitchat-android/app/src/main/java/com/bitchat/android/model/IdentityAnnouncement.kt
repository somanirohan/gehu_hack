package com.bitchat.android.model

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

/**
 * Identity announcement structure with TLV encoding
 * Compatible with iOS AnnouncementPacket TLV format
 */
@Parcelize
data class IdentityAnnouncement(
    val nickname: String,
    val noisePublicKey: ByteArray,    // Noise static public key (Curve25519.KeyAgreement)
    val signingPublicKey: ByteArray,  // Ed25519 public key for signing
    val capabilities: PeerCapabilities? = null,
    val unknownTLVs: List<UnknownAnnouncementTLV> = emptyList(),
    val role: Role = Role.UNSET
) : Parcelable {

    /**
     * TLV types matching iOS implementation
     */
    private enum class TLVType(val value: UByte) {
        NICKNAME(0x01u),
        NOISE_PUBLIC_KEY(0x02u),
        SIGNING_PUBLIC_KEY(0x03u),  // NEW: Ed25519 signing public key
        CAPABILITIES(0x05u),
        ROLE(0x06u);  // Emergency-response node role (1 byte)

        companion object {
            fun fromValue(value: UByte): TLVType? {
                return values().find { it.value == value }
            }
        }
    }

    /**
     * Encode to TLV binary data matching iOS implementation
     */
    fun encode(): ByteArray? {
        val nicknameData = nickname.toByteArray(Charsets.UTF_8)
        
        // Check size limits
        if (nicknameData.size > 255 || noisePublicKey.size > 255 || signingPublicKey.size > 255 ||
            unknownTLVs.any { it.value.size > 255 }) {
            return null
        }
        
        val result = mutableListOf<Byte>()
        
        // TLV for nickname
        result.add(TLVType.NICKNAME.value.toByte())
        result.add(nicknameData.size.toByte())
        result.addAll(nicknameData.toList())
        
        // TLV for noise public key
        result.add(TLVType.NOISE_PUBLIC_KEY.value.toByte())
        result.add(noisePublicKey.size.toByte())
        result.addAll(noisePublicKey.toList())
        
        // TLV for signing public key
        result.add(TLVType.SIGNING_PUBLIC_KEY.value.toByte())
        result.add(signingPublicKey.size.toByte())
        result.addAll(signingPublicKey.toList())

        // Optional little-endian feature bitfield. Old clients skip this TLV.
        capabilities?.encoded()?.let { capabilityBytes ->
            result.add(TLVType.CAPABILITIES.value.toByte())
            result.add(capabilityBytes.size.toByte())
            result.addAll(capabilityBytes.toList())
        }

        // Emergency-response role. UNSET is omitted on the wire so a default
        // announcement stays byte-for-byte backward compatible with old clients.
        if (role != Role.UNSET) {
            result.add(TLVType.ROLE.value.toByte())
            result.add(1.toByte())
            result.add(role.value.toByte())
        }

        // Preserve extensions this build does not understand. This includes
        // gossip TLV 0x04 when an announcement is decoded through this model.
        unknownTLVs.forEach { tlv ->
            result.add(tlv.type.toByte())
            result.add(tlv.value.size.toByte())
            result.addAll(tlv.value.toList())
        }
        
        return result.toByteArray()
    }
    
    companion object {
        /**
         * Decode from TLV binary data matching iOS implementation
         */
        fun decode(data: ByteArray): IdentityAnnouncement? {
            // Create defensive copy
            val dataCopy = data.copyOf()
            
            var offset = 0
            var nickname: String? = null
            var noisePublicKey: ByteArray? = null
            var signingPublicKey: ByteArray? = null
            var capabilities: PeerCapabilities? = null
            var role: Role = Role.UNSET
            val unknownTLVs = mutableListOf<UnknownAnnouncementTLV>()
            
            while (offset + 2 <= dataCopy.size) {
                // Read TLV type
                val typeValue = dataCopy[offset].toUByte()
                val type = TLVType.fromValue(typeValue)
                offset += 1
                
                // Read TLV length
                val length = dataCopy[offset].toUByte().toInt()
                offset += 1
                
                // Check bounds
                if (offset + length > dataCopy.size) return null
                
                // Read TLV value
                val value = dataCopy.sliceArray(offset until offset + length)
                offset += length
                
                // Process known TLV types, skip unknown ones for forward compatibility
                when (type) {
                    TLVType.NICKNAME -> {
                        nickname = String(value, Charsets.UTF_8)
                    }
                    TLVType.NOISE_PUBLIC_KEY -> {
                        noisePublicKey = value
                    }
                    TLVType.SIGNING_PUBLIC_KEY -> {
                        signingPublicKey = value
                    }
                    TLVType.CAPABILITIES -> {
                        capabilities = PeerCapabilities.decode(value)
                    }
                    TLVType.ROLE -> {
                        if (value.isNotEmpty()) role = Role.fromValue(value[0].toUByte())
                    }
                    null -> {
                        // Retain unknown extensions so callers can forward or
                        // re-encode the announcement without erasing them.
                        unknownTLVs += UnknownAnnouncementTLV(typeValue.toInt(), value)
                    }
                }
            }
            
            // All three fields are required
            return if (nickname != null && noisePublicKey != null && signingPublicKey != null) {
                IdentityAnnouncement(nickname, noisePublicKey, signingPublicKey, capabilities, unknownTLVs, role)
            } else {
                null
            }
        }

        /** Construct the announcement emitted by this Android build. */
        fun forLocalPeer(
            nickname: String,
            noisePublicKey: ByteArray,
            signingPublicKey: ByteArray,
            role: Role = Role.UNSET
        ): IdentityAnnouncement = IdentityAnnouncement(
            nickname = nickname,
            noisePublicKey = noisePublicKey,
            signingPublicKey = signingPublicKey,
            capabilities = PeerCapabilities.LOCAL_SUPPORTED,
            role = role
        )
    }
    
    // Override equals and hashCode since we use ByteArray
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (javaClass != other?.javaClass) return false
        
        other as IdentityAnnouncement
        
        if (nickname != other.nickname) return false
        if (!noisePublicKey.contentEquals(other.noisePublicKey)) return false
        if (!signingPublicKey.contentEquals(other.signingPublicKey)) return false
        if (capabilities != other.capabilities) return false
        if (unknownTLVs != other.unknownTLVs) return false
        if (role != other.role) return false
        
        return true
    }
    
    override fun hashCode(): Int {
        var result = nickname.hashCode()
        result = 31 * result + noisePublicKey.contentHashCode()
        result = 31 * result + signingPublicKey.contentHashCode()
        result = 31 * result + (capabilities?.hashCode() ?: 0)
        result = 31 * result + unknownTLVs.hashCode()
        result = 31 * result + role.hashCode()
        return result
    }
    
    override fun toString(): String {
        return "IdentityAnnouncement(nickname='$nickname', noisePublicKey=${noisePublicKey.joinToString("") { "%02x".format(it) }.take(16)}..., signingPublicKey=${signingPublicKey.joinToString("") { "%02x".format(it) }.take(16)}..., capabilities=${capabilities?.rawValue}, role=$role)"
    }
}
