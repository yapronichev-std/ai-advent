package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatMessage(
    val role: String,
    val text: String,
    val label: String? = null,
    val isError: Boolean = false
)

class ChatViewModel : ViewModel() {

    private val apiService = ClaudeApiService()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    fun sendMessage(text: String) {
        if (text.isBlank() || _isLoading.value) return

        _messages.update { it + ChatMessage(role = "user", text = text) }
        _isLoading.value = true

        viewModelScope.launch {
            val apiMessages = _messages.value
                .filter { !it.isError }
                .map { ApiMessage(role = it.role, content = it.text) }

            val systemPrompt = """
                Respond only with valid JSON matching this schema:
                {"answer": "string", "time": "string"}
                - "answer": your response to the user's question
                - "time": estimated time to implement or achieve what the user asked, e.g. "2 hours", "5 minutes"
                Do not include any text outside the JSON object.
            """.trimIndent()

            val r1 = async { apiService.sendMessage(apiMessages, temperature = 0.7, topK = 300) }
            val r2 = async { apiService.sendMessage(apiMessages, temperature = 0.7, topK = 300, maxTokens = 256) }
            val r3 = async { apiService.sendMessage(apiMessages, systemPrompt, 0.7, 300, maxTokens = 256) }

            listOf(
                "Без ограничений" to r1.await(),
                "Лимит токенов" to r2.await(),
                "JSON + лимит токенов" to r3.await()
            ).forEach { (label, result) ->
                result.fold(
                    onSuccess = { reply ->
                        _messages.update { it + ChatMessage(role = "assistant", text = reply, label = label) }
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
