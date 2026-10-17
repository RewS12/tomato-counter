package ru.hack.tomato

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.util.Size
import android.view.View
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import androidx.activity.ComponentActivity
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.content.edit
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import ru.hack.tomato.databinding.ActivityMainBinding
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.roundToInt

class MainActivity : ComponentActivity() {
    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }

    private val cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var cameraProvider: ProcessCameraProvider? = null
    private var streamClient: LiveStreamClient? = null
    private var liveRunning = false
    private var liveGeneration = 0
    private val frameInFlight = AtomicBoolean(false)

    @Volatile
    private var pendingFrame: Bitmap? = null

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

    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            startLive()
        } else {
            setLiveStatus(getString(R.string.live_permission))
            binding.liveStartStopButton.text = getString(R.string.live_start)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        applyWindowInsets()
        bindServer()
        bindNavigation()
        bindActions()
        bindLive()
        // Тихо проверяем доступность сервера, не блокируя экран.
        lifecycleScope.launch { checkServer(silent = true) }
    }

    override fun onStart() {
        super.onStart()
        if (binding.bottomNav.selectedItemId == R.id.nav_live && !liveRunning &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        ) {
            startLive()
        }
    }

    override fun onStop() {
        stopLive()
        super.onStop()
    }

    override fun onDestroy() {
        stopLive()
        cameraExecutor.shutdown()
        super.onDestroy()
    }

    private fun applyWindowInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            insets
        }
    }

    private fun bindServer() {
        val saved = prefs.getString(KEY_URL, null)?.trimEnd('/')
        val initial = if (saved.isNullOrEmpty() || saved == "https://agro.setly.space") {
            getString(R.string.server_hint)
        } else {
            saved
        }
        binding.serverUrl.setText(initial)
        binding.serverAddress.text = displayAddress(initial)
        binding.serverStatus.text = getString(R.string.server_status_idle)
    }

    private fun bindNavigation() {
        binding.bottomNav.setBackgroundColor(ContextCompat.getColor(this, R.color.white))
        binding.bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_analysis -> showScreen(Screen.ANALYSIS)
                R.id.nav_live -> showScreen(Screen.LIVE)
                R.id.nav_server -> showScreen(Screen.SERVER)
                R.id.nav_about -> showScreen(Screen.ABOUT)
            }
            true
        }
        binding.serverChip.setOnClickListener {
            binding.bottomNav.selectedItemId = R.id.nav_server
        }
        binding.bottomNav.selectedItemId = R.id.nav_analysis
    }

    private fun bindActions() {
        binding.captureCard.setOnClickListener {
            runCatching { takePicture.launch(captureUri) }
                .onFailure { setStatus("Нет приложения камеры — выберите фото из галереи") }
        }
        binding.galleryButton.setOnClickListener {
            pickImage.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
        }
        binding.checkButton.setOnClickListener {
            lifecycleScope.launch { checkServer() }
        }
        binding.serverUrl.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE || actionId == EditorInfo.IME_ACTION_GO) {
                lifecycleScope.launch { checkServer() }
                true
            } else {
                false
            }
        }
        binding.resetServerButton.setOnClickListener {
            binding.serverUrl.setText(getString(R.string.server_hint))
            lifecycleScope.launch { checkServer() }
        }
        binding.aboutSiteButton.setOnClickListener { openSite() }
    }

    private fun bindLive() {
        binding.liveStartStopButton.setOnClickListener {
            if (liveRunning) stopLive() else startLive()
        }
    }

    private fun showScreen(screen: Screen) {
        binding.analysisScroll.visibility = if (screen == Screen.ANALYSIS) View.VISIBLE else View.GONE
        binding.serverScroll.visibility = if (screen == Screen.SERVER) View.VISIBLE else View.GONE
        binding.aboutScroll.visibility = if (screen == Screen.ABOUT) View.VISIBLE else View.GONE
        binding.liveContainer.visibility = if (screen == Screen.LIVE) View.VISIBLE else View.GONE
        if (screen == Screen.LIVE) {
            // selectedItemId обновляется после callback — стартуем на следующем кадре цикла.
            binding.root.post {
                if (binding.bottomNav.selectedItemId == R.id.nav_live && !liveRunning) startLive()
            }
        } else {
            stopLive()
        }
        if (screen != Screen.SERVER) hideKeyboard()
    }

    private fun startLive() {
        if (liveRunning) return
        if (binding.bottomNav.selectedItemId != R.id.nav_live) return
        val url = serverUrl() ?: return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            setLiveStatus(getString(R.string.live_permission))
            binding.liveStartStopButton.text = getString(R.string.live_start)
            cameraPermission.launch(Manifest.permission.CAMERA)
            return
        }

        binding.streamView.clear()
        binding.liveHint.visibility = View.VISIBLE
        binding.liveTotal.text = "0"
        binding.liveRipe.text = "0"
        binding.liveUnripe.text = "0"
        binding.liveStats.text = getString(R.string.live_idle)
        binding.liveStatus.text = getString(R.string.live_connecting)
        binding.liveStartStopButton.text = getString(R.string.live_stop)
        liveRunning = true
        frameInFlight.set(false)
        val generation = ++liveGeneration

        streamClient = LiveStreamClient(LiveStreamClient.streamUrl(url), object : LiveStreamClient.Listener {
            override fun onOpen() {
                runOnUiThread {
                    if (generation == liveGeneration && liveRunning) {
                        binding.liveStatus.text = getString(R.string.live_connected)
                    }
                }
            }

            override fun onResult(result: DetectResult) {
                runOnUiThread {
                    if (generation != liveGeneration || !liveRunning) return@runOnUiThread
                    val frame = pendingFrame
                    pendingFrame = null
                    if (frame != null && !frame.isRecycled) {
                        binding.streamView.setFrame(frame, result.objects)
                        binding.liveHint.visibility = View.GONE
                        binding.liveTotal.text = result.total.toString()
                        binding.liveRipe.text = result.ripe.toString()
                        binding.liveUnripe.text = result.unripe.toString()
                        binding.liveStats.text =
                            "${result.model} · ${result.device} · ${result.ms.roundToInt()} мс"
                    }
                    frameInFlight.set(false)
                }
            }

            override fun onError(message: String) {
                runOnUiThread {
                    if (generation != liveGeneration) return@runOnUiThread
                    pendingFrame?.let { if (!it.isRecycled) it.recycle() }
                    pendingFrame = null
                    frameInFlight.set(false)
                    if (liveRunning) {
                        stopLive()
                        setLiveStatus("Ошибка: $message")
                    }
                }
            }

            override fun onClosed() {
                runOnUiThread {
                    if (generation != liveGeneration) return@runOnUiThread
                    if (liveRunning) {
                        stopLive()
                        setLiveStatus("Соединение закрыто")
                    }
                }
            }
        }).also { it.connect() }

        startCamera()
    }

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (!liveRunning) return@addListener
            try {
                val provider = future.get()
                cameraProvider = provider
                val resolution = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            Size(640, 480),
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                        )
                    )
                    .build()
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageRotationEnabled(true)
                    .setResolutionSelector(resolution)
                    .build()
                analysis.setAnalyzer(cameraExecutor) { image -> onFrame(image) }
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, analysis)
            } catch (exc: Exception) {
                stopLive()
                setLiveStatus("Камера: ${exc.message ?: "недоступна"}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun onFrame(image: ImageProxy) {
        try {
            if (!liveRunning || streamClient?.isOpen != true || frameInFlight.get()) return
            val frame = image.toBitmap()
            val jpeg = ByteArrayOutputStream().use { out ->
                frame.compress(Bitmap.CompressFormat.JPEG, 60, out)
                out.toByteArray()
            }
            pendingFrame = frame
            frameInFlight.set(true)
            if (streamClient?.sendJpeg(jpeg) != true) {
                frameInFlight.set(false)
                pendingFrame = null
                if (!frame.isRecycled) frame.recycle()
            }
        } catch (exc: Exception) {
            frameInFlight.set(false)
            pendingFrame?.let { if (!it.isRecycled) it.recycle() }
            pendingFrame = null
            runOnUiThread { setLiveStatus("Кадр: ${exc.message ?: "ошибка"}") }
        } finally {
            image.close()
        }
    }

    private fun stopLive() {
        if (!liveRunning) return
        liveRunning = false
        liveGeneration++
        streamClient?.close()
        streamClient = null
        cameraProvider?.unbindAll()
        cameraProvider = null
        frameInFlight.set(false)
        pendingFrame?.let { if (!it.isRecycled) it.recycle() }
        pendingFrame = null
        binding.liveStartStopButton.text = getString(R.string.live_start)
        binding.liveStatus.text = getString(R.string.live_stopped)
        binding.liveStats.text = getString(R.string.live_idle)
    }

    private fun setLiveStatus(text: String) {
        binding.liveStatus.text = text
    }

    /** Нормализует и запоминает адрес сервера. null — если адрес не введён. */
    private fun serverUrl(): String? = try {
        DetectApi.normalizeUrl(binding.serverUrl.text.toString()).also {
            binding.serverUrl.setText(it)
            binding.serverAddress.text = displayAddress(it)
            prefs.edit { putString(KEY_URL, it) }
        }
    } catch (e: ApiException) {
        binding.serverStatus.text = e.message
        setStatus(e.message)
        null
    }

    private suspend fun checkServer(silent: Boolean = false) {
        val url = serverUrl() ?: return
        if (!silent) setBusy(true, "Проверяю соединение…")
        binding.serverStatus.text = "Проверяю соединение…"
        val message = try {
            DetectApi.health(url).also {
                binding.serverDot.setTextColor(ContextCompat.getColor(this, R.color.green))
            }
        } catch (e: ApiException) {
            binding.serverDot.setTextColor(ContextCompat.getColor(this, R.color.orange))
            e.message
        }
        binding.serverStatus.text = message
        if (!silent) setBusy(false, message)
    }

    private fun process(uri: Uri) {
        val url = serverUrl() ?: return
        lifecycleScope.launch {
            setBusy(true, "Отправляю фото на сервер…")
            try {
                val photo: Bitmap = withContext(Dispatchers.Default) {
                    ImageUtils.loadUpright(this@MainActivity, uri)
                }
                binding.photo.setImageBitmap(photo)
                val jpeg = withContext(Dispatchers.Default) { ImageUtils.toJpeg(photo) }
                val result = DetectApi.detect(url, jpeg)
                val annotated = withContext(Dispatchers.Default) {
                    ImageUtils.drawDetections(photo, result)
                }
                binding.photo.setImageBitmap(annotated)
                binding.totalCount.text = result.total.toString()
                binding.ripeCount.text = result.ripe.toString()
                binding.unripeCount.text = result.unripe.toString()
                binding.resultMeta.text = "${result.model} (${result.mode}) · ${result.ms.toInt()} мс"
                binding.emptyState.visibility = View.GONE
                binding.resultContainer.visibility = View.VISIBLE
                binding.resultContainer.alpha = 0f
                binding.resultContainer.animate().alpha(1f).setDuration(220).start()
                binding.serverDot.setTextColor(ContextCompat.getColor(this@MainActivity, R.color.green))
                binding.serverStatus.text = "Сервер OK · ${result.model}"
                val summary = when {
                    result.total == 0 && result.mode == "stub" ->
                        "Плоды не найдены. Демо-модель может не находить томаты — нужны обученные веса."
                    result.total == 0 -> "Плоды не найдены — попробуйте другое фото"
                    else -> "Готово: найдено ${result.total} · зрелых ${result.ripe} · незрелых ${result.unripe}"
                }
                setBusy(false, summary)
            } catch (e: ApiException) {
                binding.serverDot.setTextColor(ContextCompat.getColor(this@MainActivity, R.color.orange))
                setBusy(false, e.message)
            } catch (e: OutOfMemoryError) {
                setBusy(false, "Фото слишком большое")
            }
        }
    }

    private fun setBusy(busy: Boolean, status: String?) {
        binding.progress.visibility = if (busy) View.VISIBLE else View.GONE
        binding.captureCard.isEnabled = !busy
        binding.galleryButton.isEnabled = !busy
        binding.checkButton.isEnabled = !busy
        binding.resetServerButton.isEnabled = !busy
        binding.serverUrl.isEnabled = !busy
        binding.serverChip.isEnabled = !busy
        binding.captureCard.alpha = if (busy) 0.65f else 1f
        binding.galleryButton.alpha = if (busy) 0.65f else 1f
        setStatus(status)
    }

    private fun setStatus(text: String?) {
        binding.status.text = text.orEmpty()
    }

    private fun displayAddress(url: String): String {
        val uri = Uri.parse(url)
        val host = uri.host ?: return url
        val port = if (uri.port != -1) ":${uri.port}" else ""
        val path = uri.path.orEmpty().trimEnd('/')
        return "$host$port$path"
    }

    private fun openSite() {
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://agro.setly.space")))
        }.onFailure { setStatus("Не удалось открыть браузер") }
    }

    private fun hideKeyboard() {
        (getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)
            ?.hideSoftInputFromWindow(binding.root.windowToken, 0)
    }

    private enum class Screen { ANALYSIS, LIVE, SERVER, ABOUT }

    private companion object {
        const val KEY_URL = "server_url"
    }
}
