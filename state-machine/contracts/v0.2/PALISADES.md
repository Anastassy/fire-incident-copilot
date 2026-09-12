# Palisades: аудио и текст одним replay

Базовый URL: `http://127.0.0.1:8787/api/v1`. Доступ и общая последовательность
подключения — в [CONNECTION.md](CONNECTION.md).

| scenario_id | Аудио | Радиоканал / stream_id | Текст |
|---|---|---|---|
| palisades-full (только внешний полный пакет) | 10 минут | RADIO-PALISADES-FULL | 74 фразы |
| palisades-focus | 3:26 | RADIO-PALISADES-FOCUS | 43 фразы |

Импортёр `scripts/import_repository_radio.py` добавляет только `palisades-focus` из
существующего пакета репозитория. Полный вариант по умолчанию отсутствует.

Короткий вариант соответствует 04:52–08:18 полного. Это два варианта одной записи,
а не независимые радиоканалы. В каждом сценарии также доступны два синтетических
тестовых видео и авторские показания виртуального здания. Их совмещение с Palisades условное.

## Подключение

1. Создать `POST /runs`, передав `Idempotency-Key: <UUID>` и
   `{"scenario_id":"palisades-focus","speed":1}`.
2. Открыть `GET /runs/{run_id}/stream` с Bearer-токеном. Это SSE для состояния и текста.
3. Прочитать `/runs/{run_id}/media-streams`, выбрать RADIO-PALISADES-FOCUS и открыть
   его content_url. Это одно непрерывное соединение с AAC в fragmented MP4.
4. Отправить Play через `/runs/{run_id}/commands`, указав новый command_id,
   expected_generation из Run и `action: "play"`.

SSE-кадры имеют `event: event`. Для текста отбирайте JSON, где
`kind == "observation.created"` и `data.kind == "radio_transcript"`:

```js
if (event.kind === "observation.created" && event.data.kind === "radio_transcript") {
  const observation = event.data;
  const phrase = observation.data;
  // Deduplicate by run_id + generation + evidence_id when reconnecting.
  appendPhrase({
    id: observation.evidence_id,
    text: phrase.text,
    startMs: phrase.audio_start_sim_time_ms,
    endMs: phrase.audio_end_sim_time_ms,
    words: phrase.words
  });
}
```

[Полный пример наблюдения](examples/observation.radio-transcript.json) синтетический;
реальный сервер передаёт неизменённый английский текст выбранного пакета.
RadioChannel.latest_transcript содержит последнее опубликованное наблюдение для
восстановления отображения. Не добавляйте его повторно в журнал при каждом
radio.channel.updated: новые строки приходят через observation.created.

## Время и восстановление

- Фраза публикуется после конца её аудиоинтервала, когда соответствующий fMP4-фрагмент
  уже разрешён к выдаче. Целиком будущий текст до Play не передаётся. Публикация идёт
  по фразам; таймкоды слов приходят вместе с завершённой фразой.
- Сегменты аудио около 2 секунд; дополнительно влияет сеть и буфер плеера. Текст и
  звук используют часы run. Клиент отображает полученные фразы по позиции своего плеера.
- Для новых аудиопотоков `media_timestamp_offset_ms=64`: из временной метки AAC
  вычитается задержка кодера 64 ms, чтобы получить время исходного WAV. Значения
  duration_ms и available_until_sim_time_ms уже используют шкалу исходного аудио.
- Pause прекращает продвижение аудио и текста. Уже накопленный буфер плеер останавливает
  сам по run.updated. Resume продолжает соединения.
- Reset/seek увеличивает generation. Очистите прежнее отображение, получите snapshot,
  подключите аудио нового поколения. SSE остаётся открытым и сообщает stream.reset.
- После потери SSE передайте Last-Event-ID. Для заполнения более раннего текста:
  `/runs/{run_id}/observations?generation=G&device_id=RADIO-PALISADES-FOCUS&limit=500`;
  отберите kind=radio_transcript, пройдите next_cursor, если он задан.
- После конца записи аудио завершается. Полная запись заканчивается на t=600000,
  короткая на t=206000, включая выдачу последнего аудиофрагмента.

## Происхождение текста

`delivery: "prerecorded"`, `machine_generated: true`, `human_verified: false`.
Сервер воспроизводит готовую расшифровку пакета; ASR на сервере не запускается.
Модель исходного текста — mlx-community/whisper-large-v3-turbo-q4. Вероятности слов
являются оценками этой модели, не измеренной точностью. Говорящие не определялись.

Сохраняются исходные слова, таймкоды, SHA-256 аудио и JSON, source_segment_id,
full_recording_offset_ms и provenance. При выходе исходных таймкодов слов за границы сегмента они сохраняются,
а поле timing_notes содержит пояснение.
Исправления текста и смысловая интерпретация не выполняются.

Источник: пакет palisades-radio-demo, Audio Provided by Broadcastify, CC BY 3.0 US.
Импортёр вычисляет SHA-256 входных MP3/JSON и декодирует MP3 в mono 16 kHz WAV.
Это производный файл, не исходный master WAV. Преобразование указано в provenance.
Внешний полный пакет проверяется по его SHA256SUMS. Исходные файлы не меняются.

## Автоматическая проверка

Тесты компонента собирают focus-bundle из файлов репозитория, проверяют все 43 фразы,
их временные границы, скорости 1×/10×/60×, Play/Pause/Reset, SSE reconnect,
восстановление SQLite и выдачу последнего аудиофрагмента на t=206000.
Клиентский браузерный плеер остаётся частью внешнего интерфейса.
