package ru.yar.cyclecoach.core.network.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class TrainingNetworkModel(
    @SerialName("id") val id: Long,
    @SerialName("title") val title: String,
    @SerialName("description") val description: String,
    @SerialName("duration_minutes") val durationMinutes: Int,
    @SerialName("distance_km") val distanceKm: Double,
)
