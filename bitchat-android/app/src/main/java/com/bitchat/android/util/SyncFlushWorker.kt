package com.bitchat.android.util

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.bitchat.android.net.CivilizationSyncClient
import com.bitchat.android.net.FieldMediaUploader
import com.bitchat.android.services.AppStateStore
import com.bitchat.android.services.SyncBundleBuilder
import com.bitchat.android.services.SyncPreferences
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Background flush of accumulated mesh incident + shelter log to the user
 * configured civilization endpoint. Runs only while connected; backs off
 * per [SyncWorkScheduler] when network is unavailable. No raw device IDs or
 * keys are ever serialized — only message <id, sender display name, role,
 * lat/lon, content[:280]> and shelter descriptors.
 */
class SyncFlushWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    companion object {
        private const val TAG = "SyncFlushWorker"
        private const val MAX_MESSAGES_PER_FLUSH = 200
    }

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val ctx = applicationContext
        val prefs = SyncPreferences.getInstance(ctx)
        if (!prefs.enabled) {
            Log.i(TAG, "Sync disabled, skipping flush")
            return@withContext Result.success()
        }

        val shelters = AppStateStore.shelters.value
        val allPublic = AppStateStore.publicMessages.value
        val messages = allPublic.takeLast(MAX_MESSAGES_PER_FLUSH)
        val incidents = SyncBundleBuilder.extractIncidents(messages)

        // 1) text SOS / messages / shelters (the existing bundle)
        val bundle = SyncBundleBuilder.build(shelters, incidents)
        var textOk = true
        if (bundle.incidentCount > 0 || bundle.shelterCount > 0) {
            textOk = CivilizationSyncClient(ctx).postBundle(bundle.json)
            if (textOk) {
                prefs.lastFlushBytes = bundle.bytes
                prefs.lastSyncError = null
            }
        }

        // 2) photos and voice notes (sent here or received from nearby phones)
        val media = try {
            FieldMediaUploader(ctx).uploadPending(allPublic)
        } catch (e: Exception) {
            Log.w(TAG, "Media upload crashed: ${e.message}")
            FieldMediaUploader.Outcome.RETRY_LATER
        }

        if (!textOk || media == FieldMediaUploader.Outcome.RETRY_LATER) {
            return@withContext Result.retry()
        }
        if (bundle.incidentCount == 0 && bundle.shelterCount == 0 && media == FieldMediaUploader.Outcome.NOTHING) {
            Log.i(TAG, "Nothing to sync")
            prefs.lastSyncedAt = System.currentTimeMillis()
            prefs.lastSyncError = null
        }
        Result.success()
    }
}