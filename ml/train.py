"""Дообучение YOLO на томатах (ripe / unripe).

    python ml/train.py                     # yolo11s, 60 эпох
    python ml/train.py --model yolo11n.pt --epochs 30 --batch 16

Лучшие веса копируются в models/tomato_v1.pt (имя — флаг --name).
"""
import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11s.pt", help="базовые веса COCO")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default="tomato_v1")
    args = ap.parse_args()

    base = ROOT / "models" / args.model
    model = YOLO(str(base) if base.exists() else args.model)
    model.train(
        data=str(ROOT / "data" / "tomato_yolo" / "data.yaml"),
        epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=0,
        project=str(ROOT / "runs"), name=args.name, exist_ok=True,
        patience=15, workers=4, cache="ram",
        # Цвет = признак зрелости: оттенок почти не трогаем, яркость/насыщенность варьируем (свет в зале).
        hsv_h=0.005, hsv_s=0.5, hsv_v=0.5, fliplr=0.5, degrees=10, mosaic=1.0,
    )
    best = Path(model.trainer.best)
    dst = ROOT / "models" / f"{args.name}.pt"
    shutil.copy(best, dst)
    print("Готово:", dst)


if __name__ == "__main__":
    main()
