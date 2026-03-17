package ru.yar.cyclecoach.core.data

import kotlinx.coroutines.flow.Flow
import ru.yar.cyclecoach.core.model.Training

interface TrainingRepository {
    fun observeTrainings(): Flow<List<Training>>
    suspend fun syncTrainings()
}
