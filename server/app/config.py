"""Настройки сервера. Всё переопределяется переменными окружения."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Путь к весам: самая новая наша модель из имеющихся, иначе COCO-заглушка.
# v2 обучена с негативами (яблоки, апельсины) и не путает их с томатами.
_CANDIDATES = [ROOT / "models" / n for n in ("tomato_v2.pt", "tomato_v1.pt", "yolo11n.pt")]
MODEL_PATH = os.getenv("MODEL_PATH", str(next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[-1])))
CONF = float(os.getenv("CONF", "0.25"))
IOU = float(os.getenv("IOU", "0.5"))
IMGSZ = int(os.getenv("IMGSZ", "640"))
DEVICE = os.getenv("DEVICE", "")  # "" = авто (GPU, если есть), "cpu", "0"

# Режим заглушки: какие COCO-классы считаем «плодами», пока нет своей модели.
STUB_CLASSES = {"apple", "orange"}

# Порог доли «красных» пикселей, начиная с которого плод считается зрелым (HSV-правило).
RIPE_RED_RATIO = float(os.getenv("RIPE_RED_RATIO", "0.5"))
