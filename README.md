# Safety Telemetry Platform

Backend-платформа для хакатона: приём телеметрии с сенсоров (CCTV/IoT/пожарные панели/alarm-системы),
хранение и два независимых интерфейса доступа к данным:

- **REST + SSE** (`/devices`, `/telemetry`, `/incidents`, `/dashboards`, `/stream/*`) — для
  автономного дашборд-приложения.
- **MCP** (`/mcp-server`, транспорт streamable-http) — для агентной системы: чтение телеметрии/инцидентов, запись
  инцидентов (гипотезы) и кастомных dashboard-specs по запросу оператора.

### Что построено на хакатоне, что унаследовано

**Полностью реализовано в ходе хакатона:**
- FastAPI backend с асинхронной архитектурой (SQLAlchemy, Alembic миграции, Pydantic валидация)
- Ingestion API (`POST /ingest/telemetry`, `WS /ingest/stream`) с апсертом устройств по `external_id`
- REST API для чтения устройств, телеметрии, инцидентов, дашбордов
- SSE-потоки для live-обновлений (Redis pub/sub)
- MCP сервер (13 инструментов) для агентной системы
- Адаптер-мост (`app/adapter/bridge.py`) к State Machine API симулятора (перекладывает реальные события в ingestion)

**Внешние зависимости (не наш код):**
- State Machine API (контракт в `raw-source/fire-safety-state-api-v0.2.2/`) — создан другой командой, развёрнут на `https://api.aitinkerers.space`
- Симулятор (team "Simulation") — предоставляет сценарии и события через State Machine API

Полная архитектура и разбивка ответственности — см. план в `/Users/vitalynec/.claude/plans/swirling-meandering-aho.md`.

---

## Для команды симулятора (ingestion)

### Примечание: синтетические vs. реальные данные

Все примеры ниже и в файлах `contracts/safety-telemetry-platform-v1/examples/` — **синтетические/иллюстративные**
(для тестирования и разработки): они генерируются вручную через curl, содержат фиксированные timestamps
и `"origin": "synthetic"` в провенансе.

**Реальные данные** появляются, только если запущен мост `bridge` с валидным `STATE_MACHINE_BEARER_TOKEN` —
тогда события приходят от симулятора с `"origin": "recorded"` (в провенансе указаны реальные source_id,
acquisition_id, audio_source_file и SHA256). Остальная платформа при этом не меняется и не знает разницы —
все три интерфейса (REST, SSE, MCP) работают одинаково с синтетическими и реальными данными.

### Контракт приёма данных

Два способа отправить телеметрию:

#### 1. HTTP (POST `/ingest/telemetry`)

Единый объект или список объектов:

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "cam-12",
      "type": "cctv",
      "name": "Camera warehouse A-2",
      "location": {"building": "A", "floor": 2, "zone": "warehouse"}
    },
    "metric_type": "video_event",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "quality": "valid",
    "availability": "fresh",
    "provenance": {"source_id": "sim-dataset-7", "origin": "synthetic"},
    "external_event_id": "evt-abc-123"
  }'
```

**Ответ:**
```json
{"ingested": 1}
```

Пример для радио-канала (`type: "radio"`) — расшифрованное сообщение переговоров. Одна
`TelemetryReading`-запись на одно транскрибированное сообщение/реплику (не непрерывный поток),
`ts`/`end_ts` — начало/конец реплики. Аудио-вложение (`audio_url`, `audio_duration_ms`) пока не
передаётся симулятором и ожидается позже.

Минимальный пример:

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "radio-ch-3",
      "type": "radio",
      "name": "Channel 3"
    },
    "metric_type": "radio_audio",
    "ts": "2026-09-12T10:05:00Z",
    "end_ts": "2026-09-12T10:05:12Z",
    "transcript": "Command, this is Engine 12, heavy smoke on the third floor.",
    "payload": {"speaker": "unit-12", "confidence": 0.94}
  }'
```

Расширенный пример с полной провенанцей (происхождением/доверием к данным):

```bash
curl -X POST http://localhost:8000/ingest/telemetry \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-change-me" \
  -d '{
    "device": {
      "external_id": "RADIO-A",
      "type": "radio",
      "name": "Radio Channel A (Main)"
    },
    "metric_type": "radio_audio",
    "ts": "2026-09-12T10:05:30Z",
    "end_ts": "2026-09-12T10:05:42Z",
    "transcript": "Engine 12 to command, we have heavy smoke on the third floor, east wing. Visibility is very low.",
    "external_event_id": "ev-radio-text-001",
    "quality": "valid",
    "availability": "fresh",
    "provenance": {
      "origin": "recorded",
      "model": "mlx-community/whisper-large-v3-turbo-q4",
      "delivery": "prerecorded",
      "machine_generated": true,
      "human_verified": false,
      "audio_source_file": "archive/2026-09-12-radio-a.wav",
      "audio_source_sha256": "a1b2c3d4e5f6...",
      "source_id": "broadcastify-archive-import",
      "acquisition_id": "session-2026-09-12-001"
    },
    "payload": {
      "language": "en",
      "channel_id": "RADIO-A",
      "stream_id": "RADIO-A-primary",
      "speaker": "engine-12",
      "confidence": 0.94,
      "words": [
        {"word": "Engine", "start_ms": 0, "end_ms": 250, "confidence": 0.99},
        {"word": "12", "start_ms": 280, "end_ms": 450, "confidence": 0.98},
        {"word": "command", "start_ms": 500, "end_ms": 750, "confidence": 0.97}
      ],
      "timing_notes": ["Early word detected 340ms before segment boundary"]
    }
  }'
```

#### 2. WebSocket (WS `/ingest/stream`)

Постоянное соединение, по одному объекту на строку (JSON):

```javascript
const ws = new WebSocket('ws://localhost:8000/ingest/stream', [], {
  headers: {'X-API-Key': 'dev-secret-change-me'}
});

ws.on('message', (msg) => {
  console.log(JSON.parse(msg));  // {"status": "ok"} или {"status": "error", "detail": "..."}
});

ws.send(JSON.stringify({
  device: {
    external_id: "iot-temp-01",
    type: "iot",
    name: "Temperature sensor zone B",
    location: {building: "B", floor: 1}
  },
  metric_type: "temperature",
  ts: "2026-09-12T10:05:30Z",
  end_ts: null,
  value: 23.5,
  unit: "°C",
  payload: {}
}));
```

### Схема TelemetryIn

| Поле | Тип | Опционально | Описание |
|------|-----|-------------|---------|
| `device` | DeviceIn | нет | Обвязка устройства |
| `device.external_id` | string | нет | Уникальный ID в системе источника |
| `device.type` | enum | нет | `cctv`, `iot`, `fire_panel`, `alarm`, `water_sensor`, `radio`, `other` |
| `device.name` | string | да | Человеко-читаемое имя |
| `device.location` | DeviceLocation | да | Здание, этаж, зона, координаты |
| `metric_type` | enum | нет | `temperature`, `smoke`, `water_level`, `motion`, `video_event`, `heartbeat`, `other`, `access`, `occupancy`, `radio_audio`, `system`, `obscuration`, `co`, `eco2` |
| `ts` | ISO 8601 datetime | нет | Начало события |
| `end_ts` | ISO 8601 datetime | да | **Только для событий с длительностью** (motion с ts по end_ts). Для точечных событий не передавать или `null`. |
| `value` | float | да | Для скалярных метрик (температура, уровень воды) |
| `unit` | string | да | Единица измерения (°C, m, % и т.д.) |
| `payload` | dict | да | Произвольные структурированные данные (детекции, статусы) |
| `quality` | enum | да | Качество исходного значения: `valid`, `missing`, `invalid` |
| `availability` | enum | да | Свежесть/связность устройства на момент показания: `fresh`, `stale`, `missing`, `invalid`, `disconnected` |
| `provenance` | dict | да | Произвольные метаданные о происхождении данных (например, `source_id` исходного датасета, исходное время записи, тип происхождения — `recorded`/`synthetic`/`derived`/`human_report`) |
| `external_event_id` | string | да | Непрозрачный ID события/наблюдения из системы-источника — для идемпотентности и сверки с записями источника |
| `transcript` | string | да | Расшифровка радиопереговоров (speech-to-text) для одного сообщения/реплики. Актуально для `metric_type: "radio_audio"` и `device.type: "radio"` |
| `audio_url` | string | да | Ссылка на исходный аудиоклип реплики. Пока не заполняется симулятором (транскрипт приходит без аудио); зарезервировано на будущее |
| `audio_duration_ms` | int | да | Длительность аудиоклипа в миллисекундах, если известна |

### Авторизация

**Все запросы требуют заголовок:**
```
X-API-Key: <значение из .env API_KEY>
```

По умолчанию: `dev-secret-change-me` (см. `app/core/config.py`).

---

## Для команды дашборда (REST + SSE)

### REST API endpoints

#### Устройства

**`GET /devices`** — список устройств с фильтрацией

Параметры:
- `type` (query, optional): фильтр по типу (cctv, iot, fire_panel, alarm, water_sensor, other)
- `status` (query, optional): фильтр по статусу (online, offline, fault)
- `building` (query, optional): здание
- `floor` (query, optional): этаж
- `zone` (query, optional): зона

```bash
curl -X GET "http://localhost:8000/devices?type=cctv&building=A" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `list[DeviceOut]`
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "external_id": "cam-12",
    "type": "cctv",
    "name": "Camera warehouse A-2",
    "location": {"building": "A", "floor": 2, "zone": "warehouse"},
    "status": "online",
    "metadata": {},
    "first_seen_at": "2026-09-12T09:30:00Z",
    "last_seen_at": "2026-09-12T10:15:00Z"
  }
]
```

**`GET /devices/{device_id}`** — одно устройство

```bash
curl -X GET "http://localhost:8000/devices/550e8400-e29b-41d4-a716-446655440000" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `DeviceOut` (см. выше)

---

#### Телеметрия

**`GET /telemetry`** — запрос показаний с фильтрацией

Параметры:
- `device_id` (query, optional, UUID): ID устройства
- `metric_type` (query, optional): тип метрики
- `since` (query, optional, ISO 8601): начало диапазона
- `until` (query, optional, ISO 8601): конец диапазона
- `limit` (query, default=100): максимальное число результатов

```bash
curl -X GET "http://localhost:8000/telemetry?device_id=550e8400-e29b-41d4-a716-446655440000&metric_type=video_event&since=2026-09-12T09:00:00Z&limit=50" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `list[TelemetryOut]`
```json
[
  {
    "id": 42,
    "device_id": "550e8400-e29b-41d4-a716-446655440000",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "metric_type": "video_event",
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "ingested_at": "2026-09-12T10:00:05Z"
  }
]
```

**`GET /telemetry/latest`** — последние показания по устройствам

Параметры:
- `device_id` (query, optional, list[UUID]): список ID устройств (может повторяться)
- `type` (query, optional): тип устройства
- `building` (query, optional): здание
- `floor` (query, optional): этаж
- `zone` (query, optional): зона

```bash
curl -X GET "http://localhost:8000/telemetry/latest?device_id=550e8400-e29b-41d4-a716-446655440000&device_id=660e8400-e29b-41d4-a716-446655440001&type=cctv" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `list[TelemetryOut]` (одно на устройство, самое свежее)

---

#### Инциденты

**`GET /incidents`** — список инцидентов с фильтрацией

Параметры:
- `status` (query, optional): фильтр по статусу (open, acknowledged, resolved, escalated)
- `type` (query, optional): тип инцидента (fire, flood, intrusion, equipment_fault, other)
- `since` (query, optional, ISO 8601): открыт начиная с этой даты

```bash
curl -X GET "http://localhost:8000/incidents?status=open&type=fire" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `list[IncidentOut]` (без evidence, для производительности)
```json
[
  {
    "id": "11111111-2222-3333-4444-555555555555",
    "type": "fire",
    "status": "open",
    "severity": "high",
    "location": {"building": "A", "zone": "warehouse"},
    "summary": "Smoke detected in warehouse A",
    "metadata": {},
    "opened_at": "2026-09-12T10:00:00Z",
    "updated_at": "2026-09-12T10:05:00Z",
    "closed_at": null,
    "evidence": []
  }
]
```

**`GET /incidents/{incident_id}`** — одинцидент с evidence

```bash
curl -X GET "http://localhost:8000/incidents/11111111-2222-3333-4444-555555555555" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `IncidentOut` (с полным массивом evidence)
```json
{
  "id": "11111111-2222-3333-4444-555555555555",
  "type": "fire",
  "status": "open",
  "severity": "high",
  "location": {"building": "A", "zone": "warehouse"},
  "summary": "Smoke detected in warehouse A",
  "metadata": {},
  "opened_at": "2026-09-12T10:00:00Z",
  "updated_at": "2026-09-12T10:05:00Z",
  "closed_at": null,
  "evidence": [
    {
      "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
      "device_id": "550e8400-e29b-41d4-a716-446655440000",
      "reading_id": 42,
      "note": "smoke detected by CCTV model v2",
      "created_at": "2026-09-12T10:00:00Z"
    }
  ]
}
```

---

#### Дашборды

**`GET /dashboards`** — список dashboard specs

```bash
curl -X GET "http://localhost:8000/dashboards" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `list[DashboardOut]`
```json
[
  {
    "id": "cccccccc-dddd-eeee-ffff-000000000000",
    "title": "Warehouse A Monitoring",
    "created_by": "agent",
    "spec": {"layout": "grid", "widgets": [...]},
    "version": 2,
    "created_at": "2026-09-12T09:00:00Z",
    "updated_at": "2026-09-12T10:15:00Z"
  }
]
```

**`GET /dashboards/{dashboard_id}`** — один dashboard

```bash
curl -X GET "http://localhost:8000/dashboards/cccccccc-dddd-eeee-ffff-000000000000" \
  -H "X-API-Key: dev-secret-change-me"
```

**Ответ:** `DashboardOut` (см. выше)

---

### SSE Streams

Три потока для real-time обновлений (Server-Sent Events). Подписка без параметров, фильтрация на клиенте.

**`GET /stream/telemetry`** — события телеметрии

```bash
curl -X GET "http://localhost:8000/stream/telemetry" \
  -H "X-API-Key: dev-secret-change-me"
```

Сообщение на канале (raw JSON):
```json
{
  "id": 42,
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "ts": "2026-09-12T10:00:00Z",
  "end_ts": null,
  "metric_type": "video_event",
  "value": null,
  "unit": null,
  "payload": {"event": "smoke_detected"},
  "ingested_at": "2026-09-12T10:00:05Z"
}
```

**`GET /stream/incidents`** — события инцидентов

```bash
curl -X GET "http://localhost:8000/stream/incidents" \
  -H "X-API-Key: dev-secret-change-me"
```

Сообщение на канале:
```json
{
  "id": "11111111-2222-3333-4444-555555555555",
  "type": "fire",
  "status": "open",
  "severity": "high",
  "location": {...},
  "summary": "...",
  "metadata": {},
  "opened_at": "...",
  "updated_at": "...",
  "closed_at": null
}
```

**`GET /stream/dashboards/{dashboard_id}`** — события дашборда

```bash
curl -X GET "http://localhost:8000/stream/dashboards/cccccccc-dddd-eeee-ffff-000000000000" \
  -H "X-API-Key: dev-secret-change-me"
```

Сообщение на канале: обновления DashboardOut (текущая реализация транслирует все события на общий канал; фильтрация по dashboard_id пока на клиенте).

---

### Swagger UI (для исследования)

**`GET /docs`** — интерактивный Swagger UI

- **Доступен без авторизации** — статический просмотр
- **"Try it out" требует X-API-Key** в заголовках (вводится в интерфейс)
- Полный перечень параметров и примеры

---

## Для агентной системы (MCP)

### Транспорт и монтирование

- **Путь:** `/mcp-server`
- **Транспорт:** streamable-http (Starlette SSE)
- **Авторизация:** X-API-Key header (как REST API)
- **Соединение:** инициируется агентом; платформа слушает на `/mcp-server/mcp`

```bash
# Пример curl подписки на инструменты MCP (SSE)
curl -X POST "http://localhost:8000/mcp-server/mcp" \
  -H "X-API-Key: dev-secret-change-me" \
  -H "Content-Type: application/json"
```

### MCP Tools

#### Устройства

**`list_devices(type: str | None, status: str | None) → list[dict]`**

Список устройств, опционально отфильтрованный по типу и/или статусу.

Параметры:
- `type`: фильтр по типу (cctv, iot, fire_panel, alarm, water_sensor, other)
- `status`: фильтр по статусу (online, offline, fault)

Возвращает:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "external_id": "cam-12",
    "type": "cctv",
    "name": "Camera warehouse A-2",
    "location": {"building": "A", "floor": 2, "zone": "warehouse"},
    "status": "online",
    "metadata": {},
    "first_seen_at": "2026-09-12T09:30:00Z",
    "last_seen_at": "2026-09-12T10:15:00Z"
  }
]
```

**`get_device(device_id: str) → dict | None`**

Получить одно устройство по ID.

Параметры:
- `device_id`: UUID устройства

Возвращает: объект Device или None.

---

#### Телеметрия

**`query_telemetry(device_id: str | None, metric_type: str | None, since: str | None, until: str | None, limit: int = 100) → list[dict]`**

Запрос показаний с фильтрацией.

Параметры:
- `device_id`: UUID устройства (опционально)
- `metric_type`: тип метрики (опционально)
- `since`: ISO 8601 начало диапазона (опционально)
- `until`: ISO 8601 конец диапазона (опционально)
- `limit`: максимум результатов (по умолчанию 100)

Возвращает:
```json
[
  {
    "id": 42,
    "device_id": "550e8400-e29b-41d4-a716-446655440000",
    "ts": "2026-09-12T10:00:00Z",
    "end_ts": null,
    "metric_type": "video_event",
    "value": null,
    "unit": null,
    "payload": {"event": "smoke_detected", "confidence": 0.87},
    "ingested_at": "2026-09-12T10:00:05Z"
  }
]
```

**`get_latest_readings(device_ids: list[str] | None, type: str | None) → list[dict]`**

Последние показания по устройствам.

Параметры:
- `device_ids`: список UUID (опционально)
- `type`: фильтр по типу устройства (опционально)

Возвращает: одно TelemetryOut на устройство.

---

#### Инциденты

**`list_incidents(status: str | None, type: str | None, since: str | None) → list[dict]`**

Список инцидентов с фильтрацией.

Параметры:
- `status`: фильтр по статусу (open, acknowledged, resolved, escalated)
- `type`: фильтр по типу (fire, flood, intrusion, equipment_fault, other)
- `since`: ISO 8601, открыт начиная с этой даты (опционально)

Возвращает: список IncidentOut (без evidence).

**`get_incident(incident_id: str) → dict | None`**

Получить один инцидент с полным evidence.

Параметры:
- `incident_id`: ID инцидента (UUID)

Возвращает: IncidentOut с массивом evidence или None.

**`create_incident(type: str, severity: str, location: dict, summary: str, evidence: list[dict] | None) → dict`**

Создать новый инцидент (гипотезу).

Параметры:
- `type`: тип инцидента (fire, flood, intrusion, equipment_fault, other)
- `severity`: серьёзность (low, medium, high, critical)
- `location`: dict с building/floor/zone/lat/lon
- `summary`: описание
- `evidence`: опциональный список {device_id, reading_id, note} для начальной привязки

Возвращает: созданный IncidentOut.

**`update_incident(incident_id: str, status: str | None, severity: str | None, note: str | None) → dict`**

Обновить статус/серьёзность инцидента или добавить note.

Параметры:
- `incident_id`: UUID инцидента
- `status`: новый статус (open, acknowledged, resolved, escalated), опционально
- `severity`: новая серьёзность (low, medium, high, critical), опционально
- `note`: текст note для добавления в metadata, опционально

Возвращает: обновленный IncidentOut.

**`link_evidence(incident_id: str, device_id: str | None, reading_id: int | None, note: str | None) → dict`**

Привязать evidence (показание устройства и/или примечание) к существующему инциденту.

Параметры:
- `incident_id`: UUID инцидента
- `device_id`: UUID устройства (опционально)
- `reading_id`: ID показания (опционально)
- `note`: текстовое примечание (опционально)

Возвращает: обновленный IncidentOut с добавленным evidence.

---

#### Дашборды

**`list_dashboards() → list[dict]`**

Список всех dashboard specs.

Параметров нет.

Возвращает:
```json
[
  {
    "id": "cccccccc-dddd-eeee-ffff-000000000000",
    "title": "Warehouse A Monitoring",
    "created_by": "agent",
    "spec": {"layout": "grid", "widgets": [...]},
    "version": 2,
    "created_at": "2026-09-12T09:00:00Z",
    "updated_at": "2026-09-12T10:15:00Z"
  }
]
```

**`get_dashboard(dashboard_id: str) → dict | None`**

Получить один dashboard по ID.

Параметры:
- `dashboard_id`: UUID дашборда

Возвращает: DashboardOut или None.

**`create_dashboard(title: str, spec: dict, created_by: str = "agent") → dict`**

Создать новый dashboard spec.

Параметры:
- `title`: название
- `spec`: произвольный dict с layout/widgets/etc
- `created_by`: источник (agent, operator, default); по умолчанию "agent"

Возвращает: созданный DashboardOut (version = 1).

**`update_dashboard(dashboard_id: str, title: str | None, spec: dict | None) → dict`**

Обновить dashboard (title и/или spec), увеличив version.

Параметры:
- `dashboard_id`: UUID дашборда
- `title`: новое название (опционально)
- `spec`: новый spec (опционально)

Возвращает: обновленный DashboardOut с incremented version.

---

### Конфигурация окружения

Переменные из `.env`:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/platform
REDIS_URL=redis://localhost:6379/0
API_KEY=dev-secret-change-me  # используется как X-API-Key для всех запросов
```

Значения по умолчанию см. в `app/core/config.py`.

**Тесты используют отдельную БД.** `pytest` никогда не читает и не пишет в базу из
`DATABASE_URL` выше — `tests/conftest.py` перед стартом сессии сам создаёт (если её ещё
нет) отдельную базу на том же Postgres (по умолчанию `<имя_базы>_test`, т.е.
`platform_test`), прогоняет в неё `alembic upgrade head` и направляет туда всё
приложение на время тестов. Переопределить путь можно через `TEST_DATABASE_URL` в
`.env` (см. `.env.example`) — обычно не нужно.

---

## Запуск (локально, для разработки)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db redis
alembic upgrade head
uvicorn app.main:app --reload
```

Полный стек в контейнерах: `docker compose up --build`.

Примечание: хост-порт Postgres в `docker-compose.yml` — `5433` (внутри docker-сети всё ещё `db:5432`),
т.к. `5432` на машине уже занят другим локальным проектом. `.env` для локальной разработки уже
настроен на `localhost:5433`.

---

## Мост к живому State Machine (адаптер)

`app/adapter/` — отдельный, независимый от FastAPI процесс: подключается по SSE к
реальному, уже развёрнутому "State Machine API" команды симулятора
(`https://api.aitinkerers.space/api/v1`, контракт — пакет
`raw-source/fire-safety-state-api-v0.2.2/` в корне репозитория) и перекладывает события
в НАШ ЖЕ `POST /ingest/telemetry` — так же, как это делает curl или любой другой клиент
ingestion API. Остальная платформа (REST/SSE, MCP, все три потребляющие команды) не
меняется и не знает, что данные теперь настоящие, а не curl-симулированные.

Что делает мост:

1. Один раз создаёт (или переиспользует после рестарта — см. ниже) один State Machine
   `run` для выбранного `scenario_id` и открывает его SSE-поток.
2. Отправляет команду `play`.
3. На каждое релевантное SSE-событие строит `TelemetryIn`-совместимый JSON и постит его
   в `{OUR_API_BASE_URL}/ingest/telemetry` с нашим же `X-API-Key`.
4. Переподключается при обрыве (`Last-Event-ID`), обрабатывает `stream.reset` (новое
   поколение — переподключение без курсора, свежий snapshot) и `410 CURSOR_EXPIRED`
   (тоже без курсора), делает backoff 1/2/4/8/15 сек + jitter на прочих ошибках,
   не пытается бесконечно повторять при `401`/`403`.
5. Хранит `run_id`/`generation`/`cursor` в локальном JSON-файле
   `.state_machine_bridge_state.json` (в `.gitignore`) — рестарт процесса продолжает тот
   же run с той же позиции, а не создаёт новый run каждый раз.

### Что смаппено, что пропущено

| Kind (SSE `event.kind` / `Observation.kind`) | Что делаем |
|---|---|
| `observation.created` → `measurement` | → `TelemetryIn` (metric_type по таблице: temperature/obscuration/co/eco2 как есть, smoke_detected → `smoke`, прочее → `other`) |
| `observation.created` → `camera` | → `TelemetryIn` metric_type=`video_event`, метаданные клипа в `payload` (само видео не скачивается) |
| `observation.created` → `access` | → `TelemetryIn` metric_type=`access` |
| `observation.created` → `people_count` | → `TelemetryIn` metric_type=`occupancy` |
| `observation.created` → `connectivity` | → `TelemetryIn` metric_type=`system`, `availability=fresh/disconnected` |
| `observation.created` → `radio_transcript` | → `TelemetryIn` metric_type=`radio_audio`, `transcript` заполнен, `audio_url=null` (см. ниже) |
| `observation.created` → `radio_audio` | **Пропускается** — это метаданные сырого аудиочанка (media_id/timing) без текста; без скачивания аудио сохранять нечего сверх того, что уже несёт `radio_transcript` |
| `device.updated` | **Не форвардится** как отдельная запись (это производная сводка уже отправленных показаний — повторная отправка задублировала бы `TelemetryReading`); используется только для обогащения `DeviceIn` (тип/имя/комната) следующих показаний этого устройства |
| `run.updated`, `room.updated`, `camera.updated`, `access.updated`, `occupancy.updated`, `radio.channel.updated`, `system.updated`, `stream.reset` | Пропускаются как sessions-уровневое состояние, не сырое наблюдение (`stream.reset` мост обрабатывает отдельно — как барьер поколения) |

Устройства из этого источника получают `external_id` с префиксом `sm-` (например,
`RADIO-A` → `sm-RADIO-A`), чтобы не пересекаться с curl/MCP-симулированными устройствами.

**Непрерывное аудио/видео (`/media-streams`) в этой версии не реализовано** — это
осознанно отложено. `audio_url` остаётся `null` даже для радио-расшифровок; заполнен
только `transcript` (и `audio_duration_ms`, вычисленная из длительности реплики).

### Настройка

В `.env` (см. `app/core/config.py` для актуальных полей и значений по умолчанию):

```env
STATE_MACHINE_BASE_URL=https://api.aitinkerers.space/api/v1
STATE_MACHINE_BEARER_TOKEN=<из 1Password, vault aitinkerers-hack, item "State Machine API">
STATE_MACHINE_SCENARIO_ID=degraded
# или palisades-focus / palisades-full — для демо с радио-расшифровкой (см. PALISADES.md)
OUR_API_BASE_URL=http://localhost:8000
```

Токен **никогда** не хардкодится и не появляется в коде/логах/коммитах — только через
переменную окружения; реальное значение берётся из 1Password самостоятельно.

### Запуск

Наш API должен быть поднят (`uvicorn app.main:app`), затем в отдельном терминале:

```bash
python -m app.adapter.bridge
```

Это долгоживущий процесс (не часть FastAPI/request lifecycle) — держите его запущенным,
пока нужен поток живых данных.

---

## Деплой

### Для запуска CORE платформы (REST/SSE/MCP API, ingestion) — минимальная требуемая подготовка

**Новый участник может запустить полностью рабочую базовую платформу с чистого клона:**

1. `cp .env.example .env` — готово, больше ничего менять не нужно. По умолчанию:
   - `API_KEY=dev-secret-change-me` (может быть любой строкой, реальный генерируется при необходимости)
   - `DATABASE_URL` и `REDIS_URL` указывают на интерьерные docker-контейнеры (`db:5432` и `redis:6379`
     внутри docker-сети)
2. `docker compose up --build` поднимает CORE стек:
   - `db` (Postgres) и `redis` с healthcheck'ами
   - `app` (FastAPI backend): дожидается `db` и `redis`, применяет миграции (`alembic upgrade head`),
     поднимает uvicorn на `http://localhost:8000`
3. Проверить: `curl http://localhost:8000/health` должен вернуть `{"status": "ok"}` (этот путь без auth);
   любой другой путь требует `X-API-Key` заголовок.
4. `GET http://localhost:8000/docs` — Swagger UI для live-тестирования всех эндпоинтов.
5. Отправлять тестовую телеметрию через `POST /ingest/telemetry` или `curl` примеры в разделе
   "Для команды симулятора" выше.

**Никаких реальных секретов не требуется** для работы CORE платформы и тестирования всех трёх
интерфейсов (REST, SSE, MCP).

### Для запуска моста к реальному State Machine (опционально)

Если нужны реальные события из симулятора команды:

1. Получите `STATE_MACHINE_BEARER_TOKEN` (из vault aitinkerers-hack, item "State Machine API")
2. Заполните в `.env`: `STATE_MACHINE_BEARER_TOKEN=<value>`
3. `docker compose up --build` также поднимет сервис `bridge` (`app/adapter/bridge.py`), который
   подключится к `https://api.aitinkerers.space`, откроет SSE-поток сценария и будет отправлять
   реальные события в `POST /ingest/telemetry`. Остальная платформа при этом не меняется —
   дашборд и MCP-клиенты видят реальные данные через тот же API.

**Без `STATE_MACHINE_BEARER_TOKEN` сервис `bridge` не стартует**, но CORE платформа работает полностью,
и можно тестировать через curl/примеры с синтетическими данными.

### Дополнительные детали развёртывания

- По умолчанию `docker compose up` подхватывает `docker-compose.override.yml` (bind-mount репо +
  `uvicorn --reload`) — только для локальной разработки. На сервере запускайте
  `docker compose -f docker-compose.yml up --build -d` (без override).
- Вне рамок этого репозитория: выбор хоста, TLS/сертификаты, реверс-прокси, домен, и раздача
  реальных секретов в `.env` на сервере — это организационные/инфраструктурные решения.
