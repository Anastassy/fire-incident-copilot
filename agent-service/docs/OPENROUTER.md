# OpenRouter: Astra и резервная Fable 5.1

Основная модель — `openai/gpt-6-astra`, резервная — `anthropic/claude-fable-5.1`.
Обе поддерживают structured outputs. Запросы используют JSON Schema, низкий
reasoning effort и `provider.require_parameters=true`. OpenAI Agents SDK tracing
для OpenRouter отключён; ключ остаётся в серверном процессе.

## Запуск с 1Password

Из `agent-service/`:

```sh
uv sync --frozen
cp .env.openrouter.example .env
# В .env заменить YOUR_VAULT на имя доступного хранилища.
op run --env-file=.env -- .venv/bin/python -m uvicorn \
  fire_agents.api:create_app --factory --host 127.0.0.1 --port 8012
```

1Password CLI должен быть авторизован. При использовании service account его
токен передаётся через `OP_SERVICE_ACCOUNT_TOKEN`, без записи в репозиторий.
Ссылка на запись `OpenRouter API Key - demo`, поле `credential`, разрешается
командой `op run`. `.env` исключён из Git; готовый ключ туда копировать не нужно.

Для другого secret manager достаточно задать `OPENROUTER_API_KEY` в окружении.
Другой файл БД выбирается через `FIRE_DB_PATH`; существующую БД не удалять.

`/health` сообщает `SDKEngine`, provider и точные ID моделей. Дашборд показывает
их в Copilot и настройках. Адрес сервиса передаётся gateway через
`--agent-url http://127.0.0.1:8012`; `--agent-context`, `--agent-generation` и
`--subject` должны соответствовать созданному контексту агента. Для SDK запускать
gateway без `--demo-agent`. OpenRouter не подключает State API к агенту автоматически:
импорт источников и часы контекста настраиваются отдельно через Data Platform.

## Поведение fallback

На запрос выделено 28 секунд внутри 30-секундного бюджета UI. При настроенной
резервной модели каждая попытка ограничена 14 секундами. Вторая модель получает
те же входные данные, инструкции и схему ответа. Повтор срабатывает после ошибки
API/сети, таймаута, превышения числа ходов SDK или невалидного structured output.
Успешная Astra и отмена запроса не запускают Fable. Ошибка обеих моделей остаётся
ошибкой: тестовый ответ вместо неё не подставляется. Ненастроенный или совпадающий
с основной fallback отключает вторую попытку.

## Проверено 12 сентября 2026

- Ключ из 1Password прошёл авторизованную проверку OpenRouter.
- Живой ответ Astra на два явно синтетических сообщения: 3,67 секунды,
  валидная схема и ссылки только на переданные evidence IDs.
- При контролируемой локальной транспортной ошибке основной попытки реальный
  запрос к Fable 5.1 успешно завершился за 7,34 секунды. Это проверка пути fallback,
  а не наблюдение реального сбоя Astra.
- В локальном дашборде подключён SDKEngine на порту 8012 с отдельной БД
  `work/openrouter-ui.sqlite3` и контекстом `dashboard-openrouter-demo`, generation 0,
  subject `all`. Три явно синтетических сообщения без fixture-аннотаций прошли
  настоящую экстракцию: request → assignment → acknowledgement. Вопрос из браузера
  вернул английский ответ с проверяемыми источниками и ограничениями. Локальные
  demo reading IDs не являются ID записей Data Platform. БД прежнего FixtureEngine
  сохранена; State run и медиапотоки не перезапускались.
- 59 тестов agent-service и 9 тестов dashboard/gateway прошли. Проверяются
  отмена, timeout, validation, обе ошибки, отсутствие лишнего fallback и защита
  секретов в health/config. Фактическая задержка провайдеров может меняться.

Каталог моделей: [OpenRouter](https://openrouter.ai/api/v1/models).
Параметры: [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs),
[model fallback](https://openrouter.ai/docs/guides/routing/model-fallbacks).
Здесь fallback реализован в SDKEngine, чтобы реагировать также на локальные
ошибки валидации и ограничивать общий таймаут.
