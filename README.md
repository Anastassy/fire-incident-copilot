# Safety Telemetry Platform

Backend-платформа для хакатона: приём телеметрии с сенсоров (CCTV/IoT/пожарные панели/alarm-системы),
хранение и два независимых интерфейса доступа к данным:

- **REST + WS/SSE** (`/devices`, `/telemetry`, `/incidents`, `/dashboards`, `/stream/*`) — для
  автономного дашборд-приложения.
- **MCP** (`app/mcp/server.py`) — для агентной системы: чтение телеметрии/инцидентов, запись
  инцидентов (гипотезы) и кастомных dashboard-specs по запросу оператора.

Полная архитектура и разбивка ответственности — см. план в `/Users/vitalynec/.claude/plans/swirling-meandering-aho.md`.

## Контракт приёма данных (для команды симулятора)

`POST /ingest/telemetry` принимает один объект или список объектов:

```json
{
  "device": {
    "external_id": "cam-12",
    "type": "cctv",
    "name": "Camera warehouse A-2",
    "location": {"building": "A", "floor": 2, "zone": "warehouse"}
  },
  "metric_type": "video_event",
  "ts": "2026-09-12T10:00:00Z",
  "value": null,
  "unit": null,
  "payload": {"event": "smoke_detected", "confidence": 0.87}
}
```

- `device.type`: `cctv | iot | fire_panel | alarm | water_sensor | other`
- `metric_type`: `temperature | smoke | water_level | motion | video_event | heartbeat | other`
- `value`/`unit` — для скалярных метрик (температура, уровень воды); `payload` — для произвольных
  структурированных данных (детекции, статусы, кадры).
- Устройство авто-регистрируется/апсертится по `external_id` при первом событии.
- Альтернатива HTTP — `WS /ingest/stream`: тот же payload построчно, для постоянного соединения.

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
