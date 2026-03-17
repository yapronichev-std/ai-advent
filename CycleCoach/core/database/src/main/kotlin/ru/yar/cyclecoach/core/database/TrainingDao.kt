package ru.yar.cyclecoach.core.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface TrainingDao {

    @Query("SELECT * FROM trainings")
    fun observeAll(): Flow<List<TrainingEntity>>

    @Query("SELECT * FROM trainings WHERE id = :id")
    suspend fun getById(id: Long): TrainingEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(trainings: List<TrainingEntity>)

    @Query("DELETE FROM trainings WHERE id = :id")
    suspend fun deleteById(id: Long)
}
