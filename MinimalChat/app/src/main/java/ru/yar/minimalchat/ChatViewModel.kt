package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class AiProvider { CLAUDE, GIGACHAT }

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

    private val claudeService = ClaudeApiService()
    private val gigaChatService = GigaChatApiService()
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

    private val systemPrompt = """
        You are an experienced cycling coach. Your goal is to gather information from the athlete to create a personalized training plan.

        Conduct a structured interview, asking one or two questions at a time. Collect the following information:
        - Current fitness level (beginner / intermediate / advanced)
        - Cycling experience (years, disciplines: road, MTB, track, gravel)
        - Current weekly volume (km or hours per week)
        - Available training days per week and session duration
        - Goal (weight loss, endurance, speed, race preparation, gran fondo, etc.)
        - Target event or deadline (if any)
        - Recent FTP or heart rate zones (if known)
        - Any injuries or physical limitations

        Once you have enough information, summarize what was collected and offer to generate the training plan.
    """.trimIndent()

    fun sendMessage(text: String) {
        if (text.isBlank() || _isLoading.value) return

        _messages.update { it + ChatMessage(role = "user", text = text) }
        _isLoading.value = true

        viewModelScope.launch {
            val apiMessages = _messages.value
                .filter { !it.isError }
                .map { ApiMessage(role = it.role, content = it.text) }

            val apiCall = when (_selectedProvider.value) {
                AiProvider.CLAUDE -> claudeService.sendMessage(apiMessages, systemPrompt, 0.7, 300)
                AiProvider.GIGACHAT -> gigaChatService.sendMessage(apiMessages, systemPrompt, 0.7, 300)
            }
            apiCall.fold(
                onSuccess = { reply ->
                    val coachResponse = runCatching {
                        gson.fromJson(reply, CoachResponse::class.java)
                    }.getOrNull()

                    if (coachResponse != null) {
                        _collectedInfo.value = coachResponse.collected
                        _readyToPlan.value = coachResponse.readyToPlan
                        _messages.update { it + ChatMessage(role = "assistant", text = coachResponse.answer) }
                    } else {
                        _messages.update { it + ChatMessage(role = "assistant", text = reply) }
                    }
                },
                onFailure = { error ->
                    _messages.update {
                        it + ChatMessage(
                            role = "assistant",
                            text = "Ошибка: ${error.message}",
                            isError = true
                        )
                    }
                }
            )

            _isLoading.value = false
        }
    }
}
