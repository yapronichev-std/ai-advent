package ru.yar.minimalchat

import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

private data class OpenRouterRequest(
    val model: String,
    val messages: List<ApiMessage>,
    val temperature: Double? = null,
    @SerializedName("max_tokens") val maxTokens: Int = 2048
)

private data class OpenRouterUsage(
    @SerializedName("completion_tokens") val completionTokens: Int?
)

private data class OpenRouterResponse(
    val choices: List<OpenRouterChoice>,
    val usage: OpenRouterUsage?
)

private data class OpenRouterChoice(
    val message: OpenRouterMessage
)

private data class OpenRouterMessage(
    val role: String,
    val content: String
)

class OpenRouterApiService {

    private val gson = Gson()
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    suspend fun sendMessage(
        messages: List<ApiMessage>,
        system: String? = null,
        temperature: Double? = null,
        maxTokens: Int = 2048
    ): Result<ApiResult> = withContext(Dispatchers.IO) {
        try {
            val allMessages = if (system != null) {
                listOf(ApiMessage(role = "system", content = system)) + messages
            } else {
                messages
            }

            val body = gson.toJson(
                OpenRouterRequest(
                    model = Constants.OPENROUTER_MODEL,
                    messages = allMessages,
                    temperature = temperature,
                    maxTokens = maxTokens
                )
            ).toRequestBody(jsonMedia)

            val request = Request.Builder()
                .url("https://openrouter.ai/api/v1/chat/completions")
                .addHeader("Authorization", "Bearer ${Constants.OPENROUTER_API_KEY}")
                .addHeader("X-Title", "MinimalChat")
                .post(body)
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: return@withContext Result.failure(
                Exception("Пустой ответ от OpenRouter")
            )

            if (!response.isSuccessful) {
                return@withContext Result.failure(
                    Exception("Ошибка OpenRouter API (${response.code}): $responseBody")
                )
            }

            val parsed = gson.fromJson(responseBody, OpenRouterResponse::class.java)
            val text = parsed.choices
                .firstOrNull()
                ?.message
                ?.content
                ?: return@withContext Result.failure(Exception("Нет текста в ответе OpenRouter"))

            Result.success(ApiResult(text = text, tokenCount = parsed.usage?.completionTokens))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
