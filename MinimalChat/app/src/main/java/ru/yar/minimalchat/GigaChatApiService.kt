package ru.yar.minimalchat

import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

private data class GigaChatRequest(
    val model: String,
    val messages: List<ApiMessage>,
    val temperature: Double? = null,
    @SerializedName("max_tokens") val maxTokens: Int = 1024
)

private data class GigaChatResponse(
    val choices: List<GigaChatChoice>
)

private data class GigaChatChoice(
    val message: GigaChatMessage
)

private data class GigaChatMessage(
    val role: String,
    val content: String
)

private data class TokenResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("expires_at") val expiresAt: Long
)

class GigaChatApiService {

    private val gson = Gson()
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val formMedia = "application/x-www-form-urlencoded".toMediaType()

    // GigaChat использует российский УЦ, которому Android не доверяет по умолчанию.
    // В продакшене замените на pinning конкретного сертификата.
    private val client = buildUnsafeClient()

    private var accessToken: String? = null
    private var tokenExpiresAt: Long = 0L

    private suspend fun getAccessToken(): String = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        if (accessToken != null && now < tokenExpiresAt - 60_000) {
            return@withContext accessToken!!
        }

        val credentials = Base64.getEncoder().encodeToString(
            "${Constants.GIGACHAT_CLIENT_ID}:${Constants.GIGACHAT_CLIENT_SECRET}".toByteArray()
        )

        val body = "scope=GIGACHAT_API_PERS".toRequestBody(formMedia)

        val request = Request.Builder()
            .url("https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
            .addHeader("Authorization", "Basic $credentials")
            .addHeader("RqUID", UUID.randomUUID().toString())
            .post(body)
            .build()

        val response = client.newCall(request).execute()
        val responseBody = response.body?.string()
            ?: throw Exception("Пустой ответ при получении токена GigaChat")

        if (!response.isSuccessful) {
            throw Exception("Ошибка авторизации GigaChat (${response.code}): $responseBody")
        }

        val tokenResponse = gson.fromJson(responseBody, TokenResponse::class.java)
        accessToken = tokenResponse.accessToken
        tokenExpiresAt = tokenResponse.expiresAt
        tokenResponse.accessToken
    }

    suspend fun sendMessage(
        messages: List<ApiMessage>,
        system: String? = null,
        temperature: Double? = null,
        maxTokens: Int = 1024
    ): Result<String> = withContext(Dispatchers.IO) {
        try {
            val token = getAccessToken()

            val allMessages = if (system != null) {
                listOf(ApiMessage(role = "system", content = system)) + messages
            } else {
                messages
            }

            val body = gson.toJson(
                GigaChatRequest(
                    model = "GigaChat",
                    messages = allMessages,
                    temperature = temperature,
                    maxTokens = maxTokens
                )
            ).toRequestBody(jsonMedia)

            val request = Request.Builder()
                .url("https://gigachat.devices.sberbank.ru/api/v1/chat/completions")
                .addHeader("Authorization", "Bearer $token")
                .post(body)
                .build()

            val response = client.newCall(request).execute()
            val responseBody = response.body?.string() ?: return@withContext Result.failure(
                Exception("Пустой ответ от GigaChat")
            )

            if (!response.isSuccessful) {
                return@withContext Result.failure(
                    Exception("Ошибка GigaChat API (${response.code}): $responseBody")
                )
            }

            val text = gson.fromJson(responseBody, GigaChatResponse::class.java)
                .choices
                .firstOrNull()
                ?.message
                ?.content
                ?: return@withContext Result.failure(Exception("Нет текста в ответе GigaChat"))

            Result.success(text)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun buildUnsafeClient(): OkHttpClient {
        val trustAllCerts = arrayOf<TrustManager>(object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
            override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
        })

        val sslContext = SSLContext.getInstance("SSL")
        sslContext.init(null, trustAllCerts, SecureRandom())

        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .sslSocketFactory(sslContext.socketFactory, trustAllCerts[0] as X509TrustManager)
            .hostnameVerifier { _, _ -> true }
            .build()
    }
}
