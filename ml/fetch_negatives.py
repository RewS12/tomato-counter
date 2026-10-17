"""Негативные примеры для обучения: фото НЕ-томатов (яблоки, апельсины, мячи) из COCO.

Без них модель видела только томаты и считает томатом любой круглый плод.
Берём фото, где объект крупный (виден явно), и выкидываем те, где в подписях COCO упомянуты томаты.
Скачиваем только отобранные фото по одному, а не весь COCO.

Нужны аннотации COCO 2017 в data/raw/coco/annotations/ (instances_train2017.json, captions_train2017.json):
    http://images.cocodataset.org/annotations/annotations_trainval2017.zip

    python ml/fetch_negatives.py
Результат: data/raw/negatives/coco/*.jpg → дальше ml/prepare_dataset.py добавит их с пустой разметкой.
"""
import json
import random
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "raw" / "coco" / "annotations"
OUT = ROOT / "data" / "raw" / "negatives" / "coco"

# категория COCO → сколько фото взять
WANT = {"apple": 280, "orange": 100, "sports ball": 20}
MIN_AREA = 0.01  # крупнейший объект категории ≥ 1% площади кадра
BANNED_WORDS = ("tomato",)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    random.seed(0)
    inst = json.loads((ANN / "instances_train2017.json").read_text(encoding="utf-8"))
    caps = json.loads((ANN / "captions_train2017.json").read_text(encoding="utf-8"))

    banned = {c["image_id"] for c in caps["annotations"] if any(w in c["caption"].lower() for w in BANNED_WORDS)}
    images = {im["id"]: im for im in inst["images"]}
    cat_id = {c["name"]: c["id"] for c in inst["categories"]}

    best_area: dict[tuple[int, int], float] = {}
    for a in inst["annotations"]:
        im = images[a["image_id"]]
        frac = a["area"] / (im["width"] * im["height"])
        key = (a["category_id"], a["image_id"])
        best_area[key] = max(best_area.get(key, 0.0), frac)

    chosen: dict[int, str] = {}
    for name, n in WANT.items():
        cid = cat_id[name]
        pool = sorted(img for (c, img), frac in best_area.items()
                      if c == cid and frac >= MIN_AREA and img not in banned and img not in chosen)
        random.shuffle(pool)
        for img in pool[:n]:
            chosen[img] = name
        print(f"{name}: подходящих {len(pool)}, берём {min(n, len(pool))}")
    print(f"исключено из-за томатов в подписях: {len(banned)} фото COCO")

    OUT.mkdir(parents=True, exist_ok=True)

    def fetch(img_id: int) -> bool:
        im = images[img_id]
        dst = OUT / f"{chosen[img_id].replace(' ', '_')}_{im['file_name']}"
        if dst.exists():
            return True
        try:
            urllib.request.urlretrieve(f"http://images.cocodataset.org/train2017/{im['file_name']}", dst)
            return True
        except OSError as e:
            print("  не скачалось:", im["file_name"], e)
            return False

    with ThreadPoolExecutor(16) as pool:
        ok = sum(pool.map(fetch, chosen))
    print(f"Готово: {ok}/{len(chosen)} фото в {OUT}")


if __name__ == "__main__":
    main()
