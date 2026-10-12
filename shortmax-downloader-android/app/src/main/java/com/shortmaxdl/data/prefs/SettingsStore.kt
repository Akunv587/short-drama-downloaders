package com.shortmaxdl.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.shortmaxdl.domain.model.VideoQuality
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

/**
 * Persistent app settings using DataStore.
 */
@Singleton
class SettingsStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        private val KEY_DOWNLOAD_PATH = stringPreferencesKey("download_path")
        private val KEY_VIDEO_QUALITY = stringPreferencesKey("video_quality")
        private val KEY_PROXY_URL = stringPreferencesKey("proxy_url")
        private val KEY_IS_LOGGED_IN = booleanPreferencesKey("is_logged_in")
    }

    val downloadPath: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[KEY_DOWNLOAD_PATH] ?: context.getExternalFilesDir(null)?.absolutePath
        ?: context.filesDir.absolutePath
    }

    val videoQuality: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[KEY_VIDEO_QUALITY] ?: VideoQuality.Q1080P.name
    }

    val proxyUrl: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[KEY_PROXY_URL] ?: ""
    }

    val isLoggedIn: Flow<Boolean> = context.dataStore.data.map { prefs ->
        prefs[KEY_IS_LOGGED_IN] ?: false
    }

    suspend fun getDownloadPath(): String = downloadPath.first()
    suspend fun getVideoQuality(): VideoQuality =
        VideoQuality.valueOf(videoQuality.first())
    suspend fun getProxyUrl(): String = proxyUrl.first()

    suspend fun setDownloadPath(path: String) {
        context.dataStore.edit { it[KEY_DOWNLOAD_PATH] = path }
    }

    suspend fun setVideoQuality(quality: VideoQuality) {
        context.dataStore.edit { it[KEY_VIDEO_QUALITY] = quality.name }
    }

    suspend fun setProxyUrl(url: String) {
        context.dataStore.edit { it[KEY_PROXY_URL] = url }
    }

    suspend fun setLoggedIn(loggedIn: Boolean) {
        context.dataStore.edit { it[KEY_IS_LOGGED_IN] = loggedIn }
    }
}
