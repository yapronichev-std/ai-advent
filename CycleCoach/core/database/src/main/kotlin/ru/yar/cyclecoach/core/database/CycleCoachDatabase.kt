package ru.yar.cyclecoach.core.database

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [TrainingEntity::class],
    version = 1,
    exportSchema = false,
)
abstract class CycleCoachDatabase : RoomDatabase() {
    abstract fun trainingDao(): TrainingDao
}
