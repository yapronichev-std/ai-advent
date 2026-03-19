package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatMessage(
    val role: String,
    val text: String,
    val isError: Boolean = false
)

class ChatViewModel : ViewModel() {

    private val apiService = ClaudeApiService()

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val systemPrompt = ""

    fun sendMessage(text: String) {
        if (text.isBlank() || _isLoading.value) return

        _messages.update { it + ChatMessage(role = "user", text = text) }
        _isLoading.value = true

        viewModelScope.launch {
            val apiMessages = _messages.value
                .filter { !it.isError }
                .map { ApiMessage(role = it.role, content = it.text) }

            apiService.sendMessage(apiMessages, systemPrompt, 0.7, 1024).fold(
                onSuccess = { reply ->
                    _messages.update { it + ChatMessage(role = "assistant", text = reply) }
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
