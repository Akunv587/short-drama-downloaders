package com.shortmaxdl.di

import android.content.Context
import androidx.room.Room
import com.shortmaxdl.data.db.AppDatabase
import com.shortmaxdl.data.db.DownloadDao
import com.shortmaxdl.data.http.PersistentCookieJar
import com.shortmaxdl.data.prefs.SettingsStore
import com.shortmaxdl.domain.auth.AuthManager
import com.shortmaxdl.domain.download.DownloadEngine
import com.shortmaxdl.domain.download.DownloadQueue
import com.shortmaxdl.domain.parser.ShortMaxParser
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    // ── Network ────────────────────────────────────────

    @Provides
    @Singleton
    fun providePersistentCookieJar(): PersistentCookieJar = PersistentCookieJar()

    @Provides
    @Singleton
    fun provideOkHttpClient(cookieJar: PersistentCookieJar): OkHttpClient {
        return com.shortmaxdl.data.http.HttpClientFactory.create(cookieJar)
    }

    // ── Parser ─────────────────────────────────────────

    @Provides
    @Singleton
    fun provideShortMaxParser(httpClient: OkHttpClient): ShortMaxParser {
        return ShortMaxParser(httpClient)
    }

    // ── Download ───────────────────────────────────────

    @Provides
    @Singleton
    fun provideDownloadEngine(@ApplicationContext context: Context): DownloadEngine {
        return DownloadEngine(context)
    }

    @Provides
    @Singleton
    fun provideDownloadQueue(
        @ApplicationContext context: Context,
        engine: DownloadEngine,
        parser: ShortMaxParser,
    ): DownloadQueue {
        return DownloadQueue(context, engine, parser)
    }

    // ── Auth ───────────────────────────────────────────

    @Provides
    @Singleton
    fun provideAuthManager(cookieJar: PersistentCookieJar): AuthManager {
        return AuthManager(cookieJar)
    }

    // ── Database ───────────────────────────────────────

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): AppDatabase {
        return Room.databaseBuilder(
            context,
            AppDatabase::class.java,
            "shortmax_dl.db"
        ).build()
    }

    @Provides
    fun provideDownloadDao(db: AppDatabase): DownloadDao = db.downloadDao()

    // ── Settings ───────────────────────────────────────

    @Provides
    @Singleton
    fun provideSettingsStore(@ApplicationContext context: Context): SettingsStore {
        return SettingsStore(context)
    }
}
