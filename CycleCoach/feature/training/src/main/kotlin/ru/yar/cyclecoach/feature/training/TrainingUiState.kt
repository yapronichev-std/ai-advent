package ru.yar.cyclecoach.feature.training

import ru.yar.cyclecoach.core.model.Training

sealed class TrainingUiState {
    data object Loading : TrainingUiState()
    data class Success(val trainings: List<Training>) : TrainingUiState()
    data class Error(val message: String) : TrainingUiState()
}
