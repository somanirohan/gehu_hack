package com.bitchat.android.ui.guide

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
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
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

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
    val accentColor: Color,
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

    var searchQuery by remember { mutableStateOf("") }
    var selectedCategory by remember { mutableStateOf("All") }
    var expandedSectionIds by remember { mutableStateOf(setOf("collapse", "cyclone", "firstaid")) }

    val categories = remember {
        listOf("All", "Structural", "Weather", "Geological", "Hydrological", "Thermal", "Medical", "Rescue")
    }

    val filteredSections = remember(searchQuery, selectedCategory) {
        SURVIVAL_SECTIONS.filter { section ->
            val matchesCategory = selectedCategory == "All" || section.category.equals(selectedCategory, ignoreCase = true)
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

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(Color(0xFF0A0F16))
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Top App Bar
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.95f),
                tonalElevation = 6.dp
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
                                contentDescription = "Back to Chat"
                            )
                        }
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "Disaster Survival Guide 🛡️",
                                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                            )
                            Text(
                                text = "100% Offline Emergency Knowledge Base",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
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
                        placeholder = { Text("Search disaster tip (e.g. rubble, bleed, fire)...", fontSize = 13.sp) },
                        leadingIcon = {
                            Icon(Icons.Filled.Search, contentDescription = "Search", modifier = Modifier.size(20.dp))
                        },
                        trailingIcon = {
                            if (searchQuery.isNotEmpty()) {
                                IconButton(onClick = { searchQuery = "" }) {
                                    Icon(Icons.Filled.Clear, contentDescription = "Clear", modifier = Modifier.size(18.dp))
                                }
                            }
                        },
                        singleLine = true,
                        shape = RoundedCornerShape(20.dp),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = MaterialTheme.colorScheme.primary,
                            unfocusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f),
                            focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
                            unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.2f)
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
                        categories.forEach { cat ->
                            FilterChip(
                                selected = selectedCategory == cat,
                                onClick = { selectedCategory = cat },
                                label = { Text(cat, fontSize = 12.sp) },
                                shape = CircleShape,
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = MaterialTheme.colorScheme.primary,
                                    selectedLabelColor = MaterialTheme.colorScheme.onPrimary
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
                    start = 14.dp,
                    end = 14.dp,
                    top = 10.dp,
                    bottom = 24.dp
                ),
                verticalArrangement = Arrangement.spacedBy(14.dp)
            ) {
                // Quick SOS banner
                item(key = "quick_banner") {
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = Color(0xFFB71C1C).copy(alpha = 0.22f)
                        )
                    ) {
                        Row(
                            modifier = Modifier.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("🚨", fontSize = 28.sp)
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(
                                    text = "In an active life-or-death crisis?",
                                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.Bold),
                                    color = Color(0xFFFF8A80)
                                )
                                Text(
                                    text = "Tap the red SOS button on the chat bar to broadcast your GPS beacon over the mesh.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f)
                                )
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
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center
                            )
                        }
                    }
                }

                items(filteredSections, key = { it.id }) { section ->
                    val isExpanded = section.id in expandedSectionIds

                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .animateContentSize(),
                        shape = RoundedCornerShape(18.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.94f)
                        ),
                        elevation = CardDefaults.cardElevation(defaultElevation = 3.dp)
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
                                Surface(
                                    shape = CircleShape,
                                    color = section.accentColor.copy(alpha = 0.18f),
                                    modifier = Modifier.size(46.dp)
                                ) {
                                    Box(contentAlignment = Alignment.Center) {
                                        Text(section.emoji, fontSize = 24.sp)
                                    }
                                }
                                Spacer(Modifier.width(12.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = section.title,
                                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                                    )
                                    Text(
                                        text = section.summary,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                Icon(
                                    imageVector = if (isExpanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                                    contentDescription = if (isExpanded) "Collapse" else "Expand",
                                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }

                            // Expanded Content
                            AnimatedVisibility(visible = isExpanded) {
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(start = 14.dp, end = 14.dp, bottom = 16.dp),
                                    verticalArrangement = Arrangement.spacedBy(10.dp)
                                ) {
                                    // Critical Alert Callout
                                    if (section.criticalAlert != null) {
                                        Surface(
                                            shape = RoundedCornerShape(12.dp),
                                            color = Color(0xFFD32F2F).copy(alpha = 0.15f),
                                            border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFFEF5350).copy(alpha = 0.4f)),
                                            modifier = Modifier.fillMaxWidth()
                                        ) {
                                            Row(
                                                modifier = Modifier.padding(10.dp),
                                                verticalAlignment = Alignment.Top
                                            ) {
                                                Text("⚠️", fontSize = 18.sp)
                                                Spacer(Modifier.width(8.dp))
                                                Text(
                                                    text = section.criticalAlert,
                                                    style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Medium),
                                                    color = Color(0xFFFF8A80)
                                                )
                                            }
                                        }
                                    }

                                    // Steps & Protocols
                                    section.steps.forEach { step ->
                                        Column(
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .background(
                                                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
                                                    RoundedCornerShape(12.dp)
                                                )
                                                .padding(12.dp),
                                            verticalArrangement = Arrangement.spacedBy(6.dp)
                                        ) {
                                            Text(
                                                text = "▶ ${step.phase}",
                                                style = MaterialTheme.typography.labelMedium.copy(fontWeight = FontWeight.Bold),
                                                color = section.accentColor
                                            )
                                            step.tips.forEach { tip ->
                                                Row(
                                                    modifier = Modifier.fillMaxWidth(),
                                                    verticalAlignment = Alignment.Top
                                                ) {
                                                    Text(
                                                        "•",
                                                        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                                                        color = MaterialTheme.colorScheme.primary,
                                                        modifier = Modifier.padding(end = 6.dp)
                                                    )
                                                    Text(
                                                        text = tip,
                                                        style = MaterialTheme.typography.bodySmall,
                                                        color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.9f),
                                                        lineHeight = 18.sp
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
                            "All protocols compiled for offline disaster emergency reference. Stay safe and assist others.",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center
                        )
                    }
                }
            }
        }
    }
}
