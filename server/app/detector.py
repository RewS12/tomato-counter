"""Ядро: фото → найденные плоды с категорией зрелости.

Одна функция `Detector.detect` используется и сервером, и (дальше) скриптом оценки точности.
Два режима:
- stub    — предобученная COCO-модель; берём классы из STUB_CLASSES, зрелость по HSV;
- trained — наша модель, классы которой уже означают зрелость (ripe/unripe, b_green, ...).
"""
import threading
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from ultralytics import YOLO

from . import config, ripeness

CATEGORIES = ("ripe", "unripe")
COLORS = {"ripe": (40, 40, 230), "unripe": (40, 200, 40)}  # BGR


def category_from_name(name: str) -> str | None:
    """Сводим имена классов датасета к двум категориям. Полузрелый → unripe (ADR-001)."""
    n = name.lower()
    if any(k in n for k in ("unripe", "green", "half")):
        return "unripe"
    if any(k in n for k in ("ripe", "red")):
        return "ripe"
    return None


@dataclass
class Detection:
    bbox: list[int]
    cls: str
    conf: float
    label: str  # исходное имя класса модели
    red_ratio: float | None = None


@dataclass
class Result:
    objects: list[Detection]
    width: int
    height: int
    ms: float
    counts: dict[str, int] = field(init=False)

    def __post_init__(self):
        self.counts = {c: sum(o.cls == c for o in self.objects) for c in CATEGORIES}

    @property
    def total(self) -> int:
        return len(self.objects)


class Detector:
    def __init__(self, model_path: str = config.MODEL_PATH):
        self.model_path = model_path
        self.model = YOLO(model_path)
        self.names: dict[int, str] = self.model.names
        trained = {i: category_from_name(n) for i, n in self.names.items()}
        self.mode = "trained" if any(trained.values()) else "stub"
        if self.mode == "trained":
            self.class_map = {i: c for i, c in trained.items() if c}
        else:
            self.class_map = {i: None for i, n in self.names.items() if n in config.STUB_CLASSES}
        self._lock = threading.Lock()  # YOLO.predict не потокобезопасен

    def warmup(self) -> None:
        self.detect(np.zeros((640, 640, 3), dtype=np.uint8))

    def detect(self, bgr: np.ndarray) -> Result:
        t0 = time.perf_counter()
        with self._lock:
            pred = self.model.predict(
                bgr, conf=config.CONF, iou=config.IOU, imgsz=config.IMGSZ,
                device=config.DEVICE or None, classes=list(self.class_map), verbose=False,
            )[0]
        objects = []
        for xyxy, conf, cls_id in zip(pred.boxes.xyxy.tolist(), pred.boxes.conf.tolist(), pred.boxes.cls.tolist()):
            box = tuple(int(round(v)) for v in xyxy)
            cls_id = int(cls_id)
            category = self.class_map.get(cls_id)
            red = None
            if category is None:
                category, red = ripeness.classify(bgr, box, config.RIPE_RED_RATIO)
            objects.append(Detection(list(box), category, round(conf, 3), self.names[cls_id], red))
        h, w = bgr.shape[:2]
        return Result(objects, w, h, round((time.perf_counter() - t0) * 1000, 1))


def draw(bgr: np.ndarray, result: Result) -> np.ndarray:
    """Рамки цветом категории + сводка в углу."""
    out = bgr.copy()
    thick = max(2, round(max(out.shape[:2]) / 400))
    for o in result.objects:
        x1, y1, x2, y2 = o.bbox
        color = COLORS[o.cls]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thick)
        cv2.putText(out, f"{o.cls} {o.conf:.2f}", (x1, max(y1 - 5, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4 * thick, color, max(1, thick - 1))
    summary = f"total {result.total} | ripe {result.counts['ripe']} | unripe {result.counts['unripe']}"
    cv2.putText(out, summary, (10, 15 * thick + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * thick, (255, 255, 255), thick + 2)
    cv2.putText(out, summary, (10, 15 * thick + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * thick, (0, 0, 0), thick)
    return out
