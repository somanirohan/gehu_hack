package com.bitchat.android.net

import android.content.Context
import android.util.Log
import com.bitchat.android.ui.guide.SURVIVAL_SECTIONS
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class ChatMessage(
    val role: String, // "user" or "assistant"
    val content: String,
    val isGuardrailNotice: Boolean = false,
    val matchedProtocol: String? = null,
    val criticalWarning: String? = null,
    val provider: String? = null,
    val timestampMs: Long = System.currentTimeMillis()
)

data class DisasterAiResponse(
    val answer: String,
    val matchedProtocol: String? = null,
    val category: String? = null,
    val criticalWarning: String? = null,
    val actions: String? = null,
    val isOfflineFallback: Boolean = false,
    val isDisasterRelated: Boolean = true,
    val guardrailTriggered: Boolean = false,
    val provider: String = "Groq"
)

/**
 * Client for the ResQMesh Disaster AI Assistant powered by Groq.
 *
 * Connects to the local/remote backend server on port 8800 running Groq + safety guardrails,
 * or connects directly to Groq API if configured.
 * Automatically falls back to on-device protocol matching if network is unreachable.
 */
class DisasterAiClient(private val context: Context) {

    companion object {
        private const val TAG = "DisasterAiClient"
        private const val PREFS_NAME = "disaster_ai_prefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_GROQ_API_KEY = "groq_api_key"
        const val DEFAULT_SERVER_URL = "http://10.0.2.2:8800" // Works in Android Emulator
        private const val GROQ_DIRECT_URL = "https://api.groq.com/openai/v1/chat/completions"
        private const val DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    }

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value.trim()).apply()

    var groqApiKey: String
        get() = prefs.getString(KEY_GROQ_API_KEY, "") ?: ""
        set(value) = prefs.edit().putString(KEY_GROQ_API_KEY, value.trim()).apply()

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    /**
     * Sends a multi-turn chat message to the Groq Disaster AI backend.
     */
    suspend fun sendChatMessage(
        messages: List<ChatMessage>,
        language: String = "en"
    ): DisasterAiResponse = withContext(Dispatchers.IO) {
        val lastUserMessage = messages.lastOrNull { it.role == "user" }?.content.orEmpty().trim()
        if (lastUserMessage.isEmpty()) {
            return@withContext DisasterAiResponse("Please enter a disaster survival question.")
        }

        // 1. Try Backend Server (with Groq and guardrails)
        val serverResponse = tryBackendChat(messages, lastUserMessage, language)
        if (serverResponse != null) {
            return@withContext serverResponse
        }

        // 2. If server is unreachable and direct Groq key is present, try direct Groq API
        val directKey = groqApiKey.trim()
        if (directKey.isNotEmpty()) {
            val directResponse = tryDirectGroq(messages, lastUserMessage, directKey, language)
            if (directResponse != null) {
                return@withContext directResponse
            }
        }

        // 3. AI is unavailable: Explicitly state so in chat instead of sending random fallback text
        val cleanUrl = serverUrl.trim().ifEmpty { DEFAULT_SERVER_URL }
        val unavailableMsg = when (language) {
            "hi" -> "⚠️ एआई सहायक वर्तमान में उपलब्ध नहीं है। बैकएंड सर्वर ($cleanUrl) से कनेक्ट नहीं हो सका। कृपया जांचें कि आपका एआई बैकएंड सर्वर चल रहा है और सेटिंग्स में सही URL दर्ज है।"
            "mr" -> "⚠️ एआय सहाय्यक सध्या उपलब्ध नाही. बॅकएंड सर्व्हरशी ($cleanUrl) संपर्क होऊ शकला नाही. कृपया बॅकएंड सर्व्हर सुरू असल्याचे आणि सेटिंग्जमध्ये योग्य URL असल्याचे तपासा."
            "ta" -> "⚠️ AI உதவியாளர் தற்போது கிடைக்கவில்லை. பின்புல சேவையகத்துடன் ($cleanUrl) இணைக்க முடியவில்லை. சேவையகம் இயங்குவதையும் அமைப்புகளில் சரியான URL உள்ளதையும் உறுதிசெய்யவும்."
            "te" -> "⚠️ AI సహాయకుడు ప్రస్తుతం అందుబాటులో లేదు. బ్యాకెండ్ సర్వర్‌తో ($cleanUrl) కనెక్ట్ కాలేకపోయింది. దయచేసి సర్వర్ నడుస్తున్నట్లు మరియు సెట్టింగ్‌లలో సరైన URL ఉన్నట్లు నిర్ధారించండి."
            else -> "⚠️ AI assistant is currently unavailable. Could not connect to the backend server at $cleanUrl. Please verify your AI backend server is running and the URL is configured in Settings."
        }

        return@withContext DisasterAiResponse(
            answer = unavailableMsg,
            matchedProtocol = null,
            category = "Connection Error",
            criticalWarning = "AI Backend Server Unreachable",
            isOfflineFallback = true,
            isDisasterRelated = true,
            guardrailTriggered = false,
            provider = "Unavailable"
        )
    }

    /**
     * Checks if the configured backend server is reachable and healthy.
     */
    suspend fun checkHealth(): Boolean = withContext(Dispatchers.IO) {
        try {
            val baseUrl = serverUrl.trim().removeSuffix("/")
            val healthUrl = "$baseUrl/health"
            val request = Request.Builder()
                .url(healthUrl)
                .get()
                .build()
            val response = httpClient.newCall(request).execute()
            response.isSuccessful
        } catch (e: Exception) {
            Log.w(TAG, "Health check failed for $serverUrl: ${e.message}")
            false
        }
    }

    /**
     * Single question helper (backwards compatible with SurvivalGuideScreen).
     */
    suspend fun askDisasterAi(query: String, language: String = "en"): DisasterAiResponse {
        val chatList = listOf(ChatMessage(role = "user", content = query))
        return sendChatMessage(chatList, language)
    }

    private fun tryBackendChat(
        messages: List<ChatMessage>,
        query: String,
        language: String
    ): DisasterAiResponse? {
        val baseUrl = serverUrl.removeSuffix("/")
        val url = "$baseUrl/api/chat"

        try {
            val messagesArray = JSONArray().apply {
                for (m in messages) {
                    put(JSONObject().apply {
                        put("role", m.role)
                        put("content", m.content)
                    })
                }
            }

            val payload = JSONObject().apply {
                put("query", query)
                put("messages", messagesArray)
                put("language", language)
                put("max_tokens", 350)
                put("temperature", 0.2)
                if (groqApiKey.isNotBlank()) {
                    put("groq_api_key", groqApiKey.trim())
                }
            }

            val requestBuilder = Request.Builder()
                .url(url)
                .post(payload.toString().toRequestBody(JSON_MEDIA))

            if (groqApiKey.isNotBlank()) {
                requestBuilder.header("X-Groq-Api-Key", groqApiKey.trim())
            }

            val response = httpClient.newCall(requestBuilder.build()).execute()
            if (response.isSuccessful) {
                val bodyStr = response.body.string()
                val json = JSONObject(bodyStr)
                return DisasterAiResponse(
                    answer = json.optString("answer", "No response generated."),
                    matchedProtocol = if (json.has("matched_protocol") && !json.isNull("matched_protocol")) json.getString("matched_protocol") else null,
                    category = if (json.has("category") && !json.isNull("category")) json.getString("category") else null,
                    criticalWarning = if (json.has("critical_warning") && !json.isNull("critical_warning")) json.getString("critical_warning") else null,
                    actions = if (json.has("actions") && !json.isNull("actions")) json.getString("actions") else null,
                    isOfflineFallback = false,
                    isDisasterRelated = json.optBoolean("is_disaster_related", true),
                    guardrailTriggered = json.optBoolean("guardrail_triggered", false),
                    provider = json.optString("provider", "Groq")
                )
            } else {
                Log.w(TAG, "Backend returned HTTP ${response.code}")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Cannot reach disaster backend at $url: ${e.message}")
        }
        return null
    }

    private fun tryDirectGroq(
        messages: List<ChatMessage>,
        query: String,
        apiKey: String,
        language: String
    ): DisasterAiResponse? {
        try {
            val systemDirective = "You are the ResQMesh Emergency Disaster Response Specialist AI powered by Groq. " +
                "STRICT SAFETY GUARDRAIL: You are strictly restricted to disaster survival, emergency first aid, search and rescue, and crisis evacuation. " +
                "If the query is not disaster-related, refuse and redirect to disaster safety. Always state critical warnings in bold first."

            val groqMessagesArray = JSONArray().apply {
                put(JSONObject().apply {
                    put("role", "system")
                    put("content", "$systemDirective Respond fluently in $language.")
                })
                for (m in messages) {
                    put(JSONObject().apply {
                        put("role", m.role)
                        put("content", m.content)
                    })
                }
            }

            val payload = JSONObject().apply {
                put("model", DEFAULT_GROQ_MODEL)
                put("messages", groqMessagesArray)
                put("temperature", 0.2)
                put("max_tokens", 350)
            }

            val request = Request.Builder()
                .url(GROQ_DIRECT_URL)
                .header("Authorization", "Bearer $apiKey")
                .header("Content-Type", "application/json")
                .post(payload.toString().toRequestBody(JSON_MEDIA))
                .build()

            val response = httpClient.newCall(request).execute()
            if (response.isSuccessful) {
                val bodyStr = response.body.string()
                val json = JSONObject(bodyStr)
                val choices = json.getJSONArray("choices")
                if (choices.length() > 0) {
                    val msgObj = choices.getJSONObject(0).getJSONObject("message")
                    val answer = msgObj.getString("content").trim()
                    val isGuardrail = answer.contains("Guardrail Notice", ignoreCase = true) ||
                        answer.contains("सुरक्षा सूचना", ignoreCase = true)
                    return DisasterAiResponse(
                        answer = answer,
                        isOfflineFallback = false,
                        isDisasterRelated = !isGuardrail,
                        guardrailTriggered = isGuardrail,
                        provider = "Groq Direct"
                    )
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Direct Groq call failed: ${e.message}")
        }
        return null
    }

    /**
     * Instantaneous on-device keyword search using localized survival sections.
     */
    private fun localOfflineFallback(query: String, language: String): DisasterAiResponse {
        val q = query.lowercase()
        val tokens = q.split(Regex("[\\s,?.!]+")).filter { it.length > 2 }

        val sections = com.bitchat.android.ui.guide.SurvivalGuideLocalization.getSections(context)
        val bestSection = sections.maxByOrNull { section ->
            var score = 0
            val titleLower = section.title.lowercase()
            val summaryLower = section.summary.lowercase()

            for (token in tokens) {
                if (titleLower.contains(token)) score += 5
                if (summaryLower.contains(token)) score += 3
                for (step in section.steps) {
                    if (step.phase.lowercase().contains(token)) score += 2
                    for (tip in step.tips) {
                        if (tip.lowercase().contains(token)) score += 1
                    }
                }
            }
            score
        }

        if (bestSection != null) {
            val allTips = bestSection.steps.flatMap { step ->
                listOf("**${step.phase}**:") + step.tips.map { "• $it" }
            }.joinToString("\n")

            val synthesized = buildString {
                bestSection.criticalAlert?.let { alert ->
                    append("⚠️ **CRITICAL WARNING**: $alert\n\n")
                }
                append("📋 **${bestSection.title} Instructions**:\n")
                bestSection.steps.firstOrNull()?.tips?.take(3)?.forEach { tip ->
                    append("• $tip\n")
                }
            }

            return DisasterAiResponse(
                answer = synthesized,
                matchedProtocol = bestSection.title,
                category = bestSection.category,
                criticalWarning = bestSection.criticalAlert,
                actions = allTips,
                isOfflineFallback = true,
                isDisasterRelated = true,
                guardrailTriggered = false,
                provider = "Offline Knowledge Base"
            )
        }

        return DisasterAiResponse(
            answer = "Seek secure high ground immediately, avoid damaged structures, and broadcast your SOS beacon in Bitchat.",
            matchedProtocol = "General Emergency",
            category = "Safety",
            isOfflineFallback = true,
            isDisasterRelated = true,
            guardrailTriggered = false,
            provider = "Offline Knowledge Base"
        )
    }
}
