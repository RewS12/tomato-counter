package ru.hack.tomato

import android.net.Uri
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** WebSocket-клиент realtime-детекции: отправляет JPEG-кадры и получает JSON с bbox. */
class LiveStreamClient(
    private val url: String,
    private val listener: Listener,
) {
    interface Listener {
        fun onOpen()
        fun onResult(result: DetectResult)
        fun onError(message: String)
        fun onClosed()
    }

    @Volatile
    private var open = false
    private var socket: WebSocket? = null

    val isOpen: Boolean get() = open

    fun connect() {
        val request = Request.Builder().url(url).build()
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                open = true
                listener.onOpen()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val obj = JSONObject(text)
                    val error = obj.optString("error")
                    if (error.isNotEmpty()) {
                        listener.onError(error)
                    } else {
                        listener.onResult(DetectApi.parseStream(text))
                    }
                } catch (e: Exception) {
                    listener.onError("Некорректный ответ сервера")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                open = false
                listener.onError(t.message ?: "Ошибка WebSocket")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                open = false
                listener.onClosed()
            }
        })
    }

    fun sendJpeg(jpeg: ByteArray): Boolean {
        val ws = socket ?: return false
        if (!open) return false
        return ws.send(ByteString.of(*jpeg))
    }

    fun close() {
        open = false
        socket?.close(1000, "stop")
        socket = null
    }

    companion object {
        private val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .build()

        /** http(s) base URL → ws(s) URL для /ws/stream. */
        fun streamUrl(base: String): String {
            val uri = Uri.parse(base.trimEnd('/'))
            val host = uri.host ?: return base
            val scheme = if (uri.scheme.equals("https", true)) "wss" else "ws"
            val port = if (uri.port != -1) ":${uri.port}" else ""
            val path = uri.path.orEmpty().trimEnd('/')
            return "$scheme://$host$port$path/ws/stream"
        }
    }
}
