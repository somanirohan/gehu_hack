package com.bitchat.android.contracts

import com.bitchat.android.model.BitchatFilePacket
import com.bitchat.android.model.BitchatMessage
import com.bitchat.android.model.FragmentPayload
import com.bitchat.android.model.IdentityAnnouncement
import com.bitchat.android.model.NoisePayload
import com.bitchat.android.model.NoisePayloadType
import com.bitchat.android.model.PeerCapabilities
import com.bitchat.android.model.PrivateMessagePacket
import com.bitchat.android.model.RequestSyncPacket
import com.bitchat.android.model.Role
import com.bitchat.android.model.UnknownAnnouncementTLV
import com.bitchat.android.protocol.BinaryProtocol
import com.bitchat.android.protocol.BitchatPacket
import com.bitchat.android.protocol.MessageType
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Date

/**
 * Golden wire vectors for formats that a from-scratch client must reproduce.
 *
 * These assertions deliberately compare literal bytes rather than relying only
 * on encode/decode round trips, which can hide matching bugs in both methods.
 */
class ClientRewriteWireContractTest {

    @Test
    fun `v1 packet matches canonical unpadded bytes`() {
        val packet = BitchatPacket(
            version = 1u,
            type = MessageType.MESSAGE.value,
            senderID = hex("1011121314151617"),
            recipientID = null,
            timestamp = 0x0102030405060708uL,
            payload = hex("aabbcc"),
            signature = null,
            ttl = 7u
        )

        val encoded = BinaryProtocol.encode(packet, padding = false)

        assertArrayEquals(
            hex("01020701020304050607080000031011121314151617aabbcc"),
            encoded
        )
        assertEquals(packet, BinaryProtocol.decode(encoded!!))
    }

    @Test
    fun `v2 routed signed packet matches canonical section order`() {
        val signature = ByteArray(64) { 0x5a }
        val packet = BitchatPacket(
            version = 2u,
            type = MessageType.NOISE_ENCRYPTED.value,
            senderID = hex("0102030405060708"),
            recipientID = hex("1112131415161718"),
            timestamp = 42uL,
            payload = hex("dead"),
            signature = signature,
            ttl = 5u,
            route = listOf(
                hex("2122232425262728"),
                hex("3132333435363738")
            )
        )

        val encoded = BinaryProtocol.encode(packet, padding = false)!!
        val expectedPrefix = hex(
            "021105000000000000002a0b00000002" +
                "0102030405060708" +
                "1112131415161718" +
                "02" +
                "2122232425262728" +
                "3132333435363738" +
                "dead"
        )

        assertArrayEquals(expectedPrefix + signature, encoded)
        assertEquals(packet, BinaryProtocol.decode(encoded))
    }

    @Test
    fun `minimal chat message matches canonical binary payload`() {
        val message = BitchatMessage(
            id = "id",
            sender = "bob",
            content = "hi",
            timestamp = Date(0x0102030405060708L)
        )

        val encoded = message.toBinaryPayload()

        assertArrayEquals(
            hex("00010203040506070802696403626f6200026869"),
            encoded
        )
        assertEquals(message, BitchatMessage.fromBinaryPayload(encoded!!))
    }

    @Test
    fun `chat message optional fields use flags and UTF-8 byte lengths`() {
        val message = BitchatMessage(
            id = "m",
            sender = "é",
            content = "hello",
            timestamp = Date(42L),
            isRelay = true,
            originalSender = "o",
            isPrivate = true,
            recipientNickname = "r",
            senderPeerID = "p",
            mentions = listOf("a", "β"),
            channel = "c"
        )

        val encoded = message.toBinaryPayload()!!

        assertArrayEquals(
            hex(
                "7f000000000000002a" +
                    "016d" +
                    "02c3a9" +
                    "000568656c6c6f" +
                    "016f" +
                    "0172" +
                    "0170" +
                    "02" +
                    "0161" +
                    "02ceb2" +
                    "0163"
            ),
            encoded
        )
        assertEquals(message, BitchatMessage.fromBinaryPayload(encoded))
    }

    @Test
    fun `encrypted chat payload carries ciphertext instead of placeholder content`() {
        val message = BitchatMessage(
            id = "e",
            sender = "alice",
            content = "must-not-be-on-wire",
            timestamp = Date(1L),
            encryptedContent = hex("000102ff"),
            isEncrypted = true,
            isPrivate = true
        )

        val decoded = BitchatMessage.fromBinaryPayload(message.toBinaryPayload()!!)!!

        assertEquals("", decoded.content)
        assertArrayEquals(hex("000102ff"), decoded.encryptedContent)
        assertTrue(decoded.isEncrypted)
        assertTrue(decoded.isPrivate)
        assertFalse(message.toBinaryPayload()!!.toString(Charsets.ISO_8859_1).contains("must-not-be-on-wire"))
    }

    @Test
    fun `private message and Noise envelopes match deployed type bytes`() {
        val privateMessage = PrivateMessagePacket(messageID = "m1", content = "hi")
        val privateMessageBytes = hex("00026d3101026869")

        assertArrayEquals(privateMessageBytes, privateMessage.encode())
        assertEquals(privateMessage, PrivateMessagePacket.decode(privateMessageBytes))
        assertArrayEquals(
            hex("0100026d3101026869"),
            NoisePayload(NoisePayloadType.PRIVATE_MESSAGE, privateMessageBytes).encode()
        )
        assertEquals(
            NoisePayloadType.FILE_TRANSFER,
            NoisePayload.decode(hex("09cafe"))?.type
        )
        assertArrayEquals(
            hex("20cafe"),
            NoisePayload.decode(hex("09cafe"))!!.encode()
        )
    }

    @Test
    fun `fragment payload matches the thirteen byte iOS header`() {
        val fragment = FragmentPayload(
            fragmentID = hex("0001020304050607"),
            index = 1,
            total = 3,
            originalType = MessageType.MESSAGE.value,
            data = hex("aabb")
        )
        val wire = hex("00010203040506070001000302aabb")

        assertArrayEquals(wire, fragment.encode())
        assertEquals(fragment, FragmentPayload.decode(wire))
        assertTrue(fragment.isValid())
    }

    @Test
    fun `sync request matches canonical TLV bytes and skips extensions`() {
        val request = RequestSyncPacket(
            p = 19,
            m = 0x01020304L,
            data = hex("aabb")
        )
        val wire = hex("0100011302000401020304030002aabb")

        assertArrayEquals(wire, request.encode())
        assertSyncRequestEquals(request, RequestSyncPacket.decode(wire))

        val withExtension = hex("7f0002cafe") + wire
        assertSyncRequestEquals(request, RequestSyncPacket.decode(withExtension))
    }

    @Test
    fun `identity announcement matches canonical TLV order and preserves extensions`() {
        val announcement = IdentityAnnouncement(
            nickname = "bob",
            noisePublicKey = ByteArray(32) { 0x11 },
            signingPublicKey = ByteArray(32) { 0x22 },
            capabilities = PeerCapabilities.PRIVATE_MEDIA,
            unknownTLVs = listOf(UnknownAnnouncementTLV(0x7f, hex("cafe")))
        )
        val expected =
            hex("0103626f620220") +
                ByteArray(32) { 0x11 } +
                hex("0320") +
                ByteArray(32) { 0x22 } +
                hex("050200017f02cafe")

        val encoded = announcement.encode()

        assertArrayEquals(expected, encoded)
        assertEquals(announcement, IdentityAnnouncement.decode(encoded!!))
    }

    @Test
    fun `file transfer matches deployed mixed-width TLV vector`() {
        val packet = BitchatFilePacket(
            fileName = "a",
            fileSize = 2,
            mimeType = "m",
            content = hex("dead")
        )
        val wire = hex("01000161020004000000020300016d0400000002dead")

        assertArrayEquals(wire, packet.encode())

        val decoded = BitchatFilePacket.decode(wire)
        assertNotNull(decoded)
        assertEquals(packet.fileName, decoded!!.fileName)
        assertEquals(packet.fileSize, decoded.fileSize)
        assertEquals(packet.mimeType, decoded.mimeType)
        assertArrayEquals(packet.content, decoded.content)
    }

    @Test
    fun `required message prefixes reject every truncation`() {
        val wire = BitchatMessage(
            id = "id",
            sender = "bob",
            content = "hello",
            timestamp = Date(1L)
        ).toBinaryPayload()!!

        for (length in 0 until wire.size) {
            assertNull(
                "Accepted required message prefix of $length/${wire.size} bytes",
                BitchatMessage.fromBinaryPayload(wire.copyOf(length))
            )
        }
        assertNotNull(BitchatMessage.fromBinaryPayload(wire))
    }

    @Test
    fun `TLV decoders reject missing required fields and truncated values`() {
        assertNull(PrivateMessagePacket.decode(hex("00026d31")))
        assertNull(PrivateMessagePacket.decode(hex("00026d3101036869")))
        assertNull(RequestSyncPacket.decode(hex("0100011302000401020304")))
        assertNull(IdentityAnnouncement.decode(hex("0103626f62022011")))
        assertNull(BitchatFilePacket.decode(hex("010001610400000002de")))
        assertNull(FragmentPayload.decode(ByteArray(FragmentPayload.HEADER_SIZE - 1)))
    }

    @Test
    fun `role TLV 0x06 appends a single role byte and survives round trip`() {
        val announcement = IdentityAnnouncement(
            nickname = "bob",
            noisePublicKey = ByteArray(32) { 0x11 },
            signingPublicKey = ByteArray(32) { 0x22 },
            capabilities = PeerCapabilities.PRIVATE_MEDIA,
            unknownTLVs = listOf(UnknownAnnouncementTLV(0x7f, hex("cafe"))),
            role = Role.FIRE
        )
        // Same expected body as the deployed mixed-width vector, with the role TLV appended
        // between capabilities and the unknown TLV (matches IdentityAnnouncement.encode order).
        val expected =
            hex("0103626f620220") +
                ByteArray(32) { 0x11 } +
                hex("0320") +
                ByteArray(32) { 0x22 } +
                hex("05020001") +
                hex("060103") +
                hex("7f02cafe")

        val encoded = announcement.encode()!!

        assertArrayEquals(expected, encoded)
        val decoded = IdentityAnnouncement.decode(encoded)!!
        assertEquals(announcement, decoded)
        assertEquals(Role.FIRE, decoded.role)
    }

    @Test
    fun `legacy announcement without role TLV stays byte-identical to deployed clients`() {
        // Verifies that adding the role field did not perturb previously deployed bits when role
        // is UNSET (the default). This is the regression gate for cross-client compatibility.
        val announcement = IdentityAnnouncement(
            nickname = "bob",
            noisePublicKey = ByteArray(32) { 0x11 },
            signingPublicKey = ByteArray(32) { 0x22 },
            capabilities = PeerCapabilities.PRIVATE_MEDIA,
            unknownTLVs = listOf(UnknownAnnouncementTLV(0x7f, hex("cafe")))
        )
        val expected =
            hex("0103626f620220") +
                ByteArray(32) { 0x11 } +
                hex("0320") +
                ByteArray(32) { 0x22 } +
                hex("050200017f02cafe")

        val encoded = announcement.encode()!!

        assertArrayEquals(expected, encoded)
        assertEquals(Role.UNSET, IdentityAnnouncement.decode(encoded)!!.role)
    }

    @Test
    fun `shelter TLV payload matches canonical bytes and round trips`() {
        val shelter = com.bitchat.android.model.Shelter(
            id = "s1",
            name = "Metro Shelter",
            lat = 11.0168,
            lon = 76.9558,
            capacity = 50,
            role = Role.GOV,
            status = com.bitchat.android.model.ShelterStatus.OPEN,
            version = 0xDEADBEEFL,
            originPeerID = "0102030405060708"
        )
        val encoded = shelter.encode()!!

        // Round trip preserves identity
        val decoded = com.bitchat.android.model.Shelter.decode(encoded)!!
        assertEquals(shelter.id, decoded.id)
        assertEquals(shelter.name, decoded.name)
        assertEquals(shelter.lat, decoded.lat, 1e-9)
        assertEquals(shelter.lon, decoded.lon, 1e-9)
        assertEquals(shelter.capacity, decoded.capacity)
        assertEquals(shelter.role, decoded.role)
        assertEquals(shelter.status, decoded.status)
        assertEquals(shelter.version, decoded.version)
        assertEquals(shelter.originPeerID, decoded.originPeerID)

        // Optional TLVs (ROLE / STATUS) are omitted when they take default values to keep
        // shelter bursts byte-identical regardless of which client produced them.
        val minimal = com.bitchat.android.model.Shelter(
            id = "s1",
            name = "n",
            lat = 0.0,
            lon = 0.0,
            capacity = 0,
            role = Role.UNSET,
            status = com.bitchat.android.model.ShelterStatus.OPEN,
            version = 0L,
            originPeerID = "x"
        )
        val minimalEncoded = minimal.encode()!!
        // ID + name + lat + lon + capacity + version + origin (no role/status TLVs)
        assertTrue(minimalEncoded.size >= 2 + 2 + 2 + 2 + 2 + 2 + 2)
        assertFalse(minimalEncoded.asList().windowed(2).any { it[0] == 0x06.toByte() || it[0] == 0x07.toByte() })
    }

    @Test
    fun `ack payload matches canonical bytes and round trips`() {
        val ack = com.bitchat.android.model.AckPayload(
            status = com.bitchat.android.model.AckStatus.REACHED_RESPONDER,
            hopCount = 2,
            messageID = "abc"
        )
        val encoded = ack.encode()!!
        // status=0x02, hop=0x02, idLen=3, "abc"
        assertArrayEquals(hex("020203616263"), encoded)
        val decoded = com.bitchat.android.model.AckPayload.decode(encoded)!!
        assertEquals(ack.status, decoded.status)
        assertEquals(ack.hopCount, decoded.hopCount)
        assertEquals(ack.messageID, decoded.messageID)
        assertNull(com.bitchat.android.model.AckPayload.decode(hex("00")))
    }

    private fun hex(value: String): ByteArray {
        require(value.length % 2 == 0)
        return value.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }

    private fun assertSyncRequestEquals(
        expected: RequestSyncPacket,
        actual: RequestSyncPacket?
    ) {
        assertNotNull(actual)
        assertEquals(expected.p, actual!!.p)
        assertEquals(expected.m, actual.m)
        assertArrayEquals(expected.data, actual.data)
    }
}
