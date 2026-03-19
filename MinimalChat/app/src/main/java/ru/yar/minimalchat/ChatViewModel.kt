package ru.yar.minimalchat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TaskResult(
    val label: String,
    val text: String = "",
    val isLoading: Boolean = false,
    val isError: Boolean = false
)

class ChatViewModel : ViewModel() {

    private val apiService = ClaudeApiService()

    private val _taskResults = MutableStateFlow<List<TaskResult>>(emptyList())
    val taskResults: StateFlow<List<TaskResult>> = _taskResults

    // Результат отправки сгенерированного промпта (вкладка "Промпт")
    private val _promptSendResult = MutableStateFlow<TaskResult?>(null)
    val promptSendResult: StateFlow<TaskResult?> = _promptSendResult

    fun sendTask(taskText: String) {
        _promptSendResult.value = null

        val variants = listOf(
            "Прямой ответ" to taskText,
            "Пошагово" to "$taskText\n\nРешай задачу пошагово.",
            "Промпт" to "Составь эффективный промпт для языковой модели для решения следующей задачи. Верни только текст промпта, без пояснений:\n\n$taskText",
            "Эксперты" to "$taskText\n\nРеши эту задачу от лица четырёх персонажей: Винни-Пух, Пятачок, Кролик и Сова. Каждый персонаж рассуждает в своём уникальном стиле и даёт своё решение."
        )

        _taskResults.value = variants.map { (label, _) ->
            TaskResult(label = label, isLoading = true)
        }

        variants.forEachIndexed { index, (label, prompt) ->
            viewModelScope.launch {
                val result = apiService.sendMessage(
                    messages = listOf(ApiMessage(role = "user", content = prompt)),
                    maxTokens = 4048
                )
                _taskResults.update { list ->
                    list.toMutableList().also {
                        it[index] = result.fold(
                            onSuccess = { text -> TaskResult(label = label, text = text) },
                            onFailure = { e -> TaskResult(label = label, text = "Ошибка: ${e.message}", isError = true) }
                        )
                    }
                }
            }
        }
    }

    fun sendGeneratedPrompt(generatedPrompt: String) {
        if (generatedPrompt.isBlank()) return
        _promptSendResult.value = TaskResult(label = "Результат", isLoading = true)

        viewModelScope.launch {
            val result = apiService.sendMessage(
                messages = listOf(ApiMessage(role = "user", content = generatedPrompt)),
                maxTokens = 1024
            )
            _promptSendResult.value = result.fold(
                onSuccess = { text -> TaskResult(label = "Результат", text = text) },
                onFailure = { e -> TaskResult(label = "Результат", text = "Ошибка: ${e.message}", isError = true) }
            )
        }
    }
}
