package com.bitchat.android.util

import android.content.Context
import android.util.Log
import com.bitchat.android.services.AppStateStore
import com.bitchat.android.ui.map.parseGeoTag
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Pushes new chat messages to the civilization endpoint automatically.
 *
 * Watches the public mesh timeline and the shelter list. Whenever a message
 * the sync carries (geo-tagged text, a photo or a voice note) is sent OR received, or a shelter
 * changes, it schedules a flush. That makes every online phone a gateway for
 * nearby offline phones. A short debounce turns a burst of messages into one
 * upload. The "Send now" button in Sync settings is no longer required.
 *
 * Scheduling is a no-op while Sync is disabled (see [SyncWorkScheduler]).
 */
object AutoSyncTrigger {
    private const val TAG = "AutoSyncTrigger"
    private const val DEBOUNCE_MS = 3_000L

    @Volatile
    private var started = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @OptIn(FlowPreview::class)
    fun start(context: Context) {
        if (started) return
        started = true
        val appContext = context.applicationContext

        val syncableMessageIds = AppStateStore.publicMessages
            .map { messages ->
                messages.asSequence()
                    .filter {
                        parseGeoTag(it.content) != null ||
                            it.type == com.bitchat.android.model.BitchatMessageType.Image ||
                            it.type == com.bitchat.android.model.BitchatMessageType.Audio
                    }
                    .map { it.id }
                    .toSet()
            }
            .distinctUntilChanged()

        scope.launch {
            combine(syncableMessageIds, AppStateStore.shelters) { ids, shelters -> ids to shelters }
                .distinctUntilChanged()
                .drop(1) // skip the initial snapshot; reconnect/startup flushes are handled elsewhere
                .debounce(DEBOUNCE_MS)
                .collect {
                    try {
                        SyncWorkScheduler.scheduleFlush(appContext)
                    } catch (e: Exception) {
                        Log.w(TAG, "Auto sync scheduling failed: ${e.message}")
                    }
                }
        }
    }
}
