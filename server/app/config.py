"""Настройки сервера. Всё переопределяется переменными окружения."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"

# Файл с именем активной модели. Пишет POST /admin/model, чтобы загруженная модель пережила перезапуск.
ACTIVE_FILE = MODELS_DIR / "ACTIVE"


def default_model_path() -> str:
    """MODEL_PATH из окружения → models/ACTIVE → самая новая наша модель → COCO-заглушка."""
    if os.getenv("MODEL_PATH"):
        return os.environ["MODEL_PATH"]
    try:
        active = MODELS_DIR / ACTIVE_FILE.read_text(encoding="utf-8").strip()
        if active.is_file():
            return str(active)
    except OSError:
        pass
    # v2 обучена с негативами (яблоки, апельсины) и не путает их с томатами.
    candidates = [MODELS_DIR / n for n in ("tomato_v2.pt", "tomato_v1.pt", "yolo11n.pt")]
    return str(next((p for p in candidates if p.exists()), candidates[-1]))


MODEL_PATH = default_model_path()
CONF = float(os.getenv("CONF", "0.25"))
IOU = float(os.getenv("IOU", "0.5"))
IMGSZ = int(os.getenv("IMGSZ", "640"))
DEVICE = os.getenv("DEVICE", "")  # "" = авто (GPU, если есть), "cpu", "0"

# Режим заглушки: какие COCO-классы считаем «плодами», пока нет своей модели.
STUB_CLASSES = {"apple", "orange"}

# Порог доли «красных» пикселей, начиная с которого плод считается зрелым (HSV-правило).
RIPE_RED_RATIO = float(os.getenv("RIPE_RED_RATIO", "0.5"))

# POST /admin/model: загрузка весов. Без токена эндпоинт выключен.
# Веса .pt — это pickle: кто знает токен, может выполнить код на сервере. Токен — длинный и случайный.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ADMIN_MIN_TOKEN_LEN = 24
MAX_MODEL_MB = int(os.getenv("MAX_MODEL_MB", "200"))
