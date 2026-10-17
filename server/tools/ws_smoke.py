"""Проверка WebSocket-стрима: отправить один кадр и напечатать ответ.

    python tools/ws_smoke.py путь/к/фото.jpg [--url ws://127.0.0.1:8000]
"""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from websockets.sync.client import connect


def ws_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    path = parts.path.rstrip("/") + "/ws/stream"
    return urlunsplit((scheme, parts.netloc, path, "", ""))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--url", default="ws://127.0.0.1:8000")
    args = ap.parse_args()

    with connect(ws_url(args.url), open_timeout=10) as ws:
        ws.send(args.image.read_bytes())
        res = json.loads(ws.recv())

    if "error" in res:
        print("Ошибка:", res["error"])
        raise SystemExit(1)
    print(json.dumps({k: v for k, v in res.items() if k != "objects"}, ensure_ascii=False))
    for obj in res["objects"]:
        print("  ", obj)


if __name__ == "__main__":
    main()
