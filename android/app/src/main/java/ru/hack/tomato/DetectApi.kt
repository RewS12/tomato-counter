package ru.hack.tomato

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException
import java.util.UUID

/** Один найденный плод. Координаты — в пикселях отправленного фото. */
data class Detection(
    val left: Float, val top: Float, val right: Float, val bottom: Float,
    val cls: String,
    val conf: Float,
)

data class DetectResult(
    val total: Int,
    val ripe: Int,
    val unripe: Int,
    val objects: List<Detection>,
    val model: String,
    val mode: String,
    val ms: Double,
)

class ApiException(message: String) : Exception(message)

/** Клиент сервера детекции (server/app/main.py). */
object DetectApi {
    private const val DEFAULT_PORT = 8002
    private val IPV4 = Regex("""\d{1,3}(\.\d{1,3}){3}""")

    /**
     * «192.168.1.5» → «http://192.168.1.5:8002».
     * «agro.setly.space/android-api» → «https://agro.setly.space/android-api» (без лишнего порта).
     */
    fun normalizeUrl(input: String): String {
        var s = input.trim().trimEnd('/')
        if (s.isEmpty()) throw ApiException("Введите адрес сервера")
        if (!s.contains("://")) {
            val host = Uri.parse("http://$s").host.orEmpty().lowercase()
            s = if (isLocalHost(host)) "http://$s" else "https://$s"
        }
        val uri = Uri.parse(s)
        val host = uri.host
        if (host.isNullOrEmpty()) throw ApiException("Неверный адрес: $input")
        if (uri.port != -1 || !isLocalHost(host.lowercase())) return s
        return "${uri.scheme}://$host:$DEFAULT_PORT"
    }

    private fun isLocalHost(host: String): Boolean =
        host == "localhost" || !host.contains('.') || host.endsWith(".local") || IPV4.matches(host)

    suspend fun health(baseUrl: String): String = request {
        val conn = open("$baseUrl/health", timeoutMs = 5_000)
        val json = JSONObject(readBody(conn))
        "Сервер OK · ${json.optString("model")} (${json.optString("mode")})"
    }

    suspend fun detect(baseUrl: String, jpeg: ByteArray): DetectResult = request {
        val boundary = UUID.randomUUID().toString()
        val conn = open("$baseUrl/detect", timeoutMs = 30_000).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }
        val head = ("--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"photo.jpg\"\r\n" +
            "Content-Type: image/jpeg\r\n\r\n").toByteArray()
        val tail = "\r\n--$boundary--\r\n".toByteArray()
        conn.setFixedLengthStreamingMode((head.size + jpeg.size + tail.size).toLong())
        conn.outputStream.use { out ->
            out.write(head)
            out.write(jpeg)
            out.write(tail)
        }
        parse(JSONObject(readBody(conn)))
    }

    private fun parse(json: JSONObject): DetectResult {
        val arr = json.getJSONArray("objects")
        val objects = (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            val b = o.getJSONArray("bbox")
            Detection(
                b.getDouble(0).toFloat(), b.getDouble(1).toFloat(),
                b.getDouble(2).toFloat(), b.getDouble(3).toFloat(),
                o.getString("cls"), o.getDouble("conf").toFloat(),
            )
        }
        val counts = json.getJSONObject("counts")
        return DetectResult(
            total = json.getInt("total"),
            ripe = counts.optInt("ripe"),
            unripe = counts.optInt("unripe"),
            objects = objects,
            model = json.optString("model"),
            mode = json.optString("mode"),
            ms = json.optDouble("ms"),
        )
    }

    private fun open(url: String, timeoutMs: Int) = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 5_000
        readTimeout = timeoutMs
    }

    private fun readBody(conn: HttpURLConnection): String {
        try {
            val code = conn.responseCode
            if (code !in 200..299) {
                val err = conn.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                val detail = runCatching { JSONObject(err).optString("detail") }.getOrNull()
                throw ApiException("Ошибка сервера $code${if (!detail.isNullOrEmpty()) ": $detail" else ""}")
            }
            return conn.inputStream.bufferedReader().use { it.readText() }
        } finally {
            conn.disconnect()
        }
    }

    /** Сетевые ошибки → понятный текст для экрана. */
    private suspend fun <T> request(block: () -> T): T = withContext(Dispatchers.IO) {
        try {
            block()
        } catch (e: ApiException) {
            throw e
        } catch (e: ConnectException) {
            throw ApiException("Нет связи с сервером. Телефон и ноутбук в одной сети? Сервер запущен с --host 0.0.0.0?")
        } catch (e: SocketTimeoutException) {
            throw ApiException("Сервер не ответил вовремя. Проверьте IP и брандмауэр Windows.")
        } catch (e: UnknownHostException) {
            throw ApiException("Не найден адрес сервера")
        } catch (e: IOException) {
            throw ApiException("Ошибка сети: ${e.message}")
        } catch (e: org.json.JSONException) {
            throw ApiException("Неожиданный ответ сервера")
        }
    }
}
