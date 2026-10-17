# Архитектура, API и безопасность

## Технологическая схема

```
Browser (HTML/CSS/JS, mobile 320+) --HTTP/JSON/Multipart--> FastAPI (127.0.0.1:8000)
  |  landing / app.html                            |  input validation
  |  original/annotated image                    |  OpenCV/NumPy (HSV, contour, shape)
  |  correction, forms                           |  SQLite CRUD
  |  manifest + shell service worker             |  runtime/images (uuid files)
```

Алгоритм использует декодирование BGR → HSV (Gaussian blur), красную маску для Hue 0–12 и 170–179, зелёную 34–76, минимальную насыщенность, открытие/закрытие морфологией, поиск внешних контуров, фильтры площади, aspect ratio и circularity. Один контур — один обнаруженный объект; перекрытые плоды могут слиться. Формируемые числа получены из найденных контуров. `shape_score` оценивает геометрию и не является калиброванной вероятностью.

Для изменения рамок клиент отправляет список объектов на `PUT /apiv2/analyses/{id}/objects`, сервер повторно проверяет координаты в пределах фото, пересчитывает категории и создаёт новый overlay. Нельзя редактировать текущие рамки без явной команды сохранения. Всегда можно открыть исходное фото.

## REST API

| Метод | Маршрут | Смысл |
| --- | --- | --- |
| GET | `/apiv2/health` | Status и метод CV |
| POST | `/apiv2/analyze/fruits` | Multipart file; boxes, counts, URLs, ms, id |
| GET | `/apiv2/analyses` | История |
| GET | `/apiv2/analyses/{id}` | Повторный просмотр |
| PUT | `/apiv2/analyses/{id}/objects` | Ревизия боксов |
| POST | `/apiv2/analyze/plant` | Простые цветовые метрики, не диагноз |
| POST | `/apiv2/analyze/soil` | Яркость/контраст, не определяет влажность |
| POST | `/apiv2/upload` | Пользовательские фото дневника/лота |
| GET/POST/PUT/DELETE | `/apiv2/plants[/{id}]` | CRUD растений |
| GET/POST/PUT/DELETE | `/apiv2/observations[/{id}]` | CRUD наблюдений |
| GET/POST/PATCH/DELETE | `/apiv2/recommendations[/{id}]` | Рекомендации и статусы |
| GET/POST/PUT/DELETE | `/apiv2/lots[/{id}]` | CRUD лотов |
| GET | `/apiv2/knowledge?query=&topic=` | Статьи и фильтрация |
| GET | `/apiv2/evaluation` | Непридуманные результаты тестов |
| GET | `/apiv2/demo` | Список 13 синтетических изображений |
| GET | `/apiv2/export` | Выгрузка локальной базы JSON |

Pydantic принимает оболочку `{"data":{...fields}}` для CRUD и коррекции. Свободные поля не принимаются; API отвечает 400/404/409/413/415/422 при соответствующих условиях. Файлы ограничены 8 МБ, разрешены JPG/PNG/WebP и проверяются реальным декодированием OpenCV. Имя и расширение генерируются на сервере на основе разрешённого MIME, исходное имя не участвует в пути.

## Модель данных

`plants(id,culture,variety,location,bed,planted_at,description,created_at,updated_at)`
`analyses(id,original_url,overlay_url,result_json,created_at)`
`observations(id,plant_id,date,category,description,action,outcome,photo_url,analysis_id,...)`
`lots(id,title,culture,quantity,unit,price,currency,status,buyer,description,photo_url,...)`
`recommendations(id,title,evidence,explanation,action,certainty,verify,status,outcome,plant_id,...)`

Это демонстрационная single-user-схема. В промышленной системе обязательны FK, auth, роли, журнал действий, резервные копии, image ACL, ограничения на количество хранимых файлов, мониторинг и защита от злоупотреблений.

## PWA / офлайн

`manifest.json`, `/sw.js` и иконка позволяют кэшировать статическую оболочку там, где браузер поддерживает Service Worker (localhost/HTTPS). **При недоступном Python-сервере не работают CV, записи и загрузки**. Нельзя обещать офлайн-детекцию или офлайн-синхронизацию; это следующий этап.
