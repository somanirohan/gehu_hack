package com.bitchat.android.vlm

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

class VlmApiReceiver : BroadcastReceiver() {

    companion object {
        const val TAG = "VlmApiReceiver"
        const val ACTION = "com.bitchat.android.VLM_API"

        const val CMD_SEND_TEXT = "send_text"
        const val CMD_SEND_IMAGE = "send_image"
        const val CMD_SEND_ANALYSIS = "send_analysis"
        const val CMD_ENABLE = "enable"
        const val CMD_DISABLE = "disable"
        const val CMD_STATUS = "status"
        const val CMD_SILENCE = "silence"
    }

    private val scope = CoroutineScope(Dispatchers.Default)

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION) return

        val cmd = intent.getStringExtra("cmd") ?: "status"
        Log.i(TAG, "Received command: $cmd")

        VlmSettingsManager.initialize(context)

        val result = when (cmd) {
            CMD_SEND_TEXT -> handleSendText(context, intent)
            CMD_SEND_IMAGE -> handleSendImage(context, intent)
            CMD_SEND_ANALYSIS -> handleSendAnalysis(context, intent)
            CMD_ENABLE -> handleEnable()
            CMD_DISABLE -> handleDisable()
            CMD_STATUS -> handleStatus(context)
            CMD_SILENCE -> handleSilence(intent)
            else -> error("Unknown command: $cmd")
        }

        val id = intent.getStringExtra("id") ?: "cmd-${System.currentTimeMillis()}"
        writeResult(context, id, result)

        Log.i(TAG, "Command '$cmd' result: ${result.optString("status")}")
    }

    private fun handleSendText(context: Context, intent: Intent): JSONObject {
        val text = intent.getStringExtra("text")
        if (text.isNullOrBlank()) {
            return error("Missing required extra: text")
        }

        val peerId = intent.getStringExtra("peer_id")
        val channel = intent.getStringExtra("channel")

        val result = VlmMessageHandler.sendTextMessage(context, text, peerId, channel)

        return when (result) {
            is VlmResult.Success -> ok().put("message_id", result.messageId)
            is VlmResult.Error -> error(result.message)
        }
    }

    private fun handleSendImage(context: Context, intent: Intent): JSONObject {
        if (!VlmSettingsManager.isEnabled()) {
            return error("VLM API is disabled")
        }

        val imageBytes = when {
            intent.hasExtra("image_path") -> {
                val path = intent.getStringExtra("image_path")!!
                VlmMessageHandler.processImageFromPath(path)
            }
            intent.hasExtra("image_base64") -> {
                val base64 = intent.getStringExtra("image_base64")!!
                VlmMessageHandler.processImageFromBase64(base64)
            }
            else -> null
        }

        if (imageBytes == null || imageBytes.isEmpty()) {
            return error("Missing image: provide 'image_path' or 'image_base64'")
        }

        val caption = intent.getStringExtra("caption")
        val peerId = intent.getStringExtra("peer_id")
        val channel = intent.getStringExtra("channel")

        scope.launch {
            VlmMessageHandler.sendImageMessage(context, imageBytes, caption, peerId, channel)
        }

        return ok().put("message", "Image send initiated")
    }

    private fun handleSendAnalysis(context: Context, intent: Intent): JSONObject {
        if (!VlmSettingsManager.isEnabled()) {
            return error("VLM API is disabled")
        }

        val imageBytes = when {
            intent.hasExtra("image_path") -> {
                val path = intent.getStringExtra("image_path")!!
                VlmMessageHandler.processImageFromPath(path)
            }
            intent.hasExtra("image_base64") -> {
                val base64 = intent.getStringExtra("image_base64")!!
                VlmMessageHandler.processImageFromBase64(base64)
            }
            else -> null
        }

        val description = intent.getStringExtra("description")
            ?: intent.getStringExtra("caption")
            ?: ""

        if ((imageBytes == null || imageBytes.isEmpty()) && description.isBlank()) {
            return error("Missing image and description")
        }

        val peerId = intent.getStringExtra("peer_id")
        val channel = intent.getStringExtra("channel")

        scope.launch {
            VlmMessageHandler.sendAnalysis(context, imageBytes, description, peerId, channel)
        }

        return ok().put("message", "Analysis send initiated")
    }

    private fun handleEnable(): JSONObject {
        VlmSettingsManager.setEnabled(true)
        return ok().put("api_enabled", true)
    }

    private fun handleDisable(): JSONObject {
        VlmSettingsManager.setEnabled(false)
        return ok().put("api_enabled", false)
    }

    private fun handleStatus(context: Context): JSONObject {
        val status = VlmMessageHandler.getStatus(context)
        val json = ok()
        status.forEach { (key, value) -> json.put(key, value) }
        return json
    }

    private fun handleSilence(intent: Intent): JSONObject {
        val enabled = intent.getBooleanExtra("enabled", true)
        VlmSettingsManager.setSilenceEnabled(enabled)
        return ok().put("silence_enabled", enabled)
    }

    private fun ok(): JSONObject = JSONObject().put("status", "ok")
    private fun error(message: String): JSONObject = JSONObject()
        .put("status", "error")
        .put("error", message)

    private fun writeResult(context: Context, id: String, result: JSONObject) {
        try {
            val dir = File(context.cacheDir, "vlm/results").apply { mkdirs() }
            File(dir, "$id.json").writeText(result.put("id", id).toString())
        } catch (e: Exception) {
            Log.e(TAG, "Failed to write result file: ${e.message}")
        }
    }

    private fun sha256Hex(data: ByteArray): String {
        val md = MessageDigest.getInstance("SHA-256")
        val digest = md.digest(data)
        return digest.joinToString("") { "%02x".format(it) }
    }
}
