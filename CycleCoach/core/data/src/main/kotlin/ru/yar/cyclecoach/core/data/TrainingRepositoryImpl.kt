package ru.yar.cyclecoach.core.data

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import ru.yar.cyclecoach.core.database.CycleCoachDatabase
import ru.yar.cyclecoach.core.database.TrainingEntity
import ru.yar.cyclecoach.core.model.Training
import ru.yar.cyclecoach.core.network.TrainingApiService
import javax.inject.Inject

internal class TrainingRepositoryImpl @Inject constructor(
    private val database: CycleCoachDatabase,
    private val apiService: TrainingApiService,
) : TrainingRepository {

    override fun observeTrainings(): Flow<List<Training>> =
        database.trainingDao().observeAll().map { entities -> entities.map { it.toDomain() } }

    override suspend fun syncTrainings() {
        val networkModels = apiService.getTrainings()
        val entities = networkModels.map { model ->
            TrainingEntity(
                id = model.id,
                title = model.title,
                description = model.description,
                durationMinutes = model.durationMinutes,
                distanceKm = model.distanceKm,
            )
        }
        database.trainingDao().upsertAll(entities)
    }

    private fun TrainingEntity.toDomain() = Training(
        id = id,
        title = title,
        description = description,
        durationMinutes = durationMinutes,
        distanceKm = distanceKm,
    )
}
