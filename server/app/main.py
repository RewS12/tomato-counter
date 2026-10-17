"""HTTP-сервер детекции томатов.

Запуск (из папки server/):
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import base64
import json
import os
import re
import secrets
import tempfile
import threading
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from PIL import Image, ImageOps
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import config
from .detector import Detector, draw

detector: Detector | None = None
_detector_lock = threading.Lock()
MODEL_ADMIN_TOKEN = os.getenv("MODEL_ADMIN_TOKEN", "")
MAX_MODEL_SIZE = 300 * 1024 * 1024
MAX_STREAM_FRAME = 3 * 1024 * 1024
MODEL_VERSION_RE = re.compile(r"^tomato_v(\d+)\.pt$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global detector
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    detector = Detector()
    detector.warmup()
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


def get_detector() -> Detector:
    with _detector_lock:
        if detector is None:
            raise HTTPException(503, "Модель ещё не загружена")
        return detector


def require_admin(x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")) -> None:
    if not MODEL_ADMIN_TOKEN:
        raise HTTPException(503, "Замена модели отключена: задайте MODEL_ADMIN_TOKEN")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, MODEL_ADMIN_TOKEN):
        raise HTTPException(401, "Неверный X-Admin-Token")


def model_versions() -> list[dict]:
    items = []
    for path in config.MODELS_DIR.glob("tomato_v*.pt"):
        match = MODEL_VERSION_RE.match(path.name)
        if match:
            version = int(match.group(1))
            items.append({
                "version": version,
                "tag": f"v{version}",
                "file": path.name,
                "size": path.stat().st_size,
            })
    return sorted(items, key=lambda item: item["version"])


def next_model_version() -> int:
    return max((item["version"] for item in model_versions()), default=0) + 1


def write_active_model(version: int, file_name: str, classes: dict[str, str]) -> dict:
    info = {
        "version": version,
        "file": file_name,
        "classes": classes,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    temp = config.ACTIVE_MODEL_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(config.ACTIVE_MODEL_FILE)
    return info


def model_payload(det: Detector, info: dict | None, version: int | None) -> dict:
    return {
        "version": version,
        "tag": f"v{version}" if version else None,
        "file": Path(det.model_path).name,
        "mode": det.mode,
        "classes": {str(i): det.names[i] for i in sorted(det.names)},
        "categories": {det.names[i]: category for i, category in det.class_map.items()},
        "uploaded_at": info.get("uploaded_at") if info else None,
    }


def read_image(data: bytes) -> np.ndarray:
    try:
        img = Image.open(BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")  # фото с телефона часто повёрнуты через EXIF
    except Exception:
        raise HTTPException(400, "Не удалось прочитать изображение")
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


@app.get("/health")
def health():
    det = get_detector()
    match = MODEL_VERSION_RE.match(Path(det.model_path).name)
    return {
        "status": "ok",
        "model": Path(det.model_path).name,
        "version": f"v{int(match.group(1))}" if match else None,
        "mode": det.mode,
        "device": det.device,
        "classes": {det.names[i]: c for i, c in det.class_map.items()},
    }


@app.post("/detect", response_model=DetectOut)
def detect(image: UploadFile = File(...), draw_result: bool = Query(False, alias="draw")):
    det = get_detector()
    bgr = read_image(image.file.read())
    result = det.detect(bgr)
    image_b64 = None
    if draw_result:
        ok, buf = cv2.imencode(".jpg", draw(bgr, result), [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_b64 = base64.b64encode(buf).decode() if ok else None
    return DetectOut(
        total=result.total, counts=result.counts, objects=[o.__dict__ for o in result.objects],
        width=result.width, height=result.height, model=Path(det.model_path).name,
        mode=det.mode, ms=result.ms, image_b64=image_b64,
    )


@app.websocket("/ws/stream")
async def stream_detection(ws: WebSocket):
    await ws.accept()
    try:
        get_detector()
    except HTTPException as exc:
        await ws.send_json({"error": exc.detail})
        await ws.close()
        return
    try:
        while True:
            data = await ws.receive_bytes()
            if len(data) > MAX_STREAM_FRAME:
                await ws.send_json({"error": "Кадр слишком большой"})
                continue
            bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                await ws.send_json({"error": "Не удалось декодировать кадр"})
                continue
            det = get_detector()  # подхватывает hot-swap модели между кадрами
            result = await run_in_threadpool(det.detect, bgr)
            await ws.send_json({
                "total": result.total,
                "counts": result.counts,
                "objects": [o.__dict__ for o in result.objects],
                "width": result.width,
                "height": result.height,
                "model": Path(det.model_path).name,
                "mode": det.mode,
                "device": det.device,
                "ms": result.ms,
            })
    except WebSocketDisconnect:
        pass


@app.get("/models")
def list_models(_: None = Depends(require_admin)):
    det = get_detector()
    active_file = Path(det.model_path).name
    match = MODEL_VERSION_RE.match(active_file)
    active_version = int(match.group(1)) if match else None
    active_info = None
    try:
        data = json.loads(config.ACTIVE_MODEL_FILE.read_text(encoding="utf-8"))
        if data.get("file") == active_file:
            active_info = data
    except (OSError, ValueError):
        pass
    versions = model_versions()
    for item in versions:
        item["active"] = item["file"] == active_file
    return {"active": model_payload(det, active_info, active_version), "models": versions}


@app.post("/models")
def upload_model(file: UploadFile = File(...), _: None = Depends(require_admin)):
    global detector
    if not (file.filename or "").lower().endswith(".pt"):
        raise HTTPException(415, "Ожидается файл .pt")
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(
            dir=config.MODELS_DIR, prefix="upload-", suffix=".pt", delete=False
        ) as tmp:
            temp_path = Path(tmp.name)
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_MODEL_SIZE:
                    raise HTTPException(413, f"Модель больше {MAX_MODEL_SIZE // (1024 * 1024)} МБ")
                tmp.write(chunk)
        if size == 0:
            raise HTTPException(400, "Пустой файл модели")
        if not zipfile.is_zipfile(temp_path):
            raise HTTPException(422, "Файл не похож на PyTorch-модель .pt")
        try:
            new_detector = Detector(str(temp_path))
            new_detector.warmup()
        except Exception as exc:
            raise HTTPException(422, f"Не удалось загрузить модель: {type(exc).__name__}") from exc
        if new_detector.mode != "trained" or not new_detector.class_map:
            raise HTTPException(422, "Модель должна содержать классы ripe/unripe (или red/green/half)")
        classes = {str(i): new_detector.names[i] for i in sorted(new_detector.names)}
        with _detector_lock:
            version = next_model_version()
            final_path = config.MODELS_DIR / f"tomato_v{version}.pt"
            temp_path.replace(final_path)
            temp_path = None
            new_detector.model_path = str(final_path)
            try:
                info = write_active_model(version, final_path.name, classes)
            except Exception:
                final_path.unlink(missing_ok=True)
                raise
            detector = new_detector
        return {"status": "ok", "active": True, **model_payload(new_detector, info, version)}
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@app.post("/models/{version}/activate")
def activate_model(version: str, _: None = Depends(require_admin)):
    global detector
    raw = version.strip().lower()
    if raw.startswith("v"):
        raw = raw[1:]
    if not raw.isdigit():
        raise HTTPException(400, "Версия должна быть числом или vN")
    number = int(raw)
    path = config.MODELS_DIR / f"tomato_v{number}.pt"
    if not path.is_file():
        raise HTTPException(404, f"Модель v{number} не найдена")
    try:
        new_detector = Detector(str(path))
        new_detector.warmup()
    except Exception as exc:
        raise HTTPException(422, f"Не удалось загрузить модель: {type(exc).__name__}") from exc
    if new_detector.mode != "trained" or not new_detector.class_map:
        raise HTTPException(422, "Модель должна содержать классы ripe/unripe (или red/green/half)")
    classes = {str(i): new_detector.names[i] for i in sorted(new_detector.names)}
    with _detector_lock:
        info = write_active_model(number, path.name, classes)
        detector = new_detector
    return {"status": "ok", "active": True, **model_payload(new_detector, info, number)}


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
