package ru.yar.cyclecoach.core.model

data class UserProfile(
    val id: Long,
    val name: String,
    val weightKg: Double,
    val heightCm: Int,
)
