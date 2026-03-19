package ru.yar.minimalchat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import ru.yar.minimalchat.ui.theme.MinimalChatTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MinimalChatTheme {
                ChatScreen()
            }
        }
    }
}

@Composable
fun ChatScreen(chatViewModel: ChatViewModel = viewModel()) {
    val taskResults by chatViewModel.taskResults.collectAsState()
    val promptSendResult by chatViewModel.promptSendResult.collectAsState()
    var selectedTab by remember { mutableIntStateOf(0) }

    val anyLoading = taskResults.any { it.isLoading }

    Scaffold { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // Карточка с формулировкой задачи
            TaskCard(
                taskText = Constants.TASK_PROMPT,
                isLoading = anyLoading,
                onSend = {
                    selectedTab = 0
                    chatViewModel.sendTask(Constants.TASK_PROMPT)
                }
            )

            HorizontalDivider()

            if (taskResults.isEmpty()) {
                // Пустое состояние до первой отправки
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "Нажмите «Отправить задачу»,\nчтобы получить ответы",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                    )
                }
            } else {
                // Вкладки с результатами
                TabRow(selectedTabIndex = selectedTab) {
                    taskResults.forEachIndexed { index, result ->
                        Tab(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            text = { Text(result.label, maxLines = 1) }
                        )
                    }
                }

                val current = taskResults.getOrNull(selectedTab)
                val isPromptTab = selectedTab == 2 // индекс вкладки "Промпт"

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    when {
                        current == null -> Unit
                        current.isLoading -> {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(top = 32.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                CircularProgressIndicator(modifier = Modifier.size(32.dp))
                            }
                        }
                        current.isError -> {
                            ResultCard(
                                text = current.text,
                                containerColor = MaterialTheme.colorScheme.errorContainer,
                                textColor = MaterialTheme.colorScheme.onErrorContainer
                            )
                        }
                        else -> {
                            ResultCard(text = current.text)

                            // Кнопка "Отправить промпт" только на вкладке "Промпт"
                            if (isPromptTab) {
                                Button(
                                    onClick = { chatViewModel.sendGeneratedPrompt(current.text) },
                                    enabled = promptSendResult?.isLoading != true,
                                    modifier = Modifier.fillMaxWidth(),
                                    colors = ButtonDefaults.buttonColors(
                                        containerColor = MaterialTheme.colorScheme.tertiary
                                    )
                                ) {
                                    Text("Отправить промпт в LLM")
                                }

                                // Результат отправки сгенерированного промпта
                                promptSendResult?.let { result ->
                                    HorizontalDivider()
                                    Text(
                                        text = "Ответ на промпт",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f)
                                    )
                                    when {
                                        result.isLoading -> {
                                            Box(
                                                modifier = Modifier.fillMaxWidth(),
                                                contentAlignment = Alignment.Center
                                            ) {
                                                CircularProgressIndicator(modifier = Modifier.size(28.dp))
                                            }
                                        }
                                        result.isError -> ResultCard(
                                            text = result.text,
                                            containerColor = MaterialTheme.colorScheme.errorContainer,
                                            textColor = MaterialTheme.colorScheme.onErrorContainer
                                        )
                                        else -> ResultCard(text = result.text)
                                    }
                                }
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                }
            }
        }
    }
}

@Composable
fun ResultCard(
    text: String,
    containerColor: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.surfaceVariant,
    textColor: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.onSurfaceVariant
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = containerColor,
        tonalElevation = 1.dp
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(12.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = textColor
        )
    }
}

@Composable
fun TaskCard(taskText: String, isLoading: Boolean, onSend: () -> Unit) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 10.dp),
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.secondaryContainer,
        tonalElevation = 2.dp
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text(
                text = "Задача",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer.copy(alpha = 0.6f)
            )
            Text(
                text = taskText,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
            Button(
                onClick = onSend,
                enabled = !isLoading,
                modifier = Modifier.align(Alignment.End)
            ) {
                if (isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .size(16.dp)
                            .padding(end = 4.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                }
                Text("Отправить задачу")
            }
        }
    }
}
