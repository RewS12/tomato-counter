"""Проверка сервера: отправить фото и сохранить разметку.

    python tools/smoke.py путь/к/фото.jpg [--url http://127.0.0.1:8000]
"""
import argparse
import base64
import json
import sys
import urllib.request
import uuid
from pathlib import Path


def post_image(url: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{url}/detect?draw=true", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    res = post_image(args.url, args.image)
    out = args.image.with_name(args.image.stem + "_result.jpg")
    out.write_bytes(base64.b64decode(res.pop("image_b64")))
    print(json.dumps({k: v for k, v in res.items() if k != "objects"}, ensure_ascii=False))
    for o in res["objects"]:
        print("  ", o)
    print("Разметка:", out)


if __name__ == "__main__":
    sys.exit(main())
