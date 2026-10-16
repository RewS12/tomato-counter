"""Оценка зрелости томата по цвету внутри бокса (HSV-правило).

Используется в режиме заглушки и как объяснимый запасной вариант к обученной модели.
"""
import cv2
import numpy as np

# OpenCV: H в диапазоне 0..180
_RED_LOW = (0, 12)
_RED_HIGH = (165, 180)
_MIN_S, _MIN_V = 60, 40


def red_ratio(bgr: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """Доля красных пикселей среди насыщенных в центральной части бокса."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    # Берём центр 70% бокса — края часто захватывают листья и фон.
    dx, dy = int(w * 0.15), int(h * 0.15)
    crop = bgr[y1 + dy:y2 - dy, x1 + dx:x2 - dx]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    colored = (sat >= _MIN_S) & (val >= _MIN_V)
    n = int(colored.sum())
    if n == 0:
        return 0.0
    red = colored & (((hue >= _RED_LOW[0]) & (hue <= _RED_LOW[1])) | ((hue >= _RED_HIGH[0]) & (hue <= _RED_HIGH[1])))
    return float(red.sum()) / n


def classify(bgr: np.ndarray, box: tuple[int, int, int, int], threshold: float) -> tuple[str, float]:
    ratio = red_ratio(bgr, box)
    return ("ripe" if ratio >= threshold else "unripe"), ratio
