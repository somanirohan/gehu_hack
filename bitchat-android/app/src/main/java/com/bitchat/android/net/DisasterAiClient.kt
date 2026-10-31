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
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class DisasterAiResponse(
    val answer: String,
    val matchedProtocol: String? = null,
    val category: String? = null,
    val criticalWarning: String? = null,
    val actions: String? = null,
    val isOfflineFallback: Boolean = false
)

/**
 * Client for the Disaster Management AI Assistant.
 *
 * Connects to the local machine running the SQLite + Qwen2.5-1.5B API server
 * on port 8800. Automatically falls back to on-device protocol matching if
 * the network or local server is unreachable.
 */
class DisasterAiClient(private val context: Context) {

    companion object {
        private const val TAG = "DisasterAiClient"
        private const val PREFS_NAME = "disaster_ai_prefs"
        private const val KEY_SERVER_URL = "server_url"
        const val DEFAULT_SERVER_URL = "http://10.0.2.2:8800" // Works out-of-the-box in Android Emulator
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    }

    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value.trim()).apply()

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    /**
     * Queries the Disaster AI server. If the server is unreachable, falls back to
     * instantaneous local protocol search from in-app knowledge base.
     */
    suspend fun askDisasterAi(query: String, language: String = "en"): DisasterAiResponse = withContext(Dispatchers.IO) {
        val trimmedQuery = query.trim()
        if (trimmedQuery.isEmpty()) {
            return@withContext DisasterAiResponse("Please enter an emergency question.")
        }

        val baseUrl = serverUrl.removeSuffix("/")
        val url = "$baseUrl/api/chat"

        try {
            val jsonPayload = JSONObject().apply {
                put("query", trimmedQuery)
                put("language", language)
                put("max_tokens", 220)
                put("temperature", 0.3)
            }

            val request = Request.Builder()
                .url(url)
                .post(jsonPayload.toString().toRequestBody(JSON_MEDIA))
                .build()

            val response = httpClient.newCall(request).execute()
            if (response.isSuccessful) {
                val bodyStr = response.body.string()
                val json = JSONObject(bodyStr)
                return@withContext DisasterAiResponse(
                    answer = json.optString("answer", "No response generated."),
                    matchedProtocol = if (json.has("matched_protocol") && !json.isNull("matched_protocol")) json.getString("matched_protocol") else null,
                    category = if (json.has("category") && !json.isNull("category")) json.getString("category") else null,
                    criticalWarning = if (json.has("critical_warning") && !json.isNull("critical_warning")) json.getString("critical_warning") else null,
                    actions = if (json.has("actions") && !json.isNull("actions")) json.getString("actions") else null,
                    isOfflineFallback = false
                )
            } else {
                Log.w(TAG, "Server returned HTTP ${response.code}, falling back to on-device lookup")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Cannot reach disaster AI server at $url: ${e.message}. Using offline fallback.")
        }

        // On-device deterministic fallback in localized language
        return@withContext localOfflineFallback(trimmedQuery, language)
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
                isOfflineFallback = true
            )
        }

        val fallbackAnswers = mapOf(
            "hi" to "⚠️ आपातकालीन सुरक्षा नियम:\n• सिर और महत्वपूर्ण अंगों की तुरंत रक्षा करें।\n• बिजली के गिरे तारों और पानी से दूर रहें।\n• बचाव दल को संकेत देने के लिए ठोस वस्तु पर 3 बार ठोकें।\n• अपनी लोकेशन भेजने के लिए Bitchat में लाल SOS दबाएं।",
            "mr" to "⚠️ आपत्कालीन सुरक्षा नियम:\n• डोके आणि महत्त्वाच्या अवयवांचे त्वरित संरक्षण करा.\n• विजेच्या तारा आणि साचलेल्या पाण्यापासून लांब राहा.\n• बचाव पथकाला संकेत देण्यासाठी वस्तूवर ३ वेळा ठोका.\n• लोकेशन पाठवण्यासाठी Bitchat मध्ये लाल SOS दाबा.",
            "ta" to "⚠️ அவசர பாதுகாப்பு விதி:\n• தலை மற்றும் முக்கிய உறுப்புகளை உடனடியாகப் பாதுகாக்கவும்.\n• மின் கம்பிகள் மற்றும் வெள்ள நீரிலிருந்து விலகி இருங்கள்.\n• மீட்புக் குழுவினருக்கு சமிக்ஞை செய்ய திடமான பொருளில் 3 முறை தட்டவும்.\n• உங்கள் இருப்பிடத்தை அனுப்ப Bitchat-ல் சிவப்பு SOS-ஐ அழுத்தவும்.",
            "te" to "⚠️ అత్యవసర భద్రతా నియమం:\n• తల మరియు ముఖ్యమైన శరీర భాగాలను వెంటనే రక్షించుకోండి.\n• విద్యుత్ తీగలు మరియు వరద నీటికి దూరంగా ఉండండి.\n• రెస్క్యూ సిబ్బందికి సంకేతం ఇవ్వడానికి గట్టి వస్తువుపై 3 సార్లు కొట్టండి.\n• మీ లొకేషన్‌ను పంపడానికి Bitchat లో ఎరుపు రంగు SOS బటన్‌ను నొక్కండి.",
            "en" to "⚠️ Emergency Safety Rule:\n• Protect head and vital organs immediately.\n• Avoid downed electrical lines and floodwaters.\n• Tap 3 times rhythmically on solid objects to signal rescue workers.\n• Tap red SOS in Bitchat to broadcast your coordinates."
        )

        val langCode = language.take(2).lowercase()
        val defaultAns = fallbackAnswers[langCode] ?: fallbackAnswers["en"]!!

        return DisasterAiResponse(
            answer = defaultAns,
            matchedProtocol = "Emergency Protocol",
            category = "General",
            criticalWarning = "Always prioritize personal physical protection and avoid panic.",
            isOfflineFallback = true
        )
    }
}
