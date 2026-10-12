package com.shortmaxdl.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shortmaxdl.data.db.DownloadDao
import com.shortmaxdl.data.db.DownloadRecord
import com.shortmaxdl.data.db.MovieSummary
import com.shortmaxdl.data.prefs.SettingsStore
import com.shortmaxdl.domain.auth.AuthManager
import com.shortmaxdl.domain.download.DownloadQueue
import com.shortmaxdl.domain.model.DownloadStatus
import com.shortmaxdl.domain.model.EpisodeInfo
import com.shortmaxdl.domain.model.VideoQuality
import com.shortmaxdl.domain.parser.ShortMaxParser
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

data class MainUiState(
    val urlInput: String = "",
    val isParsing: Boolean = false,
    val parseError: String? = null,
    val episodes: List<EpisodeInfo> = emptyList(),
    val selectedEpisodes: Set<Int> = emptySet(),
    val movieTitle: String = "",
    val movieId: String = "",
    val isDownloading: Boolean = false,
    val isLoggedIn: Boolean = false,
    val videoQuality: VideoQuality = VideoQuality.Q1080P,
    val downloadPath: String = "",
    val proxyUrl: String = "",
    val recentMovies: List<MovieSummary> = emptyList(),
)

@HiltViewModel
class MainViewModel @Inject constructor(
    private val parser: ShortMaxParser,
    private val downloadQueue: DownloadQueue,
    private val authManager: AuthManager,
    private val settingsStore: SettingsStore,
    private val downloadDao: DownloadDao,
) : ViewModel() {

    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()

    val taskStates = downloadQueue.taskStates
    val isDownloadRunning = downloadQueue.isRunning

    init {
        viewModelScope.launch {
            val path = settingsStore.getDownloadPath()
            val quality = settingsStore.getVideoQuality()
            val proxy = settingsStore.getProxyUrl()
            _uiState.value = _uiState.value.copy(
                downloadPath = path,
                videoQuality = quality,
                proxyUrl = proxy,
                isLoggedIn = authManager.isLoggedIn,
            )
        }
        loadRecentMovies()
    }

    fun updateUrlInput(url: String) {
        _uiState.value = _uiState.value.copy(urlInput = url, parseError = null)
    }

    fun parseUrl() {
        val url = _uiState.value.urlInput.trim()
        if (url.isBlank()) {
            _uiState.value = _uiState.value.copy(parseError = "请输入 ShortMax 链接")
            return
        }

        val (movieId, _) = parser.parseUrl(url)
            ?: run {
                _uiState.value = _uiState.value.copy(parseError = "无法解析链接，请检查 URL 格式")
                return
            }

        _uiState.value = _uiState.value.copy(isParsing = true, parseError = null)

        viewModelScope.launch {
            parser.getEpisodeList(movieId).fold(
                onSuccess = { episodes ->
                    val title = episodes.firstOrNull()?.movieTitle ?: "短剧"
                    _uiState.value = _uiState.value.copy(
                        isParsing = false,
                        episodes = episodes,
                        movieTitle = title,
                        movieId = movieId,
                        selectedEpisodes = emptySet(),
                    )
                },
                onFailure = { error ->
                    _uiState.value = _uiState.value.copy(
                        isParsing = false,
                        parseError = error.message ?: "解析失败",
                    )
                }
            )
        }
    }

    fun toggleEpisodeSelection(epNum: Int) {
        val current = _uiState.value.selectedEpisodes.toMutableSet()
        if (current.contains(epNum)) current.remove(epNum) else current.add(epNum)
        _uiState.value = _uiState.value.copy(selectedEpisodes = current)
    }

    fun selectAllFreeEpisodes() {
        val freeEps = _uiState.value.episodes
            .filter { !it.isVip }
            .map { it.episodeNumber }
            .toSet()
        _uiState.value = _uiState.value.copy(selectedEpisodes = freeEps)
    }

    fun startDownload() {
        val state = _uiState.value
        val episodesToDownload = state.episodes
            .filter { it.episodeNumber in state.selectedEpisodes }

        if (episodesToDownload.isEmpty()) {
            _uiState.value = _uiState.value.copy(parseError = "请选择至少一集")
            return
        }

        downloadQueue.setOutputDir(state.downloadPath)
        downloadQueue.setQuality(state.videoQuality)
        if (state.proxyUrl.isNotBlank()) downloadQueue.setProxy(state.proxyUrl)

        downloadQueue.start(episodesToDownload)
        _uiState.value = _uiState.value.copy(
            isDownloading = true,
            parseError = null,
        )
    }

    fun pauseDownload() = downloadQueue.pause()
    fun resumeDownload() = downloadQueue.resume()
    fun stopDownload() = downloadQueue.stop()

    fun retryEpisode(ep: EpisodeInfo) = downloadQueue.retryEpisode(ep)

    fun onDownloadFinished() {
        _uiState.value = _uiState.value.copy(isDownloading = false)
        // Record completed downloads
        viewModelScope.launch {
            val states = taskStates.value
            val currentMovieTitle = _uiState.value.movieTitle
            val currentMovieId = _uiState.value.movieId

            states.forEach { (epNum, state) ->
                if (state.status == DownloadStatus.COMPLETED && state.outputPath != null) {
                    downloadDao.insert(
                        DownloadRecord(
                            movieId = currentMovieId,
                            movieTitle = currentMovieTitle,
                            episodeNumber = epNum,
                            episodeTitle = state.episodeTitle,
                            outputPath = state.outputPath,
                            fileSizeBytes = state.fileSizeBytes,
                            status = "COMPLETED",
                        )
                    )
                }
            }
            loadRecentMovies()
        }
    }

    fun updateQuality(quality: VideoQuality) {
        _uiState.value = _uiState.value.copy(videoQuality = quality)
        viewModelScope.launch { settingsStore.setVideoQuality(quality) }
    }

    fun updateDownloadPath(path: String) {
        _uiState.value = _uiState.value.copy(downloadPath = path)
        viewModelScope.launch { settingsStore.setDownloadPath(path) }
    }

    fun updateProxy(proxy: String) {
        _uiState.value = _uiState.value.copy(proxyUrl = proxy)
        downloadQueue.setProxy(proxy.ifBlank { null })
        viewModelScope.launch { settingsStore.setProxyUrl(proxy) }
    }

    fun login() {
        _uiState.value = _uiState.value.copy(isLoggedIn = authManager.isLoggedIn)
        viewModelScope.launch { settingsStore.setLoggedIn(authManager.isLoggedIn) }
    }

    fun logout() {
        authManager.logout()
        _uiState.value = _uiState.value.copy(isLoggedIn = false)
        viewModelScope.launch { settingsStore.setLoggedIn(false) }
    }

    fun clearCache() {
        viewModelScope.launch {
            downloadDao.deleteAll()
            // recentMovies will auto-refresh via flow
        }
    }

    fun goBack() {
        _uiState.value = _uiState.value.copy(
            episodes = emptyList(),
            selectedEpisodes = emptySet(),
            parseError = null,
        )
    }

    private fun loadRecentMovies() {
        viewModelScope.launch {
            downloadDao.getRecentMoviesFlow().collect { movies ->
                _uiState.value = _uiState.value.copy(recentMovies = movies)
            }
        }
    }
}
