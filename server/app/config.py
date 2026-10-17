"""Настройки сервера. Всё переопределяется переменными окружения."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"
ACTIVE_MODEL_FILE = MODELS_DIR / "active_model.json"

# Путь к весам: активная версия из active_model.json, иначе tomato_v1.pt, иначе COCO-заглушка.
_TRAINED = MODELS_DIR / "tomato_v1.pt"


def _active_model_path() -> Path | None:
    try:
        data = json.loads(ACTIVE_MODEL_FILE.read_text(encoding="utf-8"))
        name = Path(str(data.get("file", ""))).name
        path = MODELS_DIR / name
        return path if name and path.is_file() else None
    except (OSError, ValueError):
        return None


MODEL_PATH = os.getenv(
    "MODEL_PATH",
    str(_active_model_path() or (_TRAINED if _TRAINED.exists() else MODELS_DIR / "yolo11n.pt")),
)
CONF = float(os.getenv("CONF", "0.25"))
IOU = float(os.getenv("IOU", "0.5"))
IMGSZ = int(os.getenv("IMGSZ", "640"))
DEVICE = os.getenv("DEVICE", "")  # "" = авто (GPU, если есть), "cpu", "0"

# Режим заглушки: какие COCO-классы считаем «плодами», пока нет своей модели.
STUB_CLASSES = {"apple", "orange"}

# Порог доли «красных» пикселей, начиная с которого плод считается зрелым (HSV-правило).
RIPE_RED_RATIO = float(os.getenv("RIPE_RED_RATIO", "0.5"))
