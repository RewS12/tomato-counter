"""Настройки сервера. Всё переопределяется переменными окружения."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Путь к весам: наша модель, если уже обучена, иначе COCO-заглушка.
_TRAINED = ROOT / "models" / "tomato_v1.pt"
MODEL_PATH = os.getenv("MODEL_PATH", str(_TRAINED if _TRAINED.exists() else ROOT / "models" / "yolo11n.pt"))
CONF = float(os.getenv("CONF", "0.25"))
IOU = float(os.getenv("IOU", "0.5"))
IMGSZ = int(os.getenv("IMGSZ", "640"))
DEVICE = os.getenv("DEVICE", "")  # "" = авто (GPU, если есть), "cpu", "0"

# Режим заглушки: какие COCO-классы считаем «плодами», пока нет своей модели.
STUB_CLASSES = {"apple", "orange"}

# Порог доли «красных» пикселей, начиная с которого плод считается зрелым (HSV-правило).
RIPE_RED_RATIO = float(os.getenv("RIPE_RED_RATIO", "0.5"))
