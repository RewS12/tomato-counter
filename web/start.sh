#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
printf 'Откройте: http://127.0.0.1:8000\n'
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
