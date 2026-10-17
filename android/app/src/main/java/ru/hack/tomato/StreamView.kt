package ru.hack.tomato

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.min

/** Рисует последний live-кадр и рамки детекций поверх него. */
class StreamView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : View(context, attrs, defStyleAttr) {
    private val imagePaint = Paint(Paint.FILTER_BITMAP_FLAG)
    private val boxPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        isFakeBoldText = true
    }
    private val labelBgPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val dest = RectF()
    private val colors = mapOf(
        "ripe" to Color.rgb(255, 107, 0),
        "unripe" to Color.rgb(0, 166, 81),
    )

    private var frame: Bitmap? = null
    private var objects: List<Detection> = emptyList()

    fun setFrame(bitmap: Bitmap, detections: List<Detection>) {
        val old = frame
        frame = bitmap
        objects = detections
        if (old != null && old !== bitmap && !old.isRecycled) old.recycle()
        invalidate()
    }

    fun clear() {
        val old = frame
        frame = null
        objects = emptyList()
        if (old != null && !old.isRecycled) old.recycle()
        invalidate()
    }

    override fun onDetachedFromWindow() {
        clear()
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val bitmap = frame ?: return
        if (bitmap.isRecycled) return

        val scale = min(width.toFloat() / bitmap.width, height.toFloat() / bitmap.height)
        val drawWidth = bitmap.width * scale
        val drawHeight = bitmap.height * scale
        val dx = (width - drawWidth) / 2f
        val dy = (height - drawHeight) / 2f
        dest.set(dx, dy, dx + drawWidth, dy + drawHeight)
        canvas.drawBitmap(bitmap, null, dest, imagePaint)

        val density = resources.displayMetrics.density
        val stroke = density * 2.5f
        boxPaint.strokeWidth = stroke
        labelPaint.textSize = density * 11f
        for (d in objects) {
            val color = colors[d.cls] ?: Color.WHITE
            boxPaint.color = color
            labelBgPaint.color = color

            val left = dx + d.left * scale
            val top = dy + d.top * scale
            val right = dx + d.right * scale
            val bottom = dy + d.bottom * scale
            canvas.drawRect(left, top, right, bottom, boxPaint)

            val text = "${(d.conf * 100).toInt()}%"
            val textWidth = labelPaint.measureText(text)
            val textHeight = labelPaint.textSize
            val labelTop = if (top - textHeight - stroke * 2 > 0) {
                top - textHeight - stroke * 2
            } else {
                top
            }
            canvas.drawRect(
                left,
                labelTop,
                left + textWidth + stroke * 2,
                labelTop + textHeight + stroke,
                labelBgPaint,
            )
            canvas.drawText(text, left + stroke, labelTop + textHeight, labelPaint)
        }
    }
}
