package com.bitchat.android.mesh

import com.bitchat.android.model.BitchatMessage
import com.bitchat.android.model.Shelter

/**
 * Shared mesh delegate interface for transport-agnostic callbacks.
 */
interface MeshDelegate {
    fun didReceiveMessage(message: BitchatMessage)
    fun didUpdatePeerList(peers: List<String>)
    fun didReceiveChannelLeave(channel: String, fromPeer: String)
    fun didReceiveDeliveryAck(messageID: String, recipientPeerID: String)
    fun didReceiveReadReceipt(messageID: String, recipientPeerID: String)
    fun didReceiveVerifyChallenge(peerID: String, payload: ByteArray, timestampMs: Long) {}
    fun didReceiveVerifyResponse(peerID: String, payload: ByteArray, timestampMs: Long) {}
    /** Current Noise generation either proved peer state or exhausted its 5-second watchdog. */
    fun didResolvePrivateMediaPolicy(peerID: String) {}
    fun decryptChannelMessage(encryptedContent: ByteArray, channel: String): String?
    fun getNickname(): String?
    fun isFavorite(peerID: String): Boolean
    /** A shelter-registry entry arrived over the mesh; [verified] is true iff signaled by a GOV peer. */
    fun didReceiveShelter(shelter: Shelter, verified: Boolean) {}
    /**
     * A broadcast-message delivery ACK arrived at the original sender. [hopCount] is
     * the relayer's reported distance from the original sender; [reachedResponder]
     * is true iff the acker's subscribed roles include the original message category.
     */
    fun didReceiveBroadcastAck(messageID: String, ackerPeerID: String, hopCount: Int, reachedResponder: Boolean) {}
}
