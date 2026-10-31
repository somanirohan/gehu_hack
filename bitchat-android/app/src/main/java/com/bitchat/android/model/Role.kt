package com.bitchat.android.model

import android.content.Context
import android.os.Parcelable
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.bitchat.android.R
import kotlinx.parcelize.Parcelize

/**
 * Emergency-response node role announced in the IdentityAnnouncement TLV 0x06
 * and optionally echoed as a 1-byte category prefix on broadcast MESSAGE
 * payloads (gated by the BitchatPacket [com.bitchat.android.protocol.BinaryProtocol.Flags.HAS_CATEGORY] flag bit).
 *
 * Wire value is a single UByte. [UNSET] (0x00) keeps old peers and plain-text
 * broadcasts byte-for-byte backward compatible with prior clients: no flag is
 * set and no category byte is prepended.
 */
@Parcelize
enum class Role(val value: UByte) : Parcelable {
    UNSET(0x00u),
    CIVILIAN(0x01u),
    AMBULANCE(0x02u),
    FIRE(0x03u),
    GOV(0x04u),
    ADMIN(0x05u),
    SHELTER(0x06u),
    DRONE(0x07u),
    RESCUE(0x08u);

    @get:StringRes
    val labelResId: Int
        get() = stringRes(this)

    companion object {
        fun fromValue(value: UByte): Role =
            values().firstOrNull { it.value == value } ?: UNSET

        @StringRes
        fun stringRes(role: Role): Int = when (role) {
            UNSET -> R.string.role_all
            CIVILIAN -> R.string.role_civilian
            AMBULANCE -> R.string.role_ambulance
            ADMIN -> R.string.role_admin
            SHELTER -> R.string.role_shelter
            DRONE -> R.string.role_drone
            RESCUE -> R.string.role_rescue
            FIRE -> R.string.role_fire
            GOV -> R.string.role_gov
        }

        /** Visible label used by the role-chip filter row and profile selector. */
        fun displayLabel(role: Role, context: Context? = null): String {
            if (context != null) {
                return context.getString(stringRes(role))
            }
            return when (role) {
                UNSET -> "All"
                CIVILIAN -> "Civilian"
                AMBULANCE -> "Ambulance"
                ADMIN -> "Admin"
                SHELTER -> "Shelter"
                DRONE -> "Drone"
                RESCUE -> "Rescue"
                FIRE -> "Fire"
                GOV -> "Gov"
            }
        }
    }
}

/** Composable helper to get localized role name. */
@Composable
fun Role.localizedName(): String = stringResource(Role.stringRes(this))