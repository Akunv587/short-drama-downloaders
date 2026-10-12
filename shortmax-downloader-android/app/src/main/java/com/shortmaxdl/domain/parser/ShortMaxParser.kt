package com.shortmaxdl.domain.parser

import android.util.Log
import com.shortmaxdl.domain.model.EpisodeInfo
import com.shortmaxdl.domain.model.PlaybackInfo
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject

/**
 * ShortMax page parser — fetches and parses shorttv.live / shortmax.com pages.
 *
 * Ported from zaizaimao/platforms/shortmax.py.
 * Handles URL parsing, Nuxt data extraction, episode list building,
 * and m3u8 manifest resolution.
 *
 * Base reference: zaizaimao/platforms/shortmax.py
 */
class ShortMaxParser(
    private val httpClient: OkHttpClient,
) {
    companion object {
        private const val TAG = "ShortMaxParser"

        // Base URLs (same site, different domains)
        private const val WEB_BASE = "https://www.shorttv.live"
        private const val WEB_BASE_ALT = "https://www.shortmax.com"

        // Regex patterns for URL parsing
        // Matches: shorttv.live/episode/{slug}-{movieId}-{episode}
        private val URL_PATTERN = Regex(
            """(?:shorttv\.live|shortmax\.com)/episode/(.+?)-(\d+)-(\d+)(?:\?.*)?$"""
        )

        // Regex to extract __NUXT_DATA__ script content
        private val NUXT_DATA_PATTERN = Regex(
            """<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>""",
            RegexOption.DOT_MATCHES_ALL
        )

        // Fallback: direct m3u8 URL regex
        private val M3U8_PATTERN = Regex(
            """https://akamai-static\.shorttv\.live/hls-encrypted/[^"\\]+\.m3u8"""
        )

        // Common headers for anti-detection
        // Base reference: zaizaimao/core/client.py DEFAULT_HEADERS
        val DEFAULT_HEADERS = mapOf(
            "User-Agent" to (
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) " +
                    "AppleWebKit/537.36 (KHTML, like Gecko) " +
                    "Chrome/126.0.0.0 Mobile Safari/537.36"
                ),
            "Accept" to "application/json, text/plain, */*",
            "Accept-Language" to "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest" to "empty",
            "Sec-Fetch-Mode" to "cors",
            "Sec-Fetch-Site" to "same-site",
        )
    }

    /**
     * Parse a ShortMax URL into (movieId, episodeNumber).
     * Supports both shorttv.live and shortmax.com.
     *
     * Example: https://www.shorttv.live/episode/billionaire-12345-1
     *   → movieId="12345", episode=1
     */
    fun parseUrl(url: String): Pair<String, Int>? {
        val match = URL_PATTERN.find(url.trim()) ?: return null
        val movieId = match.groupValues[2]
        val episode = match.groupValues[3].toIntOrNull() ?: 1
        return movieId to episode
    }

    /**
     * Build the episode page URL.
     */
    fun buildEpisodeUrl(movieId: String, episode: Int, base: String = WEB_BASE): String {
        return "$base/episode/short-$movieId-$episode"
    }

    /**
     * Fetch HTML content from a URL using pre-configured OkHttpClient
     * (headers are applied by the client's interceptor).
     */
    private fun fetchHtml(url: String): String {
        val request = Request.Builder()
            .url(url)
            .build()

        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw RuntimeException("HTTP ${response.code}: ${response.message} for $url")
            }
            return response.body?.string() ?: throw RuntimeException("Empty response body")
        }
    }

    /**
     * Extract __NUXT_DATA__ JSON array from HTML.
     */
    private fun extractNuxtData(html: String): JSONArray? {
        val match = NUXT_DATA_PATTERN.find(html) ?: run {
            Log.w(TAG, "No __NUXT_DATA__ found in HTML")
            return null
        }
        return try {
            val raw = match.groupValues[1]
            // Try parsing as JSONArray (Nuxt 3 format)
            val trimmed = raw.trim()
            when {
                trimmed.startsWith("[") -> JSONArray(trimmed)
                trimmed.startsWith("{") -> {
                    // Nuxt 2 format: wrap object in array for uniform handling
                    JSONArray("[$trimmed]")
                }
                else -> null
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse __NUXT_DATA__: ${e.message}")
            null
        }
    }

    /**
     * Get the full episode list for a movie.
     *
     * Flow:
     * 1. Fetch page → extract __NUXT_DATA__
     * 2. Create NuxtDataResolver → findShortplayData()
     * 3. Extract episodeList → build EpisodeInfo list
     *
     * Base reference: zaizaimao/platforms/shortmax.py get_episode_list() lines 230-268
     */
    fun getEpisodeList(movieId: String): Result<List<EpisodeInfo>> {
        return try {
            val url = buildEpisodeUrl(movieId, 1)
            Log.d(TAG, "Fetching: $url")
            val html = fetchHtml(url)

            val nuxtData = extractNuxtData(html)
                ?: return Result.failure(RuntimeException("未找到页面数据，网站可能改版"))

            val resolver = NuxtDataResolver(nuxtData)
            val spData = resolver.findShortplayData()
                ?: return Result.failure(RuntimeException("未找到剧集数据，请检查 URL 是否正确"))

            val movieTitle = spData.optString("shortPlayName", "")
            val episodeListArray = spData.optJSONArray("episodeList")
                ?: return Result.failure(RuntimeException("未找到剧集列表"))

            val episodes = mutableListOf<EpisodeInfo>()
            for (i in 0 until episodeListArray.length()) {
                val epObj = episodeListArray.optJSONObject(i) ?: continue
                val epNum = epObj.optInt("episodeNum", 0)
                val encUrl = epObj.optString("encryptedVideoUrl", "").trim()

                val isVip = epNum > 6 && (encUrl.isEmpty() || encUrl == "\"\"" || encUrl == "null")

                episodes.add(
                    EpisodeInfo(
                        movieId = movieId,
                        movieTitle = movieTitle.ifBlank { "短剧" },
                        episodeNumber = epNum,
                        episodeTitle = "第 ${epNum} 集",
                        encryptedVideoUrl = encUrl,
                        isVip = isVip,
                    )
                )
            }

            Log.d(TAG, "Parsed ${episodes.size} episodes for '$movieTitle'")
            Result.success(episodes)

        } catch (e: Exception) {
            Log.e(TAG, "Failed to get episode list: ${e.message}", e)
            Result.failure(e)
        }
    }

    /**
     * Get playback info for a specific episode.
     *
     * For free episodes: extracts m3u8 from __NUXT_DATA__.
     * For VIP episodes: requires cookies from login (handled by AuthManager).
     *
     * Base reference: zaizaimao/platforms/shortmax.py get_playback() lines 272-315
     */
    fun getPlayback(
        episode: EpisodeInfo,
        quality: com.shortmaxdl.domain.model.VideoQuality = com.shortmaxdl.domain.model.VideoQuality.Q1080P
    ): Result<PlaybackInfo> {
        return try {
            // Strategy 1: resolve m3u8 from encryptedVideoUrl
            var encUrl = episode.encryptedVideoUrl

            if (encUrl.isEmpty() || encUrl == "\"\"" || encUrl == "null") {
                // Need to fetch page to get encryptedVideoUrl for this specific episode
                val url = buildEpisodeUrl(episode.movieId, episode.episodeNumber)
                val html = fetchHtml(url)
                val nuxtData = extractNuxtData(html)

                if (nuxtData != null) {
                    val resolver = NuxtDataResolver(nuxtData)
                    val spData = resolver.findShortplayData()
                    if (spData != null) {
                        val epList = spData.optJSONArray("episodeList")
                        if (epList != null) {
                            for (i in 0 until epList.length()) {
                                val epObj = epList.optJSONObject(i) ?: continue
                                if (epObj.optInt("episodeNum", 0) == episode.episodeNumber) {
                                    encUrl = epObj.optString("encryptedVideoUrl", "")
                                    break
                                }
                            }
                        }
                    }
                }

                // Strategy 2: direct regex search for m3u8 in HTML
                if (encUrl.isEmpty() || encUrl == "\"\"" || encUrl == "null") {
                    val m3u8Match = M3U8_PATTERN.find(html)
                    if (m3u8Match != null) {
                        val m3u8Url = m3u8Match.value
                        Log.d(TAG, "Found m3u8 via regex: ${m3u8Url.take(80)}")
                        return Result.success(
                            PlaybackInfo(
                                manifestUrl = m3u8Url,
                                headers = mapOf(
                                    "Origin" to WEB_BASE,
                                    "Referer" to WEB_BASE,
                                )
                            )
                        )
                    }
                }
            }

            // Resolve m3u8 from encUrl (JSON or direct URL)
            val m3u8 = episode.copy(encryptedVideoUrl = encUrl).resolveM3u8(quality)
            if (m3u8 != null) {
                Log.d(TAG, "Resolved m3u8: ${m3u8.take(80)}")
                return Result.success(
                    PlaybackInfo(
                        manifestUrl = m3u8,
                        headers = mapOf(
                            "Origin" to WEB_BASE,
                            "Referer" to WEB_BASE,
                        )
                    )
                )
            }

            // No m3u8 available — likely VIP
            Result.failure(
                RuntimeException(
                    if (episode.episodeNumber > 6)
                        "该集需要 VIP 登录。请前往「设置」→「VIP 登录」完成登录后重试。"
                    else
                        "无法获取播放地址，网站可能改版或需要代理访问。"
                )
            )

        } catch (e: Exception) {
            Log.e(TAG, "Failed to get playback: ${e.message}", e)
            Result.failure(e)
        }
    }
}
