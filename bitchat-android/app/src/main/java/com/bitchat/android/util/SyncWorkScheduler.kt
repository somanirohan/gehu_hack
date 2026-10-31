package com.bitchat.android.util

import android.content.Context
import androidx.work.Constraints
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.bitchat.android.services.SyncPreferences

/**
 * Schedules the one-time WorkManager request that flushes accumulated incidents
 * and shelters to the civilization endpoint, using exponential backoff so the
 * "Send now" button still works when the network is flapping.
 */
object SyncWorkScheduler {

    fun scheduleFlush(context: Context) {
        val prefs = SyncPreferences.getInstance(context)
        if (!prefs.enabled) return
        val request = OneTimeWorkRequestBuilder<SyncFlushWorker>()
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(androidx.work.NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(
                androidx.work.BackoffPolicy.EXPONENTIAL,
                10, java.util.concurrent.TimeUnit.SECONDS
            )
            .build()
        WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
            "bitchat.civ.sync",
            androidx.work.ExistingWorkPolicy.REPLACE,
            request
        )
    }
}