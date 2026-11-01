package com.bitchat.android.ui.guide

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bitchat.android.R
import com.bitchat.android.net.ChatMessage
import com.bitchat.android.net.DisasterAiClient
import com.bitchat.android.ui.AboutCardShape
import com.bitchat.android.ui.AboutHorizontalPadding
import com.bitchat.android.ui.BitchatBadge
import com.bitchat.android.ui.LanguagePreferenceManager
import com.bitchat.android.ui.theme.BitchatFontFamily
import kotlinx.coroutines.launch

/**
 * ResQMesh Disaster AI Chatbot screen powered by Groq.
 *
 * Enforces strict safety guardrails ensuring only disaster survival,
 * emergency first aid, and search & rescue queries are processed.
 */
@Composable
fun DisasterChatbotScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier
) {
    BackHandler(onBack = onBack)

    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val aiClient = remember { DisasterAiClient(context) }

    val currentTag = remember { LanguagePreferenceManager.currentLanguageTag() }
    val currentLang = remember(currentTag) {
        if (currentTag.isNotBlank()) currentTag.split("-").first().lowercase() else java.util.Locale.getDefault().language.lowercase()
    }

    val welcomeGreeting = stringResource(R.string.ai_chatbot_welcome)
    var messages by remember {
        mutableStateOf(
            listOf(
                ChatMessage(
                    role = "assistant",
                    content = welcomeGreeting,
                    provider = "Groq Llama-3.3"
                )
            )
        )
    }

    var inputMessage by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(false) }
    var showSettingsDialog by remember { mutableStateOf(false) }
    var serverUrlInput by remember { mutableStateOf(aiClient.serverUrl) }
    var groqApiKeyInput by remember { mutableStateOf(aiClient.groqApiKey) }

    val listState = rememberLazyListState()

    // Auto-scroll on new message
    LaunchedEffect(messages.size, isLoading) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size)
        }
    }

    val quickSuggestions = remember(currentLang) {
        when (currentLang) {
            "hi" -> listOf("मलबे में फंसे हैं", "गंभीर रक्तस्राव प्राथमिक चिकित्सा", "बाढ़ का पानी शुद्ध करना", "चक्रवात की आंख में क्या करें?", "भूकंप के बाद सुरक्षा")
            "mr" -> listOf("ढिगाऱ्याखाली अडकलो तर", "गंभीर रक्तस्त्राव प्रथमोपचार", "पूर पाणी शुद्धीकरण", "चक्रीवादळाचा डोळा", "भूकंपाचे धक्के")
            "ta" -> listOf("இடிபாடுகளில் சிக்கினால்", "கடுமையான இரத்தப்போக்கு", "குடிநீர் சுத்திகரிப்பு", "புயலின் மையம்", "நிலநடுக்க பின்விளைவுகள்")
            "te" -> listOf("శిథిలాల్లో చిక్కుకుంటే", "తీవ్ర రక్తస్రావం ప్రథమ చికిత్స", "నీటి శుద్ధీకరణ", "తుఫాను కన్ను", "భూకంపం అనంతర చర్యలు")
            else -> listOf("Trapped in rubble", "Severe bleeding first aid", "Purifying flood water", "Eye of storm survival", "Earthquake aftershocks")
        }
    }

    fun submitQuery(userText: String) {
        val trimmed = userText.trim()
        if (trimmed.isEmpty() || isLoading) return

        val userMsg = ChatMessage(role = "user", content = trimmed)
        val updatedMessages = messages + userMsg
        messages = updatedMessages
        inputMessage = ""
        isLoading = true

        coroutineScope.launch {
            val response = aiClient.sendChatMessage(updatedMessages, language = currentLang)
            val assistantMsg = ChatMessage(
                role = "assistant",
                content = response.answer,
                isGuardrailNotice = response.guardrailTriggered,
                matchedProtocol = response.matchedProtocol,
                criticalWarning = response.criticalWarning,
                provider = response.provider
            )
            messages = messages + assistantMsg
            isLoading = false
        }
    }

    val colorScheme = MaterialTheme.colorScheme

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(colorScheme.background)
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Header
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = colorScheme.surface,
                tonalElevation = 2.dp
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .windowInsetsPadding(WindowInsets.statusBars)
                        .padding(horizontal = 8.dp, vertical = 6.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        IconButton(onClick = onBack) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = "Back",
                                tint = colorScheme.onSurface
                            )
                        }
                        Box(
                            modifier = Modifier
                                .size(36.dp)
                                .background(colorScheme.primary.copy(alpha = 0.15f), CircleShape),
                            contentAlignment = Alignment.Center
                        ) {
                            Text("🤖", fontSize = 20.sp)
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                Text(
                                    text = stringResource(R.string.ai_chatbot_title),
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colorScheme.onSurface
                                )
                                BitchatBadge("GROQ")
                            }
                            Text(
                                text = stringResource(R.string.ai_chatbot_subtitle),
                                fontFamily = BitchatFontFamily,
                                fontSize = 11.sp,
                                color = colorScheme.onSurfaceVariant
                            )
                        }
                        IconButton(
                            onClick = {
                                serverUrlInput = aiClient.serverUrl
                                groqApiKeyInput = aiClient.groqApiKey
                                showSettingsDialog = true
                            }
                        ) {
                            Icon(
                                Icons.Filled.Settings,
                                contentDescription = "Settings",
                                tint = colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(20.dp)
                            )
                        }
                    }

                    // Guardrail active banner
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        shape = RoundedCornerShape(8.dp),
                        color = colorScheme.secondaryContainer.copy(alpha = 0.5f),
                        border = BorderStroke(1.dp, colorScheme.outlineVariant.copy(alpha = 0.5f))
                    ) {
                        Text(
                            text = stringResource(R.string.ai_chatbot_guardrail_banner),
                            fontFamily = BitchatFontFamily,
                            fontSize = 11.sp,
                            lineHeight = 15.sp,
                            color = colorScheme.onSecondaryContainer,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                        )
                    }
                }
            }

            // Messages timeline
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                contentPadding = PaddingValues(
                    horizontal = AboutHorizontalPadding,
                    vertical = 12.dp
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(messages) { msg ->
                    if (msg.role == "user") {
                        // User message
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End
                        ) {
                            Surface(
                                shape = RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp),
                                color = colorScheme.primary,
                                modifier = Modifier.fillMaxWidth(0.85f)
                            ) {
                                Text(
                                    text = msg.content,
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 13.sp,
                                    lineHeight = 18.sp,
                                    color = colorScheme.onPrimary,
                                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)
                                )
                            }
                        }
                    } else {
                        // Assistant message
                        val isUnavailable = msg.provider == "Unavailable"
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.Start
                        ) {
                            Surface(
                                shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp),
                                color = when {
                                    msg.isGuardrailNotice -> colorScheme.errorContainer.copy(alpha = 0.8f)
                                    isUnavailable -> colorScheme.errorContainer.copy(alpha = 0.45f)
                                    else -> colorScheme.surface
                                },
                                border = BorderStroke(
                                    1.dp,
                                    when {
                                        msg.isGuardrailNotice -> colorScheme.error.copy(alpha = 0.5f)
                                        isUnavailable -> colorScheme.error.copy(alpha = 0.35f)
                                        else -> colorScheme.outlineVariant
                                    }
                                ),
                                modifier = Modifier.fillMaxWidth(0.92f)
                            ) {
                                Column(modifier = Modifier.padding(14.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Row(
                                            verticalAlignment = Alignment.CenterVertically,
                                            horizontalArrangement = Arrangement.spacedBy(6.dp)
                                        ) {
                                            Text(
                                                when {
                                                    msg.isGuardrailNotice -> "🛡️ Guardrail Filter"
                                                    isUnavailable -> "⚠️ AI Unavailable"
                                                    else -> "🤖 Disaster AI"
                                                },
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.SemiBold,
                                                color = if (msg.isGuardrailNotice || isUnavailable) colorScheme.error else colorScheme.primary
                                            )
                                            msg.provider?.let { prov ->
                                                Text(
                                                    "• $prov",
                                                    fontFamily = BitchatFontFamily,
                                                    fontSize = 10.sp,
                                                    color = colorScheme.onSurfaceVariant
                                                )
                                            }
                                        }
                                        msg.matchedProtocol?.let { proto ->
                                            Text(
                                                proto,
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 10.sp,
                                                fontWeight = FontWeight.Medium,
                                                color = colorScheme.onSurfaceVariant
                                            )
                                        }
                                    }

                                    msg.criticalWarning?.let { warn ->
                                        Spacer(Modifier.height(8.dp))
                                        Surface(
                                            shape = RoundedCornerShape(8.dp),
                                            color = colorScheme.errorContainer,
                                            border = BorderStroke(1.dp, colorScheme.error.copy(alpha = 0.35f)),
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Text(
                                                text = remember(warn) { ChatMarkdown.render("⚠️ $warn") },
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 12.sp,
                                                lineHeight = 16.sp,
                                                fontWeight = FontWeight.SemiBold,
                                                color = colorScheme.onErrorContainer,
                                                modifier = Modifier.padding(8.dp)
                                            )
                                        }
                                    }

                                    Spacer(Modifier.height(8.dp))
                                    val codeBg = colorScheme.onSurface.copy(alpha = 0.08f)
                                    val rendered = remember(msg.content, codeBg) { ChatMarkdown.render(msg.content, codeBg) }
                                    Text(
                                        text = rendered,
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 13.sp,
                                        lineHeight = 19.sp,
                                        color = if (msg.isGuardrailNotice) colorScheme.onErrorContainer else colorScheme.onSurface
                                    )
                                }
                            }
                        }
                    }
                }

                if (isLoading) {
                    item(key = "loading_indicator") {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.padding(vertical = 4.dp)
                        ) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                                color = colorScheme.primary
                            )
                            Text(
                                "Analyzing emergency protocols via Groq...",
                                fontFamily = BitchatFontFamily,
                                fontSize = 12.sp,
                                color = colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }

            // Quick suggestion chips
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = AboutHorizontalPadding, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                quickSuggestions.forEach { suggestion ->
                    Surface(
                        shape = RoundedCornerShape(8.dp),
                        color = colorScheme.surfaceVariant.copy(alpha = 0.45f),
                        border = BorderStroke(1.dp, colorScheme.outlineVariant),
                        modifier = Modifier.clickable(enabled = !isLoading) {
                            submitQuery(suggestion)
                        }
                    ) {
                        Text(
                            text = suggestion,
                            fontFamily = BitchatFontFamily,
                            fontSize = 12.sp,
                            color = colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
                        )
                    }
                }
            }

            // Input Row
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .imePadding(),
                color = colorScheme.surface,
                tonalElevation = 3.dp
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .windowInsetsPadding(WindowInsets.navigationBars)
                        .padding(horizontal = AboutHorizontalPadding, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    OutlinedTextField(
                        value = inputMessage,
                        onValueChange = { inputMessage = it },
                        modifier = Modifier.weight(1f),
                        placeholder = {
                            Text(
                                stringResource(R.string.ai_chatbot_input_hint),
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp,
                                color = colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                            )
                        },
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                            fontFamily = BitchatFontFamily,
                            fontSize = 13.sp
                        ),
                        trailingIcon = {
                            if (inputMessage.isNotEmpty()) {
                                IconButton(onClick = { inputMessage = "" }) {
                                    Icon(
                                        Icons.Filled.Clear,
                                        contentDescription = "Clear",
                                        tint = colorScheme.onSurfaceVariant,
                                        modifier = Modifier.size(16.dp)
                                    )
                                }
                            }
                        },
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = colorScheme.primary,
                            unfocusedBorderColor = colorScheme.outline
                        )
                    )
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = { submitQuery(inputMessage) },
                        enabled = inputMessage.isNotBlank() && !isLoading,
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = colorScheme.primary,
                            contentColor = colorScheme.onPrimary
                        )
                    ) {
                        Icon(
                            Icons.AutoMirrored.Filled.Send,
                            contentDescription = "Send",
                            modifier = Modifier.size(18.dp)
                        )
                    }
                }
            }
        }

        // Configuration Dialog
        if (showSettingsDialog) {
            AlertDialog(
                onDismissRequest = { showSettingsDialog = false },
                title = {
                    Text(
                        stringResource(R.string.ai_chatbot_settings_title),
                        fontFamily = BitchatFontFamily,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            "Configure backend server or direct Groq key for emergency AI:",
                            fontFamily = BitchatFontFamily,
                            fontSize = 12.sp,
                            color = colorScheme.onSurfaceVariant
                        )
                        OutlinedTextField(
                            value = serverUrlInput,
                            onValueChange = { serverUrlInput = it },
                            label = {
                                Text(
                                    stringResource(R.string.ai_chatbot_server_url_label),
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 12.sp
                                )
                            },
                            placeholder = { Text("Empty = use Sync address (https://…)", fontFamily = BitchatFontFamily) },
                            singleLine = true,
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp
                            ),
                            modifier = Modifier.fillMaxWidth()
                        )
                        OutlinedTextField(
                            value = groqApiKeyInput,
                            onValueChange = { groqApiKeyInput = it },
                            label = {
                                Text(
                                    stringResource(R.string.ai_chatbot_groq_key_label),
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 12.sp
                                )
                            },
                            placeholder = { Text("gsk_...", fontFamily = BitchatFontFamily) },
                            singleLine = true,
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp
                            ),
                            modifier = Modifier.fillMaxWidth()
                        )
                        Text(
                            "Guardrail protection is active locally and in the cloud.",
                            fontFamily = BitchatFontFamily,
                            fontSize = 11.sp,
                            color = colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                        )
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            aiClient.serverUrl = serverUrlInput
                            aiClient.groqApiKey = groqApiKeyInput
                            showSettingsDialog = false
                        },
                        colors = ButtonDefaults.buttonColors(
                            containerColor = colorScheme.primary,
                            contentColor = colorScheme.onPrimary
                        )
                    ) {
                        Text("Save", fontFamily = BitchatFontFamily, fontSize = 13.sp)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { showSettingsDialog = false }) {
                        Text("Cancel", fontFamily = BitchatFontFamily, fontSize = 13.sp, color = colorScheme.onSurfaceVariant)
                    }
                }
            )
        }
    }
}
