package com.shortmaxdl.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Persisted download record for history tracking.
 */
@Entity(tableName = "download_records")
data class DownloadRecord(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,
    val movieId: String,
    val movieTitle: String,
    val episodeNumber: Int,
    val episodeTitle: String,
    val outputPath: String,
    val fileSizeBytes: Long,
    val completedAt: Long = System.currentTimeMillis(),
    val status: String = "COMPLETED", // COMPLETED, FAILED
)
