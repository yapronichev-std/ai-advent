package ru.yar.cyclecoach.core.model

data class Training(
    val id: Long,
    val title: String,
    val description: String,
    val durationMinutes: Int,
    val distanceKm: Double,
)
