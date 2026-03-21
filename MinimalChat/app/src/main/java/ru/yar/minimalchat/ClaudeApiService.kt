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

data class ApiMessage(
    val role: String,
    val content: String
)

private data class ClaudeRequest(
    val model: String,
    @SerializedName("max_tokens") val maxTokens: Int,
    val messages: List<ApiMessage>,
    val system: String? = null,
    val temperature: Double? = null,
    @SerializedName("top_p") val topP: Double? = null,
    @SerializedName("top_k") val topK: Int? = null
)

private data class ClaudeResponse(
    val content: List<ContentBlock>
)

private data class ContentBlock(
    val type: String,
    val text: String?
)

class ClaudeApiService {

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    suspend fun sendMessage(
        messages: List<ApiMessage>,
        system: String? = null,
        temperature: Double? = null,
        topK: Int? = null,
        topP: Double? = null,
        maxTokens: Int = 4096
    ): Result<String> = withContext(Dispatchers.IO) {
        try {
            val body = gson.toJson(
                ClaudeRequest(
                    model = "claude-sonnet-4-6",
                    maxTokens = maxTokens,
                    messages = messages,
                    system = system,
                    temperature = temperature,
                    topP = topP,
                    topK = topK
                )
            ).toRequestBody(jsonMedia)

            val request = Request.Builder()
                .url("https://api.anthropic.com/v1/messages")
                .addHeader("x-api-key", Constants.CLAUDE_API_KEY)
                .addHeader("anthropic-version", "2023-06-01")
                .post(body)
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: return@withContext Result.failure(
                Exception("Пустой ответ от сервера")
            )

            if (!response.isSuccessful) {
                return@withContext Result.failure(Exception("Ошибка API (${response.code}): $responseBody"))
            }

            val text = gson.fromJson(responseBody, ClaudeResponse::class.java)
                .content
                .firstOrNull { it.type == "text" }
                ?.text
                ?: return@withContext Result.failure(Exception("Нет текста в ответе"))

            Result.success(text)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
