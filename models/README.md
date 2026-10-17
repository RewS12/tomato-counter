# models/

Сюда кладём веса (`*.pt`). В git не попадают.

- `yolo11n.pt` — предобученная COCO, **заглушка** (скачивается автоматически при первом запуске сервера).
- `tomato_v2.pt` — **по умолчанию**, v1 + негативы (не путает яблоки с томатами). Скачать из релиза:
  ```bash
  gh release download weights-v2 --repo RewS12/tomato-counter --pattern tomato_v2.pt --dir models
  ```
  (вручную: https://github.com/RewS12/tomato-counter/releases/tag/weights-v2).
  SHA256: `b5b65530c9f3a3506766747fc5004badadba49084e45eb35809f71dece10d3ed`
- `tomato_v1.pt` — первая версия, только томаты. Скачать из релиза:
  ```bash
  gh release download weights-v1 --repo RewS12/tomato-counter --pattern tomato_v1.pt --dir models
  ```
  (репозиторий приватный — нужен доступ и `gh auth login`; вручную: страница релиза
  https://github.com/RewS12/tomato-counter/releases/tag/weights-v1).
  SHA256: `f4a3e4b2745e8b6478e0b7cf02682d5b0d86af80f721db8c49c6c71c5fbb9373`

Сервер берёт путь из переменной `MODEL_PATH`.
