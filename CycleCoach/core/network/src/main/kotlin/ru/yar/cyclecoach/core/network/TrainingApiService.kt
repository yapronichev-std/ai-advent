package ru.yar.cyclecoach.core.network

import retrofit2.http.GET
import retrofit2.http.Path
import ru.yar.cyclecoach.core.network.model.TrainingNetworkModel

interface TrainingApiService {

    @GET("trainings")
    suspend fun getTrainings(): List<TrainingNetworkModel>

    @GET("trainings/{id}")
    suspend fun getTrainingById(@Path("id") id: Long): TrainingNetworkModel
}
