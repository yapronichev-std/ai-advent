package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.launch

data class ChatMessage(
    val role: String,
    val text: String,
    val label: String? = null,
    val isError: Boolean = false
)

data class CollectedInfo(
    val level: String? = null,
    val experience: String? = null,
    val volume: String? = null,
    val availability: String? = null,
    val goal: String? = null,
    val event: String? = null,
    val ftp: String? = null,
    val limitations: String? = null
)

private data class CoachResponse(
    val answer: String,
    val collected: CollectedInfo,
    @SerializedName("ready_to_plan") val readyToPlan: Boolean
)

class ChatViewModel : ViewModel() {

    private val apiService = ClaudeApiService()
    private val gson = Gson()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val _collectedInfo = MutableStateFlow(CollectedInfo())
    val collectedInfo: StateFlow<CollectedInfo> = _collectedInfo

    private val _readyToPlan = MutableStateFlow(false)
    val readyToPlan: StateFlow<Boolean> = _readyToPlan

    private val systemPrompt = """ """.trimIndent()

    fun sendMessage(text: String) {
        if (text.isBlank() || _isLoading.value) return

        _messages.update { it + ChatMessage(role = "user", text = text) }
        _isLoading.value = true

        viewModelScope.launch {
            val apiMessages = _messages.value
                .filter { !it.isError }
                .map { ApiMessage(role = it.role, content = it.text) }

            val temperatures = listOf(0.0 to "t=0", 0.6 to "t=0.6", 1.0 to "t=1.0")

            val results = temperatures.map { (temp, label) ->
                async { Triple(temp, label, apiService.sendMessage(apiMessages, null, temp)) }
            }.awaitAll()

            for ((_, label, result) in results) {
                result.fold(
                    onSuccess = { reply ->
                        val coachResponse = runCatching {
                            gson.fromJson(reply, CoachResponse::class.java)
                        }.getOrNull()

                        if (coachResponse != null) {
                            _collectedInfo.value = coachResponse.collected
                            _readyToPlan.value = coachResponse.readyToPlan
                            _messages.update { it + ChatMessage(role = "assistant", text = coachResponse.answer, label = label) }
                        } else {
                            _messages.update { it + ChatMessage(role = "assistant", text = reply, label = label) }
                        }
                    },
                    onFailure = { error ->
                        _messages.update {
                            it + ChatMessage(
                                role = "assistant",
                                text = "Ошибка: ${error.message}",
                                label = label,
                                isError = true
                            )
                        }
                    }
                )
            }

            _isLoading.value = false
        }
    }
}
