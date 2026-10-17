package ru.hack.tomato

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RectF
import android.net.Uri
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

object ImageUtils {
    /** Сколько пикселей по длинной стороне отправляем на сервер (модель всё равно работает на 640). */
    const val MAX_SIDE = 1280

    private val COLORS = mapOf("ripe" to Color.rgb(255, 107, 0), "unripe" to Color.rgb(0, 166, 81))

    /** Читает фото, поворачивает по EXIF и уменьшает. Сервер получает уже «прямой» кадр без EXIF. */
    fun loadUpright(context: Context, uri: Uri): Bitmap {
        val resolver = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri).use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0) throw ApiException("Не удалось открыть фото")

        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
        val decoded = resolver.openInputStream(uri).use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: throw ApiException("Не удалось открыть фото")

        val orientation = resolver.openInputStream(uri).use {
            if (it == null) ExifInterface.ORIENTATION_NORMAL
            else ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        }
        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.postRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.postRotate(270f); matrix.postScale(-1f, 1f) }
        }
        val scale = MAX_SIDE.toFloat() / max(decoded.width, decoded.height)
        if (scale < 1f) matrix.postScale(scale, scale)
        if (matrix.isIdentity) return decoded
        return Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
            .also { if (it !== decoded) decoded.recycle() }
    }

    fun toJpeg(bitmap: Bitmap, quality: Int = 90): ByteArray =
        ByteArrayOutputStream().use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
            out.toByteArray()
        }

    /** Рамки цветом категории (красный = зрелый, зелёный = незрелый) с подписью уверенности. */
    fun drawDetections(src: Bitmap, result: DetectResult): Bitmap {
        val out = src.copy(Bitmap.Config.ARGB_8888, true)
        val canvas = Canvas(out)
        val stroke = max(3f, max(out.width, out.height) / 250f)
        val box = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = stroke }
        val label = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = stroke * 5
            isFakeBoldText = true
        }
        val labelBg = Paint().apply { style = Paint.Style.FILL }

        for (d in result.objects) {
            val color = COLORS[d.cls] ?: Color.YELLOW
            box.color = color
            labelBg.color = color
            canvas.drawRect(RectF(d.left, d.top, d.right, d.bottom), box)

            val text = "${(d.conf * 100).roundToInt()}%"
            val w = label.measureText(text) + stroke * 2
            val h = label.textSize + stroke
            val top = if (d.top - h >= 0) d.top - h else d.top
            canvas.drawRect(d.left - stroke / 2, top, d.left - stroke / 2 + w, top + h, labelBg)
            canvas.drawText(text, d.left + stroke / 2, top + label.textSize, label)
        }
        return out
    }
}
