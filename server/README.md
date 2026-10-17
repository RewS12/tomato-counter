# server/ — сервер детекции томатов

FastAPI + YOLO. Телефон отправляет фото → получает найденные томаты и сводку «зрелые / незрелые».

## Запуск
```bash
pip install -r requirements.txt          # torch с CUDA ставить отдельно
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- `--host 0.0.0.0` обязателен, иначе телефон не достучится.
- Windows: разрешить Python в брандмауэре (частная сеть) или открыть порт 8000.
- IP ноутбука: `ipconfig` → IPv4 адаптера Wi-Fi. На хот-споте телефона он поменяется.

Проверка: `python tools/smoke.py фото.jpg` — печатает JSON и сохраняет `фото_result.jpg` с рамками.
Запасной веб-интерфейс: открыть `http://<IP>:8000/` в браузере телефона.

## Настройки (переменные окружения)
| Переменная | По умолчанию | Что |
|---|---|---|
| `MODEL_PATH` | см. ниже | веса модели (если задан — `models/ACTIVE` игнорируется) |
| `CONF` | 0.25 | порог уверенности |
| `IOU` | 0.5 | порог NMS (важно для перекрытий) |
| `IMGSZ` | 640 | размер входа модели |
| `DEVICE` | авто | `0` = GPU, `cpu` |
| `RIPE_RED_RATIO` | 0.5 | доля красных пикселей для «зрелый» (HSV-правило) |
| `ADMIN_TOKEN` | — (эндпоинт выключен) | токен для `POST /admin/model`, ≥ 24 символов |
| `MAX_MODEL_MB` | 200 | максимальный размер загружаемых весов |

Какая модель грузится при старте: `MODEL_PATH` → файл `models/ACTIVE` (пишет `/admin/model`) →
`tomato_v2.pt` → `tomato_v1.pt` → `yolo11n.pt`.

## Режимы
- **stub** — предобученная COCO-модель (ищет `apple`/`orange`), зрелость по цвету (HSV). Это **заглушка**, чтобы собрать приложение: томаты она находит плохо.
- **trained** — включается сам, если в именах классов модели есть `ripe`/`unripe`/`green`/`red`/`half`. Полузрелый → `unripe`.

## API
### `POST /detect`
`multipart/form-data`, поле `image` (JPEG/PNG). Параметр `?draw=true` — вернуть картинку с разметкой.

```json
{
  "total": 2,
  "counts": {"ripe": 1, "unripe": 1},
  "objects": [
    {"bbox": [172, 473, 768, 1070], "cls": "ripe", "conf": 0.588, "label": "apple", "red_ratio": 0.82}
  ],
  "width": 800, "height": 1118,
  "model": "yolo11n.pt", "mode": "stub", "ms": 169.9,
  "image_b64": null
}
```
- `bbox` = `[x1, y1, x2, y2]` в пикселях фото **после** поворота по EXIF (`width`×`height`). На телефоне масштабировать под размер ImageView.
- `cls` — всегда `ripe` или `unripe`. `label` — исходное имя класса модели.
- `400` — файл не является картинкой.

### `GET /health`
`{"status":"ok","model":"tomato_v2.pt","mode":"trained","sha256":"b5b65530c9f3","classes":{...}}` — APK может пинговать при вводе IP.
`sha256` — первые 12 символов хэша весов: видно, какой именно файл сейчас работает.

### `POST /admin/model` — загрузить модель и переключиться без перезапуска
Заголовок `Authorization: Bearer <ADMIN_TOKEN>`, `multipart/form-data`:
- `weights` — файл `.pt`;
- `name` — имя в `models/` (по умолчанию имя файла; латиница, цифры, `_.-`, окончание `.pt`);
- `allow_stub=true` — разрешить модель без классов зрелости (по умолчанию такие отклоняются).

Порядок: файл сохраняется во временный → модель загружается и прогревается → только если всё хорошо,
файл переименовывается в `models/<name>`, сервер переключается на неё, имя пишется в `models/ACTIVE`
(после перезапуска загрузится она же). Битый файл или чужие классы → `400`, **старая модель продолжает работать**.

| Код | Когда |
|---|---|
| 200 | `{"previous":"tomato_v1.pt","model":"tomato_v2.pt","sha256":"…","size_mb":18.3,…}` |
| 400 | плохое имя / не загрузилось / нет классов зрелости |
| 401 | неверный токен |
| 404 | `ADMIN_TOKEN` не задан или короче 24 символов — эндпоинт выключен |
| 413 | файл больше `MAX_MODEL_MB` |

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" -F weights=@models/tomato_v2.pt https://agro.setly.space/android-api/admin/model
```
(PowerShell: `curl.exe` вместо `curl`, токен — `$env:ADMIN_TOKEN`.)

> ⚠️ **Безопасность.** Файл `.pt` — это pickle: при загрузке он может выполнить любой код.
> Значит, **кто знает токен — может выполнить код на сервере.** Токен длинный и случайный, только в `.env`, не в git и не в чатах.
> Эндпоинт доступен через публичный `/android-api` без Basic Auth — защищает только токен.
> После хакатона — убрать `ADMIN_TOKEN` (эндпоинт выключится) или закрыть `/android-api/admin/*` в Traefik.

## Деплой на agro.setly.space (Docker)
Контейнер `tomato-server` из ветки `feature/agrovision-web-android`: `server/docker-compose.yml`, порт 8002,
`../models` смонтирован в `/models` (на запись — туда пишутся новые веса и `ACTIVE`).
Traefik → WireGuard → `192.168.2.5:8002`, наружу — `https://agro.setly.space/android-api/*`.

Один раз, на машине с контейнером:
1. Взять код с эндпоинтом: влить `master` в рабочую ветку (`git merge origin/master`).
   Если на сервере есть незакоммиченные правки (сейчас `/health` отдаёт поле `version`, которого нет в git) — сначала закоммитить их.
2. Сгенерировать токен и положить в `server/.env` (файл в `.gitignore`):
   ```bash
   python -c "import secrets; print('ADMIN_TOKEN=' + secrets.token_urlsafe(32))" > server/.env
   ```
3. В `server/docker-compose.yml`, в `environment:` сервиса `server`, добавить:
   ```yaml
   ADMIN_TOKEN: ${ADMIN_TOKEN:-}
   ```
   (compose сам читает `server/.env` рядом с файлом).
4. Пересобрать: `cd server && docker compose up -d --build`.
5. Проверить: `curl https://agro.setly.space/android-api/health` → есть поле `sha256`;
   `curl -X POST https://agro.setly.space/android-api/admin/model` → `401` (если `404` — токен не дошёл до контейнера).
6. Передать токен тому, кто будет выкатывать модели (лично, не в общий чат).

Дальше новая модель выкатывается одной командой `curl …/admin/model` (см. выше), без доступа к серверу.
Если Traefik ограничивает размер запроса (middleware `buffering` с `maxRequestBodyBytes`) — поднять лимит до 50 МБ.
