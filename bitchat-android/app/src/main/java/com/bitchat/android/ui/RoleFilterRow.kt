package com.bitchat.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.bitchat.android.model.Role
import com.bitchat.android.model.localizedName

import androidx.compose.foundation.layout.Box
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.ui.res.stringResource
import com.bitchat.android.R

/**
 * Emergency-response role filter row. Renders a sidebar toggle ("3 lines" / hamburger)
 * followed by an "All" chip and one chip per consumer role.
 */
@Composable
fun RoleFilterRow(
    selectedRoles: Set<Role>,
    availableRoles: Set<Role>,
    onToggle: (Role) -> Unit,
    onClearAll: () -> Unit,
    onOpenSidebar: () -> Unit = {},
    modifier: Modifier = Modifier
) {
    val colorScheme = MaterialTheme.colorScheme
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(44.dp)
            .padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.Start)
    ) {
        // "3 lines" (hamburger menu icon) before "All" to open the sidebar
        Surface(
            onClick = onOpenSidebar,
            shape = CircleShape,
            color = colorScheme.surfaceVariant.copy(alpha = 0.7f),
            contentColor = colorScheme.onSurface,
            modifier = Modifier.size(34.dp)
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    imageVector = Icons.Default.Menu,
                    contentDescription = stringResource(R.string.open_sidebar),
                    modifier = Modifier.size(20.dp),
                    tint = colorScheme.onSurface
                )
            }
        }

        Row(
            modifier = Modifier
                .weight(1f)
                .horizontalScroll(rememberScrollState()),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.Start)
        ) {
            // "All": highlighted when the subscription set is empty
            FilterChip(
                selected = selectedRoles.isEmpty(),
                onClick = onClearAll,
                label = { Text(com.bitchat.android.model.Role.UNSET.localizedName()) },
                colors = FilterChipDefaults.filterChipColors(
                    selectedContainerColor = colorScheme.primary,
                    selectedLabelColor = colorScheme.onPrimary
                ),
                shape = CircleShape
            )
            // One chip per non-UNSET role, unconditionally so responders can pre-subscribe.
            // FilterChip auto-sizes to its label (single-line), so the chip never wraps the text.
            availableRoles.forEach { role ->
                FilterChip(
                    selected = role in selectedRoles,
                    onClick = { onToggle(role) },
                    label = { Text(role.localizedName(), maxLines = 1) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = roleAccent(role, colorScheme.primary),
                        selectedLabelColor = Color.White
                    ),
                    shape = CircleShape
                )
            }
        }
    }
}

/** Stable demo-time color per responder role so chips stand out at a glance. */
private fun roleAccent(role: Role, base: Color): Color = when (role) {
    Role.CIVILIAN -> Color(0xFF43A047)  // green
    Role.AMBULANCE -> Color(0xFFE53935) // red
    Role.ADMIN -> Color(0xFF7B1FA2)     // purple
    Role.SHELTER -> Color(0xFF00ACC1)   // cyan
    Role.DRONE -> Color(0xFF3949AB)     // indigo
    Role.RESCUE -> Color(0xFFFF6F00)    // amber/orange
    Role.FIRE -> Color(0xFFFB8C00)      // orange
    Role.GOV -> Color(0xFF1E88E5)       // blue
    Role.UNSET -> base
}