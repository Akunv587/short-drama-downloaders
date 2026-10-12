package com.shortmaxdl.domain.model

import org.json.JSONObject

/**
 * Episode information extracted from ShortMax page.
 */
data class EpisodeInfo(
    val movieId: String,
    val movieTitle: String = "",
    val episodeNumber: Int = 0,
    val episodeTitle: String = "",
    val durationSeconds: Int = 0,
    /** JSON string with quality→m3u8 mappings or direct m3u8 URL */
    val encryptedVideoUrl: String = "",
    /** True if this episode requires VIP login */
    val isVip: Boolean = false,
) {
    val displayLabel: String
        get() = if (episodeTitle.isNotBlank()) episodeTitle
        else "EP${episodeNumber.toString().padStart(2, '0')}"

    /**
     * Extract the best quality m3u8 URL from encryptedVideoUrl.
     * Format: {"video_1080":"...m3u8","video_720":"...","video_480":"..."}
     * or a direct m3u8 URL string.
     */
    fun resolveM3u8(quality: VideoQuality = VideoQuality.Q1080P): String? {
        val url = encryptedVideoUrl.trim()
        if (url.isEmpty() || url == "\"\"" || url == "null") return null

        // Direct m3u8 URL
        if (url.startsWith("http") && ".m3u8" in url) return url

        // JSON with quality options
        if (url.startsWith("{")) {
            return try {
                val obj = JSONObject(url)
                val qualityKeys = when (quality) {
                    VideoQuality.Q1080P -> listOf("video_1080", "video_720", "video_480")
                    VideoQuality.Q720P -> listOf("video_720", "video_1080", "video_480")
                    VideoQuality.Q480P -> listOf("video_480", "video_720", "video_1080")
                }
                for (key in qualityKeys) {
                    val val_ = obj.optString(key, "")
                    if (val_.isNotBlank()) return val_
                }
                null
            } catch (_: Exception) {
                null
            }
        }

        return null
    }
}

enum class VideoQuality(val label: String) {
    Q1080P("1080p"),
    Q720P("720p"),
    Q480P("480p")
}

/**
 * Playback credentials for downloading a video.
 */
data class PlaybackInfo(
    val manifestUrl: String,
    val headers: Map<String, String> = emptyMap(),
)

/**
 * Download task state machine.
 */
enum class DownloadStatus {
    QUEUED, DOWNLOADING, COMPLETED, FAILED, PAUSED, RETRYING
}

/**
 * Runtime state of a download task.
 */
data class DownloadTaskState(
    val episodeNumber: Int,
    val episodeTitle: String,
    val movieTitle: String,
    val status: DownloadStatus = DownloadStatus.QUEUED,
    val progressPercent: Float = 0f,
    val progressTimeSeconds: Int = 0,
    val totalTimeSeconds: Int = 0,
    val speedBytesPerSec: Long = 0,
    val errorMessage: String? = null,
    val attempt: Int = 0,
    val outputPath: String? = null,
    val fileSizeBytes: Long = 0,
)
