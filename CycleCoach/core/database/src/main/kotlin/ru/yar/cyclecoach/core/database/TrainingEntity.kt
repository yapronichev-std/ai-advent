package ru.yar.cyclecoach.core.database

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "trainings")
data class TrainingEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val title: String,
    val description: String,
    val durationMinutes: Int,
    val distanceKm: Double,
)
