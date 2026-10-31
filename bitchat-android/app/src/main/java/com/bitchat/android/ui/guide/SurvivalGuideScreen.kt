package com.bitchat.android.ui.guide

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
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
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import com.bitchat.android.ui.theme.BitchatFontFamily
import com.bitchat.android.ui.AboutCardShape
import com.bitchat.android.ui.AboutHorizontalPadding
import com.bitchat.android.ui.theme.LocalBitchatPalette
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.res.stringResource
import com.bitchat.android.R
import com.bitchat.android.ui.LanguagePreferenceManager
import com.bitchat.android.net.DisasterAiClient
import com.bitchat.android.net.DisasterAiResponse
import kotlinx.coroutines.launch

/**
 * A comprehensive, offline-first Disaster Survival Guide.
 *
 * Provides actionable protocols for earthquakes/building collapse, cyclones, landslides,
 * flash floods, fire, emergency trauma first aid, and offline search & rescue signaling.
 */
data class SurvivalSection(
    val id: String,
    val title: String,
    val emoji: String,
    val category: String,
    val accentColor: Color? = null,
    val summary: String,
    val criticalAlert: String? = null,
    val steps: List<SurvivalStep>
)

data class SurvivalStep(
    val phase: String, // e.g. "Immediate Action", "During", "If Trapped", "After"
    val tips: List<String>
)

val SURVIVAL_SECTIONS: List<SurvivalSection> = listOf(
    SurvivalSection(
        id = "collapse",
        title = "Building Collapse & Earthquake",
        emoji = "🏢",
        category = "Structural",
        accentColor = Color(0xFFFF5252),
        summary = "Immediate protocols for tremors, structural failures, and surviving trapped beneath rubble.",
        criticalAlert = "DO NOT ignite matches or lighters beneath rubble; ruptured gas mains can trigger explosions.",
        steps = listOf(
            SurvivalStep(
                phase = "When Shaking Starts",
                tips = listOf(
                    "DROP, COVER, and HOLD ON: Drop to hands and knees under a sturdy desk or interior table.",
                    "If no desk is nearby, crouch against an interior wall away from glass, mirrors, and tall furniture.",
                    "Cover your head and neck with your arms and tuck your torso tightly.",
                    "Do NOT rush outside or use elevators during tremors; falling masonry and glass cause 70% of injuries."
                )
            ),
            SurvivalStep(
                phase = "If Trapped in Rubble",
                tips = listOf(
                    "Cover your mouth and nose with a shirt or cloth to filter lethal pulverized concrete dust.",
                    "Conserve oxygen & voice: Avoid continuous screaming which fills your lungs with dust and depletes air.",
                    "Rule of Three (Acoustic Signaling): Tap 3 sharp beats on metal pipes, beams, or walls using a stone or metal object, pause 10 seconds, repeat. Acoustic search sensors (geophones) track rhythmic taps.",
                    "Only shout when you distinctly hear rescue workers or search dogs nearby.",
                    "Stay still to prevent shifting unstable debris slabs above you."
                )
            ),
            SurvivalStep(
                phase = "Evacuation & Aftermath",
                tips = listOf(
                    "Check for gas leaks before using electricity: smell for sulfur/rotten eggs. If suspected, shut off main valve and leave immediately.",
                    "Wear sturdy shoes immediately to protect against shattered glass and exposed rebar.",
                    "Prepare for severe aftershocks which often bring down already compromised structures."
                )
            )
        )
    ),
    SurvivalSection(
        id = "cyclone",
        title = "Cyclone, Hurricane & Severe Storm",
        emoji = "🌀",
        category = "Weather",
        accentColor = Color(0xFF29B6F6),
        summary = "Wind resistance, structural sheltering, and navigating the eye of the storm.",
        criticalAlert = "Beware the Eye of the Storm: A sudden calm means you are only halfway through. Destructive winds will reverse direction without warning.",
        steps = listOf(
            SurvivalStep(
                phase = "Pre-Storm Preparation",
                tips = listOf(
                    "Store 4-5 days of drinking water in closed containers (minimum 3 liters per person per day).",
                    "Charge all mobile devices and external power banks; keep in sealed waterproof plastic bags.",
                    "Anchor or bring indoors all loose outdoor objects (roof sheets, pots, bicycles) which become deadly projectiles in 100+ km/h winds.",
                    "Board up or tape glass windows with heavy cross-taping to prevent explosive glass fragmentation."
                )
            ),
            SurvivalStep(
                phase = "During the Cyclone",
                tips = listOf(
                    "Shelter in the innermost room on the ground floor (bathroom, corridor, stairwell) with no exterior windows.",
                    "Disconnect main electrical breakers and gas supplies before high winds intensify.",
                    "Never venture outside during the lull (eye); the second half of the storm wall brings even more violent wind shear.",
                    "Keep battery-powered radios or this Bitchat mesh app open for emergency broadcasts."
                )
            ),
            SurvivalStep(
                phase = "Post-Storm Safety",
                tips = listOf(
                    "Never step into standing water near utility poles or fallen lines—risk of electrocution.",
                    "Boil all drinking water for at least 3 minutes; storm surges frequently cross-contaminate municipal water.",
                    "Watch out for displaced venomous snakes and wild animals seeking dry refuge in buildings."
                )
            )
        )
    ),
    SurvivalSection(
        id = "landslide",
        title = "Landslide & Mudflow",
        emoji = "🏔️",
        category = "Geological",
        accentColor = Color(0xFF8D6E63),
        summary = "Early acoustic warnings, rapid perpendicular escape, and debris survival.",
        criticalAlert = "If you hear a low rumble like an approaching freight train or see trees tilting, evacuate IMMEDIATELY.",
        steps = listOf(
            SurvivalStep(
                phase = "Early Warning Signs",
                tips = listOf(
                    "Sudden changes in water flow from clear to heavily mud-laden creeks or springs.",
                    "Trees or utility poles tilting, fences warping, or cracks appearing in road asphalt and hillside soil.",
                    "Rumbling sounds that gradually grow louder as soil and boulders mobilize upstream."
                )
            ),
            SurvivalStep(
                phase = "Immediate Evacuation",
                tips = listOf(
                    "Flee PERPENDICULAR to the slide path, never downhill in the direction of the flow.",
                    "Get to higher ground immediately; mudflows can travel up to 50 km/h and can easily outrun a running person.",
                    "Stay alert when driving: road embankments and culverts are particularly vulnerable to sudden collapse."
                )
            ),
            SurvivalStep(
                phase = "If Escape is Impossible",
                tips = listOf(
                    "Curl tightly into a fetal ball and lock hands firmly around the back of your head and neck.",
                    "Position yourself behind a large, rooted tree or sturdy boulder facing away from the flow to deflect heavy impacts.",
                    "After the slide stops, listen for secondary slides which often follow within minutes or hours."
                )
            )
        )
    ),
    SurvivalSection(
        id = "flood",
        title = "Flash Flood & Water Surge",
        emoji = "🌊",
        category = "Hydrological",
        accentColor = Color(0xFF00ACC1),
        summary = "Vehicle water escape, vertical evacuation, and avoiding hidden hydraulic hazards.",
        criticalAlert = "Turn Around, Don't Drown: Just 15 cm (6 inches) of moving water sweeps an adult; 30-60 cm floats cars and SUVs.",
        steps = listOf(
            SurvivalStep(
                phase = "Immediate Threat",
                tips = listOf(
                    "Move immediately to the highest accessible ground or upper floors of substantial concrete structures.",
                    "Attic Trap Warning: NEVER climb into an attic without roof access or an axe; rising floodwaters can trap and drown you.",
                    "Do NOT attempt to walk, swim, or drive through flooded roads or bridges. Submerged pavement is often eroded away.",
                    "If your car stalls in rapidly rising water, abandon the vehicle immediately and climb onto the roof or higher ground."
                )
            ),
            SurvivalStep(
                phase = "Waterborne Hazards",
                tips = listOf(
                    "Stay clear of electrical conduits, submerged junction boxes, and downed wires.",
                    "Never enter storm drains, culverts, or drainage canals—powerful suction can pull a person under instantly.",
                    "Disinfect any open cuts or scrapes immediately; flood water is contaminated with raw sewage, oil, and pathogens."
                )
            ),
            SurvivalStep(
                phase = "Signaling Rescuers",
                tips = listOf(
                    "Display bright clothing, tarps, or mirrors from the roof so rescue boats and drones can spot you.",
                    "Use whistle or phone flashlight flashes in sets of 3 to signal boat operators in the dark."
                )
            )
        )
    ),
    SurvivalSection(
        id = "fire",
        title = "Wildfire & Structural Fire",
        emoji = "🔥",
        category = "Thermal",
        accentColor = Color(0xFFFF6F00),
        summary = "Smoke inhalation protection, navigating burning buildings, and wildfire defense.",
        criticalAlert = "Smoke kills before flames. 80% of fire deaths are from carbon monoxide and toxic gas inhalation. CRAWL LOW.",
        steps = listOf(
            SurvivalStep(
                phase = "Building Evacuation",
                tips = listOf(
                    "Stay below the smoke line: The cleanest, coolest, most oxygenated air is 30–60 cm above the floor.",
                    "Touch doors with the back of your hand before turning the handle: if hot or if smoke pours around seams, DO NOT open.",
                    "If clothes catch fire: STOP, DROP, and ROLL to smother oxygen; cover face with hands.",
                    "Never use elevators in a fire; shafts act as chimneys drawing deadly smoke and power can cut out."
                )
            ),
            SurvivalStep(
                phase = "If Trapped in a Room",
                tips = listOf(
                    "Close the door and seal all cracks around seams with wet towels, clothes, or tape.",
                    "Open a window slightly at the top for air unless thick smoke is entering from outside.",
                    "Hang a brightly colored cloth or sheet from the window to alert firefighters to your location."
                )
            ),
            SurvivalStep(
                phase = "Wildfire Approaching",
                tips = listOf(
                    "Wear 100% cotton or wool natural fibers; synthetic fabrics melt and cause devastating skin burns.",
                    "Cover mouth with a damp cotton bandanna and protect eyes with swimming goggles or wrap-around glasses.",
                    "If trapped outdoors, seek a depression in bare ground, rock outcrop, or burned-over area with zero fuel."
                )
            )
        )
    ),
    SurvivalSection(
        id = "firstaid",
        title = "Emergency Trauma & First Aid",
        emoji = "🩹",
        category = "Medical",
        accentColor = Color(0xFF43A047),
        summary = "Controlling severe bleeding, recovery positions, shock management, and water purification.",
        criticalAlert = "Massive bleeding can kill in 3 minutes. Apply continuous, direct, firm pressure with both hands immediately.",
        steps = listOf(
            SurvivalStep(
                phase = "Severe Bleeding Control",
                tips = listOf(
                    "Direct Pressure: Place a clean cloth or gauze directly onto the wound and push down with full body weight without releasing.",
                    "Wound Packing: For deep groin or armpit junctional wounds, pack cloth tightly into the wound cavity and hold extreme pressure.",
                    "Tourniquet: For catastrophic limb bleeding where pressure fails, apply a tourniquet 5–7 cm above the wound (never over a joint), tighten until bleeding stops, and mark the exact time on forehead/strap."
                )
            ),
            SurvivalStep(
                phase = "Unconscious Breathing Patient",
                tips = listOf(
                    "Recovery Position: Roll the patient onto their side with their upper knee bent forward to prevent them from rolling back.",
                    "Tilt their head gently backward to keep the tongue from blocking the airway.",
                    "This prevents asphyxiation and choking if the patient vomits."
                )
            ),
            SurvivalStep(
                phase = "Emergency Water Purification",
                tips = listOf(
                    "Rolling Boil: Bring water to a vigorous, bubbling boil for at least 1 full minute (3 minutes at high altitude).",
                    "Cloth Filtration: Pre-filter cloudy water through 4 layers of clean cotton cloth to remove sand, silt, and parasites before boiling.",
                    "Never drink seawater or urine; the high solute concentration accelerates organ failure."
                )
            )
        )
    ),
    SurvivalSection(
        id = "signaling",
        title = "Offline Rescue Signaling",
        emoji = "📡",
        category = "Rescue",
        accentColor = Color(0xFF7E57C2),
        summary = "International distress codes, acoustic alerts, visual heli-markings, and Bitchat SOS.",
        criticalAlert = "International Distress Rule: Any signal repeated THREE times (3 whistle blasts, 3 fires, 3 flashes) signifies an emergency.",
        steps = listOf(
            SurvivalStep(
                phase = "Acoustic Signals",
                tips = listOf(
                    "Whistle: 3 sharp, loud blasts. Pause for 30 seconds to listen for answering whistles or shouts, then repeat.",
                    "Pipe / Wall Tapping: 3 solid metallic knocks against pipes or beams carries miles through structural rubble.",
                    "Vehicle Horn: 3 long honks repeated every few minutes if vehicle battery is functional."
                )
            ),
            SurvivalStep(
                phase = "Visual & Aerial Signals",
                tips = listOf(
                    "Ground-to-Air Symbols (make with rocks, logs, or contrasting fabric on open ground):",
                    "  'V' = Require Assistance",
                    "  'X' = Require Medical Assistance",
                    "  '->' = Moving in this direction",
                    "Mirror / Screen Flash: Direct sunlight reflection toward circling drones or helicopters by aiming between two fingers in a V-notch.",
                    "Signal Fires: 3 fires arranged in a triangle or straight line. Use green leafy branches for dense white smoke by day; dry wood for bright flame by night."
                )
            ),
            SurvivalStep(
                phase = "Digital Mesh SOS",
                tips = listOf(
                    "Hit the red 'SOS' button in Bitchat: broadcasts emergency packets with your GPS coordinate across nearby devices without internet.",
                    "Responders on the tactical map will immediately see an SOS marker at your coordinates."
                )
            )
        )
    )
)

/**
 * Full page Survival Guide Screen.
 */
@Composable
fun SurvivalGuideScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier
) {
    BackHandler(onBack = onBack)

    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val aiClient = remember { DisasterAiClient(context) }

    var searchQuery by remember { mutableStateOf("") }
    var expandedSectionIds by remember { mutableStateOf(setOf("collapse", "cyclone", "firstaid")) }

    val currentTag = remember { LanguagePreferenceManager.currentLanguageTag() }
    val currentLang = remember(currentTag) {
        if (currentTag.isNotBlank()) currentTag.split("-").first().lowercase() else java.util.Locale.getDefault().language.lowercase()
    }

    val localizedSections = remember(context, currentLang) {
        SurvivalGuideLocalization.getSections(context)
    }

    val categoryNames = remember(currentLang) {
        when (currentLang) {
            "hi" -> listOf("सभी", "ढांचागत", "मौसम", "भूगर्भीय", "जलीय", "तापीय", "चिकित्सीय", "बचाव")
            "mr" -> listOf("सर्व", "संरचनात्मक", "हवामान", "भूगर्भीय", "जलीय", "औष्णिक", "वैद्यकीय", "बचाव")
            "ta" -> listOf("அனைத்தும்", "கட்டமைப்பு", "வானிலை", "புவியியல்", "நீரியல்", "வெப்பவியல்", "மருத்துவம்", "மீட்பு")
            "te" -> listOf("అన్నీ", "నిర్మాణపరమైన", "వాతావరణం", "భూగర్భపరమైన", "జలసంబంధిత", "ఉష్ణసంబంధిత", "వైద్యపరమైన", "రెస్క్యూ")
            else -> listOf("All", "Structural", "Weather", "Geological", "Hydrological", "Thermal", "Medical", "Rescue")
        }
    }
    var selectedCategoryIndex by remember { mutableStateOf(0) }

    // Disaster AI State
    var aiQuery by remember { mutableStateOf("") }
    var isAiLoading by remember { mutableStateOf(false) }
    var aiResponse by remember { mutableStateOf<DisasterAiResponse?>(null) }
    var showAiSettingsDialog by remember { mutableStateOf(false) }
    var serverUrlInput by remember { mutableStateOf(aiClient.serverUrl) }

    val filteredSections = remember(searchQuery, selectedCategoryIndex, localizedSections) {
        localizedSections.filter { section ->
            val matchesCategory = selectedCategoryIndex == 0 || (selectedCategoryIndex < categoryNames.size && section.category.equals(categoryNames[selectedCategoryIndex], ignoreCase = true))
            val matchesQuery = if (searchQuery.isBlank()) true else {
                val q = searchQuery.trim().lowercase()
                section.title.lowercase().contains(q) ||
                    section.summary.lowercase().contains(q) ||
                    section.steps.any { step ->
                        step.phase.lowercase().contains(q) || step.tips.any { it.lowercase().contains(q) }
                    }
            }
            matchesCategory && matchesQuery
        }
    }

    val colorScheme = MaterialTheme.colorScheme

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(colorScheme.background)
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Top App Bar
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
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = stringResource(R.string.survival_guide_title),
                                fontFamily = BitchatFontFamily,
                                fontSize = 17.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = colorScheme.onSurface
                            )
                            Text(
                                text = stringResource(R.string.survival_guide_subtitle),
                                fontFamily = BitchatFontFamily,
                                fontSize = 12.sp,
                                color = colorScheme.onSurfaceVariant
                            )
                        }
                    }

                    // Search input
                    OutlinedTextField(
                        value = searchQuery,
                        onValueChange = { searchQuery = it },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        placeholder = {
                            Text(
                                stringResource(R.string.survival_guide_search_hint),
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp,
                                color = colorScheme.onSurfaceVariant
                            )
                        },
                        leadingIcon = {
                            Icon(
                                Icons.Filled.Search,
                                contentDescription = "Search",
                                tint = colorScheme.onSurfaceVariant,
                                modifier = Modifier.size(18.dp)
                            )
                        },
                        trailingIcon = {
                            if (searchQuery.isNotEmpty()) {
                                IconButton(onClick = { searchQuery = "" }) {
                                    Icon(
                                        Icons.Filled.Clear,
                                        contentDescription = "Clear",
                                        tint = colorScheme.onSurfaceVariant,
                                        modifier = Modifier.size(16.dp)
                                    )
                                }
                            }
                        },
                        singleLine = true,
                        shape = RoundedCornerShape(12.dp),
                        textStyle = MaterialTheme.typography.bodyMedium.copy(
                            fontFamily = BitchatFontFamily,
                            fontSize = 13.sp
                        ),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = colorScheme.primary,
                            unfocusedBorderColor = colorScheme.outline
                        )
                    )

                    // Category filter chips
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState())
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp)
                    ) {
                        categoryNames.forEachIndexed { idx, cat ->
                            FilterChip(
                                selected = selectedCategoryIndex == idx,
                                onClick = { selectedCategoryIndex = idx },
                                label = {
                                    Text(
                                        cat,
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 12.sp,
                                        fontWeight = if (selectedCategoryIndex == idx) FontWeight.SemiBold else FontWeight.Normal
                                    )
                                },
                                shape = RoundedCornerShape(10.dp),
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = colorScheme.primary.copy(alpha = 0.15f),
                                    selectedLabelColor = colorScheme.primary,
                                    containerColor = colorScheme.surfaceVariant.copy(alpha = 0.5f),
                                    labelColor = colorScheme.onSurfaceVariant
                                )
                            )
                        }
                    }
                }
            }

            // Guide Content List
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(
                    start = AboutHorizontalPadding,
                    end = AboutHorizontalPadding,
                    top = 12.dp,
                    bottom = 32.dp
                ),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                // Quick SOS banner
                item(key = "quick_banner") {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = AboutCardShape,
                        color = colorScheme.errorContainer,
                        border = BorderStroke(1.dp, colorScheme.error.copy(alpha = 0.35f))
                    ) {
                        Row(
                            modifier = Modifier.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("🚨", fontSize = 18.sp)
                            Spacer(Modifier.width(12.dp))
                            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                Text(
                                    text = stringResource(R.string.survival_guide_quick_crisis),
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = colorScheme.onErrorContainer
                                )
                                Text(
                                    text = stringResource(R.string.survival_guide_quick_crisis_desc),
                                    fontFamily = BitchatFontFamily,
                                    fontSize = 12.sp,
                                    lineHeight = 16.sp,
                                    color = colorScheme.onErrorContainer.copy(alpha = 0.85f)
                                )
                            }
                        }
                    }
                }

                // Interactive Disaster AI Assistant (Qwen2.5-1.5B + SQLite)
                item(key = "disaster_ai_assistant") {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = AboutCardShape,
                        color = colorScheme.surface,
                        border = BorderStroke(1.dp, colorScheme.outlineVariant)
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(
                                    modifier = Modifier.weight(1f),
                                    verticalArrangement = Arrangement.spacedBy(2.dp)
                                ) {
                                    Text(
                                        text = stringResource(R.string.survival_guide_ai_title),
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 14.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colorScheme.onSurface
                                    )
                                    Text(
                                        text = stringResource(R.string.survival_guide_ai_subtitle),
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 12.sp,
                                        color = colorScheme.onSurfaceVariant
                                    )
                                }
                                IconButton(
                                    onClick = {
                                        serverUrlInput = aiClient.serverUrl
                                        showAiSettingsDialog = true
                                    },
                                    modifier = Modifier.size(28.dp)
                                ) {
                                    Icon(
                                        Icons.Filled.Settings,
                                        contentDescription = "Server Settings",
                                        tint = colorScheme.onSurfaceVariant,
                                        modifier = Modifier.size(16.dp)
                                    )
                                }
                            }

                            Spacer(Modifier.height(10.dp))

                            // Query input row
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                OutlinedTextField(
                                    value = aiQuery,
                                    onValueChange = { aiQuery = it },
                                    modifier = Modifier.weight(1f),
                                    placeholder = {
                                        Text(
                                            stringResource(R.string.survival_guide_ai_hint),
                                            fontFamily = BitchatFontFamily,
                                            fontSize = 13.sp,
                                            color = colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                                        )
                                    },
                                    singleLine = true,
                                    shape = RoundedCornerShape(10.dp),
                                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 13.sp
                                    ),
                                    colors = OutlinedTextFieldDefaults.colors(
                                        focusedBorderColor = colorScheme.primary,
                                        unfocusedBorderColor = colorScheme.outline
                                    )
                                )
                                Spacer(Modifier.width(8.dp))
                                Button(
                                    onClick = {
                                        if (aiQuery.isNotBlank() && !isAiLoading) {
                                            isAiLoading = true
                                            coroutineScope.launch {
                                                aiResponse = aiClient.askDisasterAi(aiQuery, language = currentLang)
                                                isAiLoading = false
                                            }
                                        }
                                    },
                                    enabled = aiQuery.isNotBlank() && !isAiLoading,
                                    shape = RoundedCornerShape(10.dp),
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = colorScheme.primary,
                                        contentColor = colorScheme.onPrimary
                                    )
                                ) {
                                    if (isAiLoading) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.size(16.dp),
                                            color = colorScheme.onPrimary,
                                            strokeWidth = 2.dp
                                        )
                                    } else {
                                        Icon(
                                            Icons.AutoMirrored.Filled.Send,
                                            contentDescription = "Ask",
                                            modifier = Modifier.size(16.dp)
                                        )
                                    }
                                }
                            }

                            // Quick query suggestions (localized)
                            val quickSuggestions = remember(currentLang) {
                                when (currentLang) {
                                    "hi" -> listOf("मलबे में फंसे हैं", "चक्रवात की आंख", "बाढ़ का पानी शुद्ध करना", "गंभीर रक्तस्राव")
                                    "mr" -> listOf("ढिगाऱ्याखाली अडकलो", "चक्रीवादळाचा डोळा", "पाणी शुद्ध करणे", "गंभीर रक्तस्त्राव")
                                    "ta" -> listOf("இடிபாடுகளில் சிக்கினால்", "புயலின் மையம்", "குடிநீர் சுத்திகரிப்பு", "இரத்தப்போக்கு கட்டுப்பாடு")
                                    "te" -> listOf("శిథిలాల్లో చిక్కుకుంటే", "తుఫాను కన్ను", "నీటి శుద్ధీకరణ", "తీవ్ర రక్తస్రావం")
                                    else -> listOf("Trapped in rubble", "Cyclone eye calm", "Purify flood water", "Severe bleeding")
                                }
                            }
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .horizontalScroll(rememberScrollState())
                                    .padding(top = 8.dp),
                                horizontalArrangement = Arrangement.spacedBy(6.dp)
                            ) {
                                quickSuggestions.forEach { suggestion ->
                                    Surface(
                                        shape = RoundedCornerShape(8.dp),
                                        color = colorScheme.surfaceVariant.copy(alpha = 0.45f),
                                        border = BorderStroke(1.dp, colorScheme.outlineVariant),
                                        modifier = Modifier.clickable {
                                            aiQuery = suggestion
                                            isAiLoading = true
                                            coroutineScope.launch {
                                                aiResponse = aiClient.askDisasterAi(suggestion, language = currentLang)
                                                isAiLoading = false
                                            }
                                        }
                                    ) {
                                        Text(
                                            text = suggestion,
                                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp),
                                            fontFamily = BitchatFontFamily,
                                            fontSize = 12.sp,
                                            color = colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                            }

                            // Response display
                            aiResponse?.let { resp ->
                                Spacer(Modifier.height(10.dp))
                                Surface(
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(10.dp),
                                    color = colorScheme.surfaceVariant.copy(alpha = 0.35f),
                                    border = BorderStroke(1.dp, colorScheme.outlineVariant)
                                ) {
                                    Column(modifier = Modifier.padding(12.dp)) {
                                        Row(
                                            modifier = Modifier.fillMaxWidth(),
                                            horizontalArrangement = Arrangement.SpaceBetween,
                                            verticalAlignment = Alignment.CenterVertically
                                        ) {
                                            Text(
                                                text = if (resp.isOfflineFallback) "Offline Fallback" else "Qwen2.5-1.5B (Local)",
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 11.sp,
                                                fontWeight = FontWeight.SemiBold,
                                                color = colorScheme.primary
                                            )
                                            TextButton(
                                                onClick = { aiResponse = null },
                                                contentPadding = PaddingValues(0.dp)
                                            ) {
                                                Text(
                                                    "Dismiss",
                                                    fontFamily = BitchatFontFamily,
                                                    fontSize = 11.sp,
                                                    color = colorScheme.onSurfaceVariant
                                                )
                                            }
                                        }

                                        resp.criticalWarning?.let { warn ->
                                            Spacer(Modifier.height(6.dp))
                                            Surface(
                                                modifier = Modifier.fillMaxWidth(),
                                                shape = RoundedCornerShape(8.dp),
                                                color = colorScheme.errorContainer
                                            ) {
                                                Text(
                                                    text = "⚠️ $warn",
                                                    modifier = Modifier.padding(8.dp),
                                                    fontFamily = BitchatFontFamily,
                                                    fontSize = 12.sp,
                                                    lineHeight = 16.sp,
                                                    fontWeight = FontWeight.SemiBold,
                                                    color = colorScheme.onErrorContainer
                                                )
                                            }
                                        }

                                        Spacer(Modifier.height(8.dp))
                                        Text(
                                            text = resp.answer,
                                            fontFamily = BitchatFontFamily,
                                            fontSize = 13.sp,
                                            lineHeight = 18.sp,
                                            color = colorScheme.onSurface
                                        )

                                        resp.matchedProtocol?.let { proto ->
                                            Spacer(Modifier.height(6.dp))
                                            Text(
                                                text = "Protocol: $proto",
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 11.sp,
                                                color = colorScheme.onSurfaceVariant
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                if (filteredSections.isEmpty()) {
                    item(key = "empty_state") {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 40.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                "No survival tips matched your search.\nTry searching for 'earthquake', 'bleed', 'fire', or 'water'.",
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp,
                                lineHeight = 18.sp,
                                color = colorScheme.onSurfaceVariant,
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center
                            )
                        }
                    }
                }

                items(filteredSections, key = { it.id }) { section ->
                    val isExpanded = section.id in expandedSectionIds

                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .animateContentSize(),
                        shape = AboutCardShape,
                        color = colorScheme.surface,
                        border = BorderStroke(1.dp, colorScheme.outlineVariant)
                    ) {
                        Column(modifier = Modifier.fillMaxWidth()) {
                            // Section Header
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        expandedSectionIds = if (isExpanded) {
                                            expandedSectionIds - section.id
                                        } else {
                                            expandedSectionIds + section.id
                                        }
                                    }
                                    .padding(14.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(section.emoji, fontSize = 18.sp)
                                Spacer(Modifier.width(12.dp))
                                Column(
                                    modifier = Modifier.weight(1f),
                                    verticalArrangement = Arrangement.spacedBy(2.dp)
                                ) {
                                    Text(
                                        text = section.title,
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 14.sp,
                                        fontWeight = FontWeight.SemiBold,
                                        color = colorScheme.onSurface
                                    )
                                    Text(
                                        text = section.summary,
                                        fontFamily = BitchatFontFamily,
                                        fontSize = 12.sp,
                                        lineHeight = 16.sp,
                                        color = colorScheme.onSurfaceVariant
                                    )
                                }
                                Icon(
                                    imageVector = if (isExpanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                                    contentDescription = if (isExpanded) "Collapse" else "Expand",
                                    tint = colorScheme.onSurfaceVariant
                                )
                            }

                            // Expanded Content
                            AnimatedVisibility(visible = isExpanded) {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(start = 14.dp, end = 14.dp, bottom = 14.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp)
                                ) {
                                    // Critical Alert Callout
                                    if (section.criticalAlert != null) {
                                        Surface(
                                            shape = RoundedCornerShape(10.dp),
                                            color = colorScheme.errorContainer,
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Text(
                                                text = "⚠️ ${section.criticalAlert}",
                                                modifier = Modifier.padding(10.dp),
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 12.sp,
                                                lineHeight = 17.sp,
                                                fontWeight = FontWeight.SemiBold,
                                                color = colorScheme.onErrorContainer
                                            )
                                        }
                                    }

                                    // Steps & Protocols
                                    section.steps.forEach { step ->
                                        Column(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .background(
                                                    colorScheme.surfaceVariant.copy(alpha = 0.45f),
                                                    RoundedCornerShape(10.dp)
                                                )
                                                .padding(10.dp),
                                            verticalArrangement = Arrangement.spacedBy(4.dp)
                                        ) {
                                            Text(
                                                text = step.phase,
                                                fontFamily = BitchatFontFamily,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.SemiBold,
                                                color = colorScheme.primary
                                            )
                                            step.tips.forEach { tip ->
                                                Row(
                                                    modifier = Modifier.fillMaxWidth(),
                                                    verticalAlignment = Alignment.Top
                                                ) {
                                                    Text(
                                                        "•",
                                                        fontFamily = BitchatFontFamily,
                                                        fontSize = 13.sp,
                                                        fontWeight = FontWeight.Bold,
                                                        color = colorScheme.primary,
                                                        modifier = Modifier.padding(end = 6.dp)
                                                    )
                                                    Text(
                                                        text = tip,
                                                        fontFamily = BitchatFontFamily,
                                                        fontSize = 13.sp,
                                                        lineHeight = 18.sp,
                                                        color = colorScheme.onSurface
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // Bottom safety disclaimer
                item(key = "disclaimer") {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .windowInsetsPadding(WindowInsets.navigationBars)
                            .padding(vertical = 12.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            stringResource(R.string.survival_guide_disclaimer),
                            fontFamily = BitchatFontFamily,
                            fontSize = 11.sp,
                            lineHeight = 15.sp,
                            color = colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center
                        )
                    }
                }
            }
        }

        // Server URL configuration dialog
        if (showAiSettingsDialog) {
            AlertDialog(
                onDismissRequest = { showAiSettingsDialog = false },
                title = {
                    Text(
                        "Disaster AI Server Config",
                        fontFamily = BitchatFontFamily,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold
                    )
                },
                text = {
                    Column {
                        Text(
                            "Enter the address of your local machine running Qwen2.5-1.5B (port 8800):",
                            fontSize = 12.sp,
                            fontFamily = BitchatFontFamily,
                            color = colorScheme.onSurfaceVariant
                        )
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = serverUrlInput,
                            onValueChange = { serverUrlInput = it },
                            label = { Text("Server URL", fontFamily = BitchatFontFamily, fontSize = 12.sp) },
                            placeholder = { Text("http://192.168.1.xxx:8800", fontFamily = BitchatFontFamily, fontSize = 12.sp) },
                            singleLine = true,
                            textStyle = MaterialTheme.typography.bodyMedium.copy(
                                fontFamily = BitchatFontFamily,
                                fontSize = 13.sp
                            ),
                            modifier = Modifier.fillMaxWidth()
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Default for Android Emulator: http://10.0.2.2:8800. For physical phone, use laptop's local Wi-Fi IP.",
                            fontSize = 11.sp,
                            fontFamily = BitchatFontFamily,
                            color = colorScheme.onSurfaceVariant.copy(alpha = 0.7f)
                        )
                    }
                },
                confirmButton = {
                    Button(
                        onClick = {
                            aiClient.serverUrl = serverUrlInput
                            showAiSettingsDialog = false
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
                    TextButton(onClick = { showAiSettingsDialog = false }) {
                        Text("Cancel", fontFamily = BitchatFontFamily, fontSize = 13.sp, color = colorScheme.onSurfaceVariant)
                    }
                }
            )
        }
    }
}

