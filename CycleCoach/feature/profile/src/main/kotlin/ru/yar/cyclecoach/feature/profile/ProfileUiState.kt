package ru.yar.cyclecoach.feature.profile

import ru.yar.cyclecoach.core.model.UserProfile

sealed class ProfileUiState {
    data object Loading : ProfileUiState()
    data class Success(val profile: UserProfile) : ProfileUiState()
    data class Error(val message: String) : ProfileUiState()
}
