# server/ — сервер детекции томатов

FastAPI + YOLO. Телефон отправляет фото → получает найденные томаты и сводку «зрелые / незрелые».

## Запуск

### Docker (рекомендуется)
```bash
cd server
docker compose up -d --build      # локально http://localhost:8002
```
- Снаружи: `https://agro.setly.space/android-api` → Traefik (147.45.141.224) → WireGuard → `192.168.2.5:8002`. Сайт проекта — в корне `https://agro.setly.space/`.
- Веса монтируются из `../models`; при первом старте `yolo11n.pt` скачается туда автоматически.
- Логи: `docker compose logs -f`, остановка: `docker compose down`.

### Без Docker
```bash
pip install -r requirements.txt          # torch с CUDA ставить отдельно
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### GPU (NVIDIA + Docker)
```bash
cd server
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```
- Собирает CUDA-сборку torch (`cu128`) и пробрасывает GPU в контейнер (`gpus: all`, `DEVICE=0`).
- Проверка: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec server python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"`.
- `/health` покажет `"device":"cuda"`. Если у драйвера другой CUDA, поменяйте `TORCH_INDEX_URL` в `docker-compose.gpu.yml`.
- `--host 0.0.0.0` обязателен, иначе телефон не достучится.
- Windows: разрешить Python в брандмауэре (частная сеть) или открыть порт 8000.
- IP ноутбука: `ipconfig` → IPv4 адаптера Wi-Fi. На хот-споте телефона он поменяется.

Проверка: `python tools/smoke.py фото.jpg` — печатает JSON и сохраняет `фото_result.jpg` с рамками.
Запасной веб-интерфейс: открыть `http://<IP>:8000/` в браузере телефона.

## Настройки (переменные окружения)
| Переменная | По умолчанию | Что |
|---|---|---|
| `MODEL_PATH` | `models/tomato_v1.pt`, если есть, иначе `models/yolo11n.pt` | веса модели |
| `CONF` | 0.25 | порог уверенности |
| `IOU` | 0.5 | порог NMS (важно для перекрытий) |
| `IMGSZ` | 640 | размер входа модели |
| `DEVICE` | авто | `0` = GPU, `cpu` |
| `MODEL_ADMIN_TOKEN` | пусто | токен для `POST /models`; без него замена модели отключена |
| `RIPE_RED_RATIO` | 0.5 | доля красных пикселей для «зрелый» (HSV-правило) |

## Замена модели на лету
Модель можно загрузить через API, она получит версию `v2`, `v3`… и сразу станет активной для `/detect`. Старая модель остаётся в `models/`, переключиться обратно можно по версии.

```bash
# токен лежит в server/.env на машине, где запущен сервер
curl -X POST https://agro.setly.space/android-api/models \
  -H "X-Admin-Token: <MODEL_ADMIN_TOKEN>" \
  -F "file=@models/tomato_v2.pt"

# список версий и активная модель
curl https://agro.setly.space/android-api/models \
  -H "X-Admin-Token: <MODEL_ADMIN_TOKEN>"

# переключиться на версию 1
curl -X POST https://agro.setly.space/android-api/models/1/activate \
  -H "X-Admin-Token: <MODEL_ADMIN_TOKEN>"
```

- Принимается только `.pt` до 300 МБ; файл проверяется загрузкой в Ultralytics и прогревом.
- В модели должны быть классы, сводящиеся к `ripe`/`unripe` (`red`/`green`/`half` тоже подходят). Иначе `422`, старая модель продолжает работать.
- Активная версия сохраняется в `models/active_model.json` и подхватывается после перезапуска.
- `X-Admin-Token` обязателен: публичный `/detect` не защищён, а загрузка модели — потенциально опасная операция. Не публикуйте токен и загружайте только доверенные веса.

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
`{"status":"ok","model":"tomato_v1.pt","mode":"trained","device":"cuda","classes":{...}}` — APK может пинговать при вводе IP.

### `WS /ws/stream` — видео в реальном времени
Клиент открывает WebSocket (`wss://agro.setly.space/android-api/ws/stream`) и шлёт JPEG-кадры бинарными сообщениями. Сервер отвечает JSON на каждый кадр:

```json
{
  "total": 3,
  "counts": {"ripe": 2, "unripe": 1},
  "objects": [{"bbox": [120, 80, 310, 290], "cls": "ripe", "conf": 0.81}],
  "width": 640, "height": 480,
  "model": "tomato_v1.pt", "mode": "trained", "device": "cuda", "ms": 21.4
}
```
- Один кадр в полёте: следующий отправляйте только после ответа (в приложении это делает `frameInFlight`).
- Кадр больше 5 МБ или не JPEG/PNG → текстовое сообщение с ошибкой, соединение остаётся открытым.
- На GPU один кадр 640×480 обрабатывается за ~20–30 мс.
- Проверка из терминала: `cd server && python tools/ws_smoke.py ../web/data/demo/tomato_04.jpg`.
