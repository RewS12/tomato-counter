"""COCO-датасеты томатов → единый YOLO-датасет с 2 классами: ripe / unripe.

Сведение классов (ADR-001): полностью зрелый → ripe; полузрелый и зелёный → unripe.
Фото уменьшаются до MAX_SIDE (оригиналы Laboro 4032 px — обучение всё равно на 640).

Негативы — фото НЕ-томатов (яблоки, апельсины...) из data/raw/negatives/**: попадают в датасет
с пустой разметкой, чтобы модель не принимала любой круглый плод за томат.
Источники: ml/fetch_negatives.py (COCO) и data/raw/negatives/own/ — свои снимки, кладите туда.

    python ml/prepare_dataset.py
"""
import json
import shutil
import zlib
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "tomato_yolo"
NEGATIVES = RAW / "negatives"
NEG_VAL_SHARE = 0.15
MAX_SIDE = 1280
CLASSES = ["ripe", "unripe"]

# (имя источника, COCO json, папка с фото, сплит в итоговом датасете)
SOURCES = [
    ("laboro", RAW / "laboro/laboro_tomato/annotations/train.json", RAW / "laboro/laboro_tomato/train", "train"),
    ("laboro", RAW / "laboro/laboro_tomato/annotations/test.json", RAW / "laboro/laboro_tomato/test", "val"),
]


def to_category(name: str) -> str | None:
    n = name.lower()
    if any(k in n for k in ("unripe", "half", "semi", "green")):
        return "unripe"
    if any(k in n for k in ("fully", "ripe")):
        return "ripe"
    return None


def convert(source: str, ann_path: Path, img_dir: Path, split: str, stats: Counter) -> None:
    coco = json.loads(ann_path.read_text(encoding="utf-8"))
    cat_map = {c["id"]: to_category(c["name"]) for c in coco["categories"]}
    print(f"[{source}/{split}] категории:", {c["name"]: cat_map[c["id"]] for c in coco["categories"]})
    anns: dict[int, list] = {}
    for a in coco["annotations"]:
        anns.setdefault(a["image_id"], []).append(a)

    (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
    for im in coco["images"]:
        src = img_dir / im["file_name"]
        if not src.exists():
            stats["missing_images"] += 1
            continue
        stem = f"{source}_{Path(im['file_name']).stem}"
        W, H = im["width"], im["height"]
        # В Laboro часть фото повёрнута через EXIF, а разметка сделана по уже повёрнутому кадру.
        img = ImageOps.exif_transpose(Image.open(src))
        if img.size != (W, H):
            stats["size_mismatch"] += 1
            continue
        lines = []
        for a in anns.get(im["id"], []):
            cat = cat_map.get(a["category_id"])
            if cat is None or a.get("iscrowd"):
                continue
            x, y, w, h = a["bbox"]
            if w < 2 or h < 2:
                continue
            lines.append(f"{CLASSES.index(cat)} {(x + w / 2) / W:.6f} {(y + h / 2) / H:.6f} {w / W:.6f} {h / H:.6f}")
            stats[f"{split}_{cat}"] += 1
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.save(OUT / "images" / split / f"{stem}.jpg", quality=92)
        (OUT / "labels" / split / f"{stem}.txt").write_text("\n".join(lines))
        stats[f"{split}_images"] += 1


def add_negatives(stats: Counter) -> None:
    """Фото без томатов → пустой .txt. Сплит детерминированный по имени файла."""
    files = sorted(p for p in NEGATIVES.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    for src in files:
        split = "val" if zlib.crc32(src.name.encode()) % 100 < NEG_VAL_SHARE * 100 else "train"
        stem = f"neg_{src.parent.name}_{src.stem}"
        img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.save(OUT / "images" / split / f"{stem}.jpg", quality=92)
        (OUT / "labels" / split / f"{stem}.txt").write_text("")
        stats[f"{split}_negatives"] += 1


def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if OUT.exists():
        shutil.rmtree(OUT)
    stats: Counter = Counter()
    for source, ann, img_dir, split in SOURCES:
        if not ann.exists():
            print(f"[{source}] нет {ann} — пропускаю")
            continue
        convert(source, ann, img_dir, split, stats)
    add_negatives(stats)
    (OUT / "data.yaml").write_text(
        f"path: {OUT.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: ripe\n  1: unripe\n",
        encoding="utf-8")
    print(dict(sorted(stats.items())))


if __name__ == "__main__":
    main()
