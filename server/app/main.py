"""HTTP-сервер детекции томатов.

Запуск (из папки server/):
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import base64
import hashlib
import hmac
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import config
from .detector import Detector, draw

detector: Detector | None = None
model_sha256 = ""
_swap_lock = threading.Lock()  # одна замена модели за раз


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global detector, model_sha256
    detector = Detector(config.MODEL_PATH)
    detector.warmup()
    model_sha256 = sha256_of(detector.model_path)
    yield


app = FastAPI(title="Tomato detector", lifespan=lifespan)


class ObjectOut(BaseModel):
    bbox: list[int]  # x1, y1, x2, y2 в пикселях исходного (повёрнутого по EXIF) фото
    cls: str          # "ripe" | "unripe"
    conf: float
    label: str        # имя класса модели
    red_ratio: float | None = None


class DetectOut(BaseModel):
    total: int
    counts: dict[str, int]
    objects: list[ObjectOut]
    width: int
    height: int
    model: str
    mode: str  # "stub" | "trained"
    ms: float
    image_b64: str | None = None  # JPEG с разметкой, если draw=true


def read_image(data: bytes) -> np.ndarray:
    try:
        img = Image.open(BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")  # фото с телефона часто повёрнуты через EXIF
    except Exception:
        raise HTTPException(400, "Не удалось прочитать изображение")
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@app.get("/health")
def health():
    return {"status": "ok", "model": Path(detector.model_path).name, "mode": detector.mode,
            "sha256": model_sha256[:12],
            "classes": {detector.names[i]: c for i, c in detector.class_map.items()}}


@app.post("/detect", response_model=DetectOut)
def detect(image: UploadFile = File(...), draw_result: bool = Query(False, alias="draw")):
    bgr = read_image(image.file.read())
    result = detector.detect(bgr)
    image_b64 = None
    if draw_result:
        ok, buf = cv2.imencode(".jpg", draw(bgr, result), [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_b64 = base64.b64encode(buf).decode() if ok else None
    return DetectOut(
        total=result.total, counts=result.counts, objects=[o.__dict__ for o in result.objects],
        width=result.width, height=result.height, model=Path(detector.model_path).name,
        mode=detector.mode, ms=result.ms, image_b64=image_b64,
    )


_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.pt$")


def require_admin(authorization: str | None) -> None:
    """Bearer-токен из ADMIN_TOKEN. Без токена (или со слишком коротким) эндпоинт будто не существует."""
    if len(config.ADMIN_TOKEN) < config.ADMIN_MIN_TOKEN_LEN:
        raise HTTPException(404, "Not Found")
    if not authorization or not hmac.compare_digest(authorization.encode(), f"Bearer {config.ADMIN_TOKEN}".encode()):
        raise HTTPException(401, "Неверный токен", headers={"WWW-Authenticate": "Bearer"})


@app.post("/admin/model")
def upload_model(
    weights: UploadFile = File(..., description="веса YOLO (.pt)"),
    name: str | None = Form(None, description="имя файла в models/, по умолчанию — имя загруженного"),
    allow_stub: bool = Form(False, description="разрешить модель без классов зрелости"),
    authorization: str | None = Header(None),
):
    """Загрузить веса и сразу переключить сервер на них (без перезапуска).

    Модель сначала загружается и прогревается из временного файла; если она битая или в ней нет
    классов зрелости, старая продолжает работать. Активная модель записывается в models/ACTIVE.
    """
    global detector, model_sha256
    require_admin(authorization)
    name = name or weights.filename or ""
    if not _MODEL_NAME.match(name):
        raise HTTPException(400, "Имя файла: латиница, цифры, _.- и окончание .pt (например tomato_v3.pt)")

    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    limit = config.MAX_MODEL_MB * 1024 * 1024
    with _swap_lock:
        tmp = config.MODELS_DIR / f".upload-{uuid.uuid4().hex}.pt"
        try:
            size = 0
            with open(tmp, "wb") as out:
                while chunk := weights.file.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"Файл больше {config.MAX_MODEL_MB} МБ")
                    out.write(chunk)
            try:
                new = Detector(str(tmp))
                new.warmup()
            except Exception as e:
                raise HTTPException(400, f"Не удалось загрузить модель: {type(e).__name__}: {e}")
            if new.mode != "trained" and not allow_stub:
                raise HTTPException(400, f"В модели нет классов зрелости (ripe/unripe/green...): {list(new.names.values())}")

            target = config.MODELS_DIR / name
            os.replace(tmp, target)
            new.model_path = str(target)
            active_tmp = config.MODELS_DIR / ".ACTIVE.tmp"
            active_tmp.write_text(name, encoding="utf-8")
            os.replace(active_tmp, config.ACTIVE_FILE)

            previous = Path(detector.model_path).name if detector else None
            detector, model_sha256 = new, sha256_of(str(target))
        finally:
            tmp.unlink(missing_ok=True)

    return {"status": "ok", "previous": previous, "model": name, "mode": detector.mode,
            "sha256": model_sha256, "size_mb": round(size / 1024 / 1024, 1),
            "classes": {detector.names[i]: c for i, c in detector.class_map.items()}}


@app.get("/", response_class=HTMLResponse)
def index():
    """Запасной веб-интерфейс: открыть http://<IP>:8000 с телефона или ноутбука."""
    return """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Томаты</title>
<style>body{font-family:system-ui;margin:16px;max-width:900px}img{max-width:100%;margin-top:12px}
#s{font-size:1.3em;margin-top:12px}</style>
<h2>🍅 Подсчёт томатов</h2>
<input type=file id=f accept="image/*" capture=environment>
<div id=s></div><img id=i>
<script>
f.onchange=async()=>{const d=new FormData();d.append('image',f.files[0]);s.textContent='Обработка…';
const r=await fetch('/detect?draw=true',{method:'POST',body:d});const j=await r.json();
if(!r.ok){s.textContent='Ошибка: '+(j.detail||r.status);return}
s.textContent=`Всего: ${j.total} · зрелых: ${j.counts.ripe} · незрелых: ${j.counts.unripe} (${j.ms} мс, ${j.mode})`;
i.src='data:image/jpeg;base64,'+j.image_b64}
</script>"""
