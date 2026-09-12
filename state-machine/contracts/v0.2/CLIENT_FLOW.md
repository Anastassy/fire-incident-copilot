# Короткая инструкция для команды интерфейса

Это интеграционная схема v0.2 для сырого `/api/v1`: State Machine → внешний потребитель.
Распознавание речи/изображений и аналитика выполняются в другом проекте.
Сервис работает по отдельному базовому URL; реквизиты находятся в инструкции подключения.
Для разработки без сервера используйте `examples/`.
Медиа-URL в фикстурах не загружаются.

## Первое подключение

1. Прочитать capabilities и scenarios; скрыть неподдерживаемые функции.
2. Создать run с Idempotency-Key. Сохранить run_id/generation и ссылки.
3. Открыть SSE с Bearer через fetch и стандартный SSE-парсер. Без cursor придёт snapshot.
4. Полностью заменить store данными snapshot. Сохранить as_of.sequence/cursor.
5. Кнопка Play отправляет отдельный command_id и expected_generation. Состояние кнопки
   окончательно синхронизируется через stream; HTTP-ответ не откатывает свежие события.
6. Обновлять объекты по ID, историю — по evidence_id.
7. Один раз получить media-streams и открыть content_url нужных камер/радиоканалов.
   Дальнейшие bytes приходят по тем же соединениям; по каждому фрагменту запрос не нужен.

## Обработчик событий — псевдокод

```text
onSnapshot(snapshot):
    reject if snapshot.run.run_id != selected_run_id
    atomically replace state
    generation = snapshot.run.generation
    sequence = snapshot.as_of.sequence
    cursor = snapshot.as_of.cursor

onEvent(event):
    reject if event.run_id != selected_run_id
    ignore if event.sequence <= sequence
    if event.kind == "stream.reset" or event.generation != generation:
        abort old requests and stop media players
        reconnect without cursor to receive a new atomic snapshot
        return
    if event.sequence != sequence + 1:
        reconnect after current cursor; if 410, reload snapshot
        return
    apply complete payload according to kind
    update displayed simulation clock from event.sim_time_ms
    commit sequence and cursor only after successful application

onHeartbeat(heartbeat):
    reject if heartbeat.run_id != selected_run_id
    if heartbeat.generation != generation:
        reconnect without cursor to receive a new atomic snapshot
        return
    update connection timer and displayed simulation clock
    do not advance the event cursor
```

Нельзя использовать один JSON.parse на каждый TCP chunk: chunk может содержать
половину UTF-8 символа, несколько SSE-сообщений или часть строки `data:`.
Парсер должен обрабатывать границы строк/пустую строку, CRLF/LF, несколько data-строк,
комментарии, event/id/retry. Подойдёт проверенная библиотека SSE для fetch.

## Поля для первого экрана

| Элемент UI | Где брать |
|---|---|
| Время, Play/Pause, скорость | snapshot.run / run.updated; часы также event.sim_time_ms и heartbeat |
| Карточки датчиков | snapshot.devices / device.updated |
| Графики | observations?device_id=…&generation=…; новые точки observation.created |
| Камеры | media-streams → один непрерывный content_url на камеру; camera.updated для состояния |
| СКУД | access + observation.kind=access |
| Число людей | occupancy со scope_type=building: прямое значение источника; null — «неизвестно» |
| Аудио | media-streams → один непрерывный content_url на радиоканал |
| Техническая связь | heartbeat таймер + system.updated |

Состояние reducer — ключ `(run_id, generation, entity_id)`. Media, графики и результаты
fetch прошлого поколения игнорируются. Snapshot/history не смешиваются: история
добавляет точки, а не подменяет текущие показания.

## Вымышленная демонстрация из пакета

Загрузите `snapshot.initial.json`, затем по порядку `events.json`, ориентируясь на
sim_time_ms. В конце получится `snapshot.after-play.json`:

- исходные значения: температура 42.2 degC, obscuration 11.017 %/ft;
- приходит 2-секундный video clip и audio chunk;
- пропуск получает разрешение, но число людей остаётся неизвестным;
- датчик дыма теряет связь, последнее значение остаётся с пометкой disconnected;
- replay останавливается на 4000 мс.

Все значения, тексты, ссылки и хеши фикстур синтетические. `event.reset.json` — отдельный
пример барьера generation=1. `stream.sse` содержит реальный текстовый wire-format,
включая snapshot, события, heartbeat и retry. Этот файл можно отдавать mock-сервером;
его наличие не означает, что production SSE уже реализован.

## Что передать команде backend перед подключением

Origin интерфейса для CORS, согласованный base URL, способ выдачи application token,
нужный scenario_id. Остальные пути/тела уже описаны в OpenAPI.
До этого UI можно разрабатывать по пакетным JSON/SSE и своим локальным заглушкам.

## Подключение внешнего распознавания

Второй слой подписывается на SSE **того же run** и открывает отдельные непрерывные
HTTP-потоки из media-streams. SSE сообщает времена/IDs наблюдений, медиа приходит
по открытым бинарным соединениям. GET Media нужен только для выбранного архивного фрагмента.
Для пропущенных/старых фрагментов читает observations с фильтром device_id и generation.
Результаты обработки хранит у себя со ссылками на run_id/generation/evidence_id/media_id;
в State Machine результаты не отправляются. В этом пакете нет API аналитического слоя.

Прямой people_count показан отдельной парой JSON observation.people-count и
occupancy.source-count. Основной SSE-пример не содержит источника подсчёта людей.

## Готовый текст Palisades

Для аудио вместе с расшифровкой выберите palisades-full или palisades-focus.
Из того же SSE отбирайте observation.created с data.kind=radio_transcript.
Полная последовательность и таймкоды — в [PALISADES.md](PALISADES.md).
