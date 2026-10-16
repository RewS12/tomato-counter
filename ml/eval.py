"""Оценка модели на размеченных фото: подсчёт vs ручная разметка, precision/recall, картинки ошибок.

Использует то же ядро, что и сервер (server/app/detector.py), с теми же порогами.

Разметка — одним из двух способов (можно смешивать):
  1. YOLO txt рядом по имени: labels/<имя_фото>.txt, строки «класс cx cy w h» (0 = ripe, 1 = unripe),
     координаты относительно фото ПОСЛЕ поворота по EXIF. Даёт precision/recall и картинки ошибок.
  2. CSV только с количествами (--counts): file,ripe,unripe. Быстро посчитать глазами — даёт только ошибку подсчёта.

    python ml/eval.py --images data/hidden_test --labels data/labels/hidden_test
    python ml/eval.py --images data/hidden_test --counts data/labels/hidden_counts.csv
    python ml/eval.py --images data/tomato_yolo/images/val --limit 20      # labels/ найдутся сами

Результат: runs/eval/<name>/ — report.md, results.csv, errors/*.jpg
"""
import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
CLASSES = ["ripe", "unripe"]
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# BGR
C_OK, C_WRONG, C_FP, C_MISS = (60, 200, 60), (0, 165, 255), (40, 40, 230), (230, 120, 0)


@dataclass
class Box:
    xyxy: tuple[float, float, float, float]
    cls: str
    conf: float = 1.0


def load_bgr(path: Path) -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def load_yolo_labels(path: Path, w: int, h: int) -> list[Box]:
    boxes = []
    for line in path.read_text().split("\n"):
        parts = line.split()
        if len(parts) < 5:
            continue
        c, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:5])
        boxes.append(Box(((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h), CLASSES[c]))
    return boxes


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(preds: list[Box], gts: list[Box], thr: float) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Жадное сопоставление без учёта класса: самые уверенные предсказания первыми."""
    pairs, used = [], set()
    for pi in sorted(range(len(preds)), key=lambda i: -preds[i].conf):
        best, best_iou = None, thr
        for gi, g in enumerate(gts):
            if gi in used:
                continue
            v = iou(preds[pi].xyxy, g.xyxy)
            if v >= best_iou:
                best, best_iou = gi, v
        if best is not None:
            used.add(best)
            pairs.append((pi, best))
    matched_p = {p for p, _ in pairs}
    fp = [i for i in range(len(preds)) if i not in matched_p]
    fn = [i for i in range(len(gts)) if i not in used]
    return pairs, fp, fn


def draw_errors(bgr, preds, gts, pairs, fp, fn) -> np.ndarray:
    out = bgr.copy()
    t = max(2, round(max(out.shape[:2]) / 500))
    fs = 0.35 * t

    def box(b, color, text, thick):
        x1, y1, x2, y2 = map(int, b.xyxy)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thick)
        if text:
            cv2.putText(out, text, (x1, max(y1 - 4, 12)), cv2.FONT_HERSHEY_SIMPLEX, fs, color, max(1, t - 1))

    for pi, gi in pairs:
        p, g = preds[pi], gts[gi]
        if p.cls == g.cls:
            box(p, C_OK, "", max(1, t - 1))
        else:
            box(p, C_WRONG, f"{g.cls}->{p.cls}", t)
    for i in fp:
        box(preds[i], C_FP, f"FP {preds[i].cls} {preds[i].conf:.2f}", t)
    for i in fn:
        box(gts[i], C_MISS, f"MISS {gts[i].cls}", t)

    legend = [("OK", C_OK), ("wrong class", C_WRONG), ("false positive", C_FP), ("missed", C_MISS)]
    x = 10
    for text, color in legend:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fs * 1.3, t)
        cv2.rectangle(out, (x - 4, 6), (x + tw + 4, 14 + th), (255, 255, 255), -1)
        cv2.putText(out, text, (x, 10 + th), cv2.FONT_HERSHEY_SIMPLEX, fs * 1.3, color, t)
        x += tw + 20
    return out


def safe_div(a, b):
    return a / b if b else 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", type=Path, required=True)
    ap.add_argument("--labels", type=Path, help="папка с YOLO txt (по умолчанию images→labels в пути)")
    ap.add_argument("--counts", type=Path, help="CSV file,ripe,unripe — только количества")
    ap.add_argument("--model", help="веса (по умолчанию как у сервера)")
    ap.add_argument("--conf", type=float, help="порог уверенности (по умолчанию как у сервера)")
    ap.add_argument("--iou", type=float, default=0.5, help="IoU для засчитывания попадания")
    ap.add_argument("--name", help="имя папки отчёта в runs/eval/")
    ap.add_argument("--limit", type=int, help="взять только первые N фото")
    args = ap.parse_args()

    # Настройки ядра читаются из окружения при импорте — выставляем до него.
    if args.model:
        os.environ["MODEL_PATH"] = str(Path(args.model).resolve())
    if args.conf is not None:
        os.environ["CONF"] = str(args.conf)
    sys.path.insert(0, str(ROOT / "server"))
    from app import config
    from app.detector import Detector

    labels_dir = args.labels
    if labels_dir is None and "images" in args.images.parts:
        parts = list(args.images.parts)
        parts[len(parts) - 1 - parts[::-1].index("images")] = "labels"
        labels_dir = Path(*parts)
    counts = {}
    if args.counts:
        with args.counts.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                counts[Path(row["file"]).stem] = {"ripe": int(row["ripe"]), "unripe": int(row["unripe"])}

    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in IMG_EXT)[:args.limit]
    if not images:
        sys.exit(f"Нет фото в {args.images}")

    name = args.name or args.images.name
    out_dir = ROOT / "runs" / "eval" / name
    (out_dir / "errors").mkdir(parents=True, exist_ok=True)

    det = Detector()
    print(f"Модель: {Path(det.model_path).name} ({det.mode}), conf={config.CONF}, IoU матчинга={args.iou}")

    rows = []
    tot = dict(tp=0, fp=0, fn=0, wrong=0)
    per_cls = {c: dict(tp=0, fp=0, fn=0) for c in CLASSES}
    confusion = {g: {p: 0 for p in CLASSES} for g in CLASSES}
    for path in images:
        bgr = load_bgr(path)
        h, w = bgr.shape[:2]
        res = det.detect(bgr)
        preds = [Box(tuple(o.bbox), o.cls, o.conf) for o in res.objects]
        row = {"file": path.name, "pred_total": res.total, "pred_ripe": res.counts["ripe"],
               "pred_unripe": res.counts["unripe"], "ms": res.ms}

        label_file = labels_dir / f"{path.stem}.txt" if labels_dir else None
        if label_file and label_file.exists():
            gts = load_yolo_labels(label_file, w, h)
            pairs, fp, fn = match(preds, gts, args.iou)
            wrong = sum(preds[p].cls != gts[g].cls for p, g in pairs)
            for p, g in pairs:
                confusion[gts[g].cls][preds[p].cls] += 1
                if preds[p].cls == gts[g].cls:
                    per_cls[gts[g].cls]["tp"] += 1
                else:
                    per_cls[preds[p].cls]["fp"] += 1
                    per_cls[gts[g].cls]["fn"] += 1
            for i in fp:
                per_cls[preds[i].cls]["fp"] += 1
            for i in fn:
                per_cls[gts[i].cls]["fn"] += 1
            tot["tp"] += len(pairs)
            tot["fp"] += len(fp)
            tot["fn"] += len(fn)
            tot["wrong"] += wrong
            gt_counts = {c: sum(g.cls == c for g in gts) for c in CLASSES}
            row.update(source="boxes", tp=len(pairs), fp=len(fp), fn=len(fn), wrong_class=wrong)
            if fp or fn or wrong:
                cv2.imwrite(str(out_dir / "errors" / f"{path.stem}.jpg"), draw_errors(bgr, preds, gts, pairs, fp, fn))
        elif path.stem in counts:
            gt_counts = counts[path.stem]
            row.update(source="counts")
        else:
            print(f"  нет разметки для {path.name} — пропускаю")
            continue

        row.update(gt_total=sum(gt_counts.values()), gt_ripe=gt_counts["ripe"], gt_unripe=gt_counts["unripe"])
        row["count_err"] = row["pred_total"] - row["gt_total"]
        rows.append(row)

    if not rows:
        sys.exit("Ни у одного фото нет разметки")

    # --- сводка ---
    n = len(rows)
    mae = sum(abs(r["count_err"]) for r in rows) / n
    mae_cls = {c: sum(abs(r[f"pred_{c}"] - r[f"gt_{c}"]) for r in rows) / n for c in CLASSES}
    boxed = [r for r in rows if r["source"] == "boxes"]
    P = safe_div(tot["tp"], tot["tp"] + tot["fp"])
    R = safe_div(tot["tp"], tot["tp"] + tot["fn"])
    F1 = safe_div(2 * P * R, P + R)

    fields = ["file", "source", "gt_total", "pred_total", "count_err", "gt_ripe", "pred_ripe", "gt_unripe",
              "pred_unripe", "tp", "fp", "fn", "wrong_class", "ms"]
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)

    summary = [f"# Оценка: {name}", "",
               f"Модель `{Path(det.model_path).name}` ({det.mode}) · conf {config.CONF} · "
               f"IoU матчинга {args.iou} · фото: {n}", "",
               "## Подсчёт", "",
               "| | Вручную | Модель | MAE на фото |", "|---|---|---|---|",
               f"| Всего | {sum(r['gt_total'] for r in rows)} | {sum(r['pred_total'] for r in rows)} | {mae:.2f} |"]
    for c in CLASSES:
        summary.append(f"| {c} | {sum(r[f'gt_{c}'] for r in rows)} | {sum(r[f'pred_{c}'] for r in rows)} "
                       f"| {mae_cls[c]:.2f} |")
    if boxed:
        summary += ["", f"## Детекция ({len(boxed)} фото с боксами)", "",
                    f"**Без учёта класса:** precision **{P:.3f}** · recall **{R:.3f}** · F1 {F1:.3f} "
                    f"(TP {tot['tp']}, FP {tot['fp']}, пропущено {tot['fn']})", "",
                    "| Класс | Precision | Recall |", "|---|---|---|"]
        for c in CLASSES:
            s = per_cls[c]
            summary.append(f"| {c} | {safe_div(s['tp'], s['tp'] + s['fp']):.3f} "
                           f"| {safe_div(s['tp'], s['tp'] + s['fn']):.3f} |")
        summary += ["", f"**Зрелость на найденных:** верно {tot['tp'] - tot['wrong']} из {tot['tp']} "
                        f"({safe_div(tot['tp'] - tot['wrong'], tot['tp']):.1%})", "",
                    "| Вручную \\ Модель | ripe | unripe |", "|---|---|---|"]
        for g in CLASSES:
            summary.append(f"| {g} | {confusion[g]['ripe']} | {confusion[g]['unripe']} |")

    per_photo = ["", "## По фото", "",
                 "| Фото | Вручную (з/н) | Модель (з/н) | Ошибка | TP | FP | Пропуск | Не тот класс |",
                 "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        per_photo.append(
            f"| {r['file']} | {r['gt_total']} ({r['gt_ripe']}/{r['gt_unripe']}) | "
            f"{r['pred_total']} ({r['pred_ripe']}/{r['pred_unripe']}) | {r['count_err']:+d} | "
            f"{r.get('tp', '—')} | {r.get('fp', '—')} | {r.get('fn', '—')} | {r.get('wrong_class', '—')} |")
    per_photo += ["", "Картинки ошибок: `errors/` — зелёный = верно, оранжевый = не тот класс, "
                      "красный = ложное срабатывание, синий = пропуск.", ""]
    (out_dir / "report.md").write_text("\n".join(summary + per_photo), encoding="utf-8")

    print("\n".join(summary))
    print(f"\nОтчёт: {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
