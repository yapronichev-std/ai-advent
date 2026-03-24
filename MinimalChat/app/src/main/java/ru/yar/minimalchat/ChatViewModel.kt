package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class AiProvider { CLAUDE, GIGACHAT, OPENROUTER }

data class ApiResult(
    val text: String,
    val tokenCount: Int? = null
)

data class ChatMessage(
    val role: String,
    val text: String,
    val label: String? = null,
    val isError: Boolean = false,
    val durationMs: Long? = null,
    val tokenCount: Int? = null
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

    private val claudeService = ClaudeApiService()
    private val gigaChatService = GigaChatApiService()
    private val openRouterService = OpenRouterApiService()
    private val gson = Gson()

    private val _selectedProvider = MutableStateFlow(AiProvider.CLAUDE)
    val selectedProvider: StateFlow<AiProvider> = _selectedProvider

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val _collectedInfo = MutableStateFlow(CollectedInfo())
    val collectedInfo: StateFlow<CollectedInfo> = _collectedInfo

    private val _readyToPlan = MutableStateFlow(false)
    val readyToPlan: StateFlow<Boolean> = _readyToPlan

    fun setProvider(provider: AiProvider) {
        if (_selectedProvider.value == provider) return
        _selectedProvider.value = provider
        _messages.value = emptyList()
        _collectedInfo.value = CollectedInfo()
        _readyToPlan.value = false
    }

    private val systemPrompt = """ """.trimIndent()

    fun sendMessage(text: String) {
        if (text.isBlank() || _isLoading.value) return

        _messages.update { it + ChatMessage(role = "user", text = text) }
        _isLoading.value = true

        viewModelScope.launch {
            val apiMessages = _messages.value
                .filter { !it.isError }
                .map { ApiMessage(role = it.role, content = it.text) }

            val startMs = System.currentTimeMillis()
            val apiCall = when (_selectedProvider.value) {
                AiProvider.CLAUDE -> claudeService.sendMessage(apiMessages)
                AiProvider.GIGACHAT -> gigaChatService.sendMessage(apiMessages)
                AiProvider.OPENROUTER -> openRouterService.sendMessage(apiMessages)
            }
            val durationMs = System.currentTimeMillis() - startMs

            apiCall.fold(
                onSuccess = { result ->
                    val coachResponse = runCatching {
                        gson.fromJson(result.text, CoachResponse::class.java)
                    }.getOrNull()

                    if (coachResponse != null) {
                        _collectedInfo.value = coachResponse.collected
                        _readyToPlan.value = coachResponse.readyToPlan
                        _messages.update {
                            it + ChatMessage(
                                role = "assistant",
                                text = coachResponse.answer,
                                durationMs = durationMs,
                                tokenCount = result.tokenCount
                            )
                        }
                    } else {
                        _messages.update {
                            it + ChatMessage(
                                role = "assistant",
                                text = result.text,
                                durationMs = durationMs,
                                tokenCount = result.tokenCount
                            )
                        }
                    }
                },
                onFailure = { error ->
                    _messages.update {
                        it + ChatMessage(
                            role = "assistant",
                            text = "Ошибка: ${error.message}",
                            isError = true,
                            durationMs = durationMs
                        )
                    }
                }
            )

            _isLoading.value = false
        }
    }
}
