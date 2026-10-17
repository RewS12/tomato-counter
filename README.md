# Урожай под прицелом — подсчёт и зрелость томатов

Хакатон Обнинск, кейс 02. Фото томатов → каждый плод в рамке → «всего / зрелых / незрелых».

| Папка | Что |
|---|---|
| `server/` | FastAPI + YOLO, `POST /detect` — см. [server/README.md](server/README.md) |
| `web/` | AgroVision: сайт + PWA-кабинет (FastAPI + OpenCV + SQLite), см. [web/README.md](web/README.md) |
| `android/` | Kotlin-клиент (камера / галерея → сервер) |
| `ml/` | дообучение YOLO и оценка точности |
| `data/` | датасеты, демо-фото, скрытый тест |
| `models/` | веса (не в git) |
| `brain/` | Obsidian: решения, план, риски, питч |
| `ТЗ.txt` | условие кейса |
