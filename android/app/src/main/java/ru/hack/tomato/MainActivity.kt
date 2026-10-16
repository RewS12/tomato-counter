package ru.hack.tomato

import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.view.View
import androidx.activity.ComponentActivity
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.core.content.edit
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import ru.hack.tomato.databinding.ActivityMainBinding
import java.io.File

class MainActivity : ComponentActivity() {
    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }

    /** Файл, куда системная камера кладёт снимок. */
    private val captureUri: Uri by lazy {
        val file = File(cacheDir, "photos/capture.jpg").apply { parentFile?.mkdirs() }
        FileProvider.getUriForFile(this, "$packageName.files", file)
    }

    private val takePicture = registerForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        if (ok) process(captureUri) else setStatus("Съёмка отменена")
    }

    private val pickImage = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) process(uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.serverUrl.setText(prefs.getString(KEY_URL, ""))
        binding.checkButton.setOnClickListener { checkServer() }
        binding.cameraButton.setOnClickListener {
            runCatching { takePicture.launch(captureUri) }
                .onFailure { setStatus("Нет приложения камеры — выберите фото из галереи") }
        }
        binding.galleryButton.setOnClickListener {
            pickImage.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
        }
    }

    /** Нормализует и запоминает адрес сервера. null — если адрес не введён. */
    private fun serverUrl(): String? = try {
        DetectApi.normalizeUrl(binding.serverUrl.text.toString()).also {
            binding.serverUrl.setText(it)
            prefs.edit { putString(KEY_URL, it) }
        }
    } catch (e: ApiException) {
        setStatus(e.message)
        null
    }

    private fun checkServer() {
        val url = serverUrl() ?: return
        lifecycleScope.launch {
            setBusy(true, "Проверяю $url …")
            val msg = try {
                DetectApi.health(url)
            } catch (e: ApiException) {
                e.message
            }
            setBusy(false, msg)
        }
    }

    private fun process(uri: Uri) {
        val url = serverUrl() ?: return
        lifecycleScope.launch {
            setBusy(true, "Отправляю фото…")
            binding.summary.text = ""
            try {
                val photo: Bitmap = withContext(Dispatchers.Default) { ImageUtils.loadUpright(this@MainActivity, uri) }
                binding.photo.setImageBitmap(photo)
                val jpeg = withContext(Dispatchers.Default) { ImageUtils.toJpeg(photo) }
                val result = DetectApi.detect(url, jpeg)
                val annotated = withContext(Dispatchers.Default) { ImageUtils.drawDetections(photo, result) }
                binding.photo.setImageBitmap(annotated)
                binding.summary.text = summaryText(result)
                setBusy(false, "${result.model} (${result.mode}) · ${result.ms.toInt()} мс на сервере")
            } catch (e: ApiException) {
                setBusy(false, e.message)
            } catch (e: OutOfMemoryError) {
                setBusy(false, "Фото слишком большое")
            }
        }
    }

    private fun summaryText(r: DetectResult) = "Всего ${r.total}  ·  🔴 зрелых ${r.ripe}  ·  🟢 незрелых ${r.unripe}"

    private fun setBusy(busy: Boolean, status: String?) {
        binding.progress.visibility = if (busy) View.VISIBLE else View.GONE
        binding.cameraButton.isEnabled = !busy
        binding.galleryButton.isEnabled = !busy
        binding.checkButton.isEnabled = !busy
        setStatus(status)
    }

    private fun setStatus(text: String?) {
        binding.status.text = text.orEmpty()
    }

    private companion object {
        const val KEY_URL = "server_url"
    }
}
