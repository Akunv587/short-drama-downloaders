package com.shortmaxdl.data.db

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface DownloadDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(record: DownloadRecord): Long

    @Query("SELECT * FROM download_records ORDER BY completedAt DESC")
    fun getAllFlow(): Flow<List<DownloadRecord>>

    @Query("SELECT * FROM download_records WHERE movieId = :movieId ORDER BY episodeNumber ASC")
    suspend fun getByMovieId(movieId: String): List<DownloadRecord>

    @Query("SELECT * FROM download_records WHERE movieId = :movieId ORDER BY episodeNumber ASC")
    fun getByMovieIdFlow(movieId: String): Flow<List<DownloadRecord>>

    @Query("DELETE FROM download_records WHERE id = :id")
    suspend fun deleteById(id: Long)

    @Query("DELETE FROM download_records")
    suspend fun deleteAll()

    @Query("SELECT DISTINCT movieId, movieTitle FROM download_records ORDER BY completedAt DESC LIMIT 10")
    fun getRecentMoviesFlow(): Flow<List<MovieSummary>>
}

data class MovieSummary(
    val movieId: String,
    val movieTitle: String,
)
