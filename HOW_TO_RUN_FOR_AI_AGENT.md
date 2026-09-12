# How to run locally — instructions for an AI agent

Дополнение после хакатона: этот файл документирует запуск уже опубликованного кода.
Он не заменяет реализацию и не требует изменений других файлов репозитория.

**Цель:** собственные State API → PostgreSQL/Redis Platform → agent → dashboard,
радио с готовой расшифровкой и тестовые камеры. Без Hetzner, Cloudflare, 1Password,
`api.aitinkerers.space`, `platform.aitinkerers.space` и ключей команды.
После установки зависимостей базовый режим работает без интернета. Настоящий
анализ можно включить через локальную модель; он описан отдельно от FixtureEngine.

## 0. Границы воспроизведения

- Ветка `main` содержит dashboard/agent/platform. State API опубликован отдельно
  в **этом же публичном репозитории**, ветка `feat/state-machine-api`, каталог
  `state-machine/`. Нужны две отдельные копии; сливать ветки не требуется.
- Проверяемые версии: приложение `c9bb44ddfde275aa6b6eb455ef4e78e1f7fc05dc`,
  State `d8000b02193a1ffc4bd28a543daeb0099cbed4f5`. Это фиксация существующего кода,
  а не новая реализация после завершения события.
- Сценарий **`palisades-focus`**: 206 секунд опубликованного в Git радио, 43 готовых
  машинных транскрипции, авторские датчики и СКУД, две цветные видеозаглушки по
  6 секунд. MP3 декодируется локально; новое ASR не запускается.
- Это не точная копия Base2 из конкурсного фильма: восемь сгенерированных CCTV и
  его полный серверный bundle отсутствуют в публичной поставке. Не подставляйте
  название `base2-palisades-v1`: такой сценарий эта локальная сборка не создаёт.
- Цветные камеры проверяют транспорт/декодирование, а не распознавание дыма.
  На 6-й секунде они заканчиваются. Радио заканчивается на 206-й; зацикливания нет.
  Синтетические показания и историческое радио не относятся к одному происшествию.
- Существующий UI для не-Base2 камер использует подпись `RECORDED CCTV`, а некоторые
  кнопки/футер сохраняют Base2-названия. **Здесь камеры синтетические**; проверяйте
  provenance. Этот документ не исправляет и не скрывает особенности старого UI.
- FixtureEngine возвращает выбранные описания источников, не понимает радио и не
  создаёт из исторического текста смысловые channel checks. Это проверка всей
  доставки и интерфейса. Для модельных выводов нужен раздел 7.

## 1. Подготовить инструменты и отдельный рабочий каталог

Нужны Bash, Git, Python 3.12+, uv, Node.js 18+/npm, FFmpeg с `libx264` и AAC,
PostgreSQL (`initdb`, `pg_ctl`, `createdb`, `psql`) и `redis-server`/`redis-cli`.
Docker не требуется. Проверка проведена на macOS с PostgreSQL 14.17 и Redis 8.10.1;
не запускайте системные сервисы БД и не используйте базы других проектов.

Если инструментов нет, установите их обычным пакетным менеджером. Например, macOS:
`brew install python@3.12 uv node ffmpeg postgresql@16 redis`, затем добавьте
`$(brew --prefix postgresql@16)/bin` в PATH. На Linux нужны аналогичные пакеты;
`initdb` часто расположен в `/usr/lib/postgresql/<version>/bin`.
Команды `initdb` выполняются обычным пользователем, не root.
Установка пакетов/клонирование требуют интернета; рабочий replay — нет.

Откройте **Bash** и выполните блок. Путь должен быть новым, без пробелов, вне текущего checkout.
Можно задать свой `FIREWATCH_HOME` перед блоком. Все последующие блоки подготовки
выполняются в этой же оболочке; для других терминалов будет создан `env.sh`.

```bash
set -euo pipefail
export FIREWATCH_HOME="${FIREWATCH_HOME:-$HOME/firewatch-local-reproduction}"
test ! -e "$FIREWATCH_HOME" || { echo 'Choose a new FIREWATCH_HOME; existing data is preserved.'; exit 1; }
mkdir -p "$FIREWATCH_HOME/runtime" "$FIREWATCH_HOME/cache"
export UV_CACHE_DIR="$FIREWATCH_HOME/cache/uv"
export APP="$FIREWATCH_HOME/app"
export STATE_SOURCE="$FIREWATCH_HOME/state-source/state-machine"
export RUN="$FIREWATCH_HOME/runtime"

git clone --branch main --single-branch https://github.com/Anastassy/fire-incident-copilot.git "$APP"
git -C "$APP" checkout --detach c9bb44ddfde275aa6b6eb455ef4e78e1f7fc05dc
git clone --branch feat/state-machine-api --single-branch https://github.com/Anastassy/fire-incident-copilot.git "$FIREWATCH_HOME/state-source"
git -C "$FIREWATCH_HOME/state-source" checkout --detach d8000b02193a1ffc4bd28a543daeb0099cbed4f5
uv sync --project "$APP/agent-service" --locked
uv venv --python 3.12 "$FIREWATCH_HOME/platform-venv"
uv pip install --python "$FIREWATCH_HOME/platform-venv/bin/python" -r "$APP/platform/requirements.txt"
mkdir -p "$RUN/private" "$RUN/logs" "$RUN/redis" "$RUN/guard"
chmod 700 "$RUN/private"
```

Зависимости агента зафиксированы `uv.lock`; requirements платформы в исходном коде
не зафиксированы по версиям. В случае будущей несовместимости смотрите раздел 9,
не переписывайте код/lock-файлы. `.venv` появляется только в отдельном клоне;
данные/служебные файлы ниже находятся в его соседнем `runtime/`.

## 2. Собрать локальный State bundle и собственные ключи

```bash
cd "$STATE_SOURCE"
"$APP/agent-service/.venv/bin/python" scripts/build_demo_bundle.py --output "$RUN/demo-bundle"
"$APP/agent-service/.venv/bin/python" scripts/import_repository_radio.py \
  --base "$RUN/demo-bundle" --output "$RUN/palisades-bundle" \
  --package "$APP/data/demo/palisades-radio-demo"
"$APP/agent-service/.venv/bin/python" scripts/setup_local.py \
  --output "$RUN/private" --public-url http://127.0.0.1:18765/api/v1
```

Ожидается `scenario_id=palisades-focus`, `duration_ms=206000`,
`transcript_segments=43`. `setup_local.py` создаёт новые локальные read/control
токены в `client.json`, серверные хэши в `server.json`; токены команды не нужны.
Они действуют 30 дней. Повторный запуск сохраняет существующие ключи.
Bundle неизменяем: повторная сборка в существующий каталог намеренно завершается
ошибкой. Для другой версии выберите новый каталог, не удаляйте чужие данные.

## 3. Общая конфигурация и запрет внешних Python-соединений

Этот блок создаёт только служебные файлы **вне checkout**. `sitecustomize.py`
устанавливает audit hook: runtime Python-процессы могут обращаться только к
loopback. Это проверочный ограничитель запуска, не изменение приложения и не
системный firewall. Установка зависимостей выполнялась до его включения.

```bash
cat > "$RUN/guard/sitecustomize.py" <<'PY'
import ipaddress
import os
import sys

def local_only(event, args):
    if event == 'socket.connect':
        address = args[1]
        if not isinstance(address, tuple):
            return
        host = address[0]
    elif event == 'socket.getaddrinfo':
        host = args[0]
    else:
        return
    if isinstance(host, bytes):
        host = host.decode('ascii')
    allowed = host in ('localhost', None, '')
    if not allowed:
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
    if not allowed:
        with open(os.environ['FIREWATCH_NETWORK_LOG'], 'a') as log:
            log.write(event + ' BLOCKED ' + str(host) + '\n')
        raise RuntimeError('External networking is disabled: ' + str(host))

sys.addaudithook(local_only)
PY

python3 - <<'PY'
from pathlib import Path
import json, os, shlex
root=Path(os.environ['FIREWATCH_HOME']).resolve()
r=root/'runtime'
exports={
 'FIREWATCH_HOME':str(root), 'APP':str(root/'app'),
 'STATE_SOURCE':str(root/'state-source/state-machine'), 'RUN':str(r),
 'UV_CACHE_DIR':str(root/'cache/uv'),
 'PYTHONPATH':str(r/'guard'),
 'FIREWATCH_NETWORK_LOG':str(r/'logs/network.log'),
 'DATABASE_URL':'postgresql+asyncpg://firewatch@127.0.0.1:15439/firewatch',
 'REDIS_URL':'redis://127.0.0.1:16379/0', 'API_KEY':'local-demo-only',
 'STATE_MACHINE_BASE_URL':'http://127.0.0.1:18765/api/v1',
 'OPENAI_AGENTS_DISABLE_TRACING':'1', 'NO_PROXY':'127.0.0.1,localhost,::1',
 'FIRE_ENGINE':'fixture', 'FIRE_EVENT_WORKERS':'1',
 'FIRE_DB_PATH':str(r/'private/agent.sqlite3'),
}
# Bash: remove inherited provider, production, proxy and Python settings first.
reset="""while IFS= read -r name; do
  case "$name" in FIRE_*|STATE_*|PLATFORM_*|OPENAI_*|OPENROUTER_*|PYTHONPATH|HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|http_proxy|https_proxy|all_proxy) unset "$name" ;; esac
done < <(compgen -e)
"""
(r/'env.sh').write_text(reset+''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in exports.items()))
(r/'private/platform.json').write_text(json.dumps({'base_url':'http://127.0.0.1:18800','api_key':'local-demo-only'}))
os.chmod(r/'private/platform.json',0o600)
print('Source this in each terminal:',r/'env.sh')
PY
source "$RUN/env.sh"

"$APP/agent-service/.venv/bin/python" - <<'PY'
import socket
for port in (15439,16379,18765,18800,18812,18790):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1',port))
    print(port,'available')
PY
```

Все шесть портов должны быть свободны. Не освобождайте их через `killall` или
остановку чужих контейнеров. Если порт занят, согласованно выберите другой во
всех URL/командах; State `public_url` тоже должен совпадать с портом сервера.
Проверка порта не резервирует его: при ошибке bind позже проверьте владельца.

## 4. Поднять собственные PostgreSQL и Redis

В терминале подготовки:

```bash
initdb -D "$RUN/postgres" -U firewatch --auth=trust --encoding=UTF8 --locale=C
pg_ctl -D "$RUN/postgres" -l "$RUN/logs/postgres.log" \
  -o "-h 127.0.0.1 -p 15439 -k $RUN/private" start
createdb -h 127.0.0.1 -p 15439 -U firewatch firewatch
cd "$APP/platform"
"$FIREWATCH_HOME/platform-venv/bin/python" -m alembic upgrade head
```

Это отдельный учебный кластер с loopback-привязкой и локальным `trust`; он доступен
процессам на этой машине и не предназначен для общего сервера. Он не использует
системный PostgreSQL, пароль команды или рабочие таблицы. Файл `postmaster.pid`
не удалять вручную. При обычном повторном запуске пропустите `initdb`/`createdb`;
используйте тот же `pg_ctl start` и миграции.

Откройте **терминал Redis**, задайте путь к созданному `env.sh` и держите процесс:

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
redis-server --bind 127.0.0.1 --port 16379 --dir "$RUN/redis" --save '' --appendonly no
```

Если выбрали другой `FIREWATCH_HOME`, замените путь в строке `source` во всех
новых терминалах. Redis здесь — временный pub/sub; телеметрия хранится в PostgreSQL.

## 5. Четыре процесса приложения

В каждом терминале сначала загрузите тот же `env.sh`. Ни `run_local.py`, ни
`platform` bridge, ни `FIRE_PLATFORM_SCOPE` для этого режима не нужны:
**единственный importer — dashboard gateway**.

**Терминал State:**

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$STATE_SOURCE"
"$APP/agent-service/.venv/bin/python" -m state_api \
  --bundle "$RUN/palisades-bundle" --database "$RUN/private/state.sqlite" \
  --config "$RUN/private/server.json" --host 127.0.0.1 --port 18765
```

**Терминал Platform:**

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$APP/platform"
"$FIREWATCH_HOME/platform-venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 18800
```

**Терминал agent, сначала воспроизводимый режим без модели:**

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$APP/agent-service"
"$APP/agent-service/.venv/bin/python" -m uvicorn fire_agents.api:create_app \
  --factory --host 127.0.0.1 --port 18812
```

**Терминал gateway:**

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$APP"
"$APP/agent-service/.venv/bin/python" dashboard/live/server.py --port 18790 \
  --scenario palisades-focus --state-config "$RUN/private/client.json" \
  --platform-config "$RUN/private/platform.json" --agent-url http://127.0.0.1:18812 \
  --live-pipeline --analysis-interval 3 --pipeline-work-dir "$RUN/pipeline"
```

Откройте **http://127.0.0.1:18790/**. Dashboard создаст собственный paused run и
добавит его UUID в URL. Это локальный UUID; не копируйте UUID конкурсного сервера.
Сохраните URL, чтобы продолжить тот же replay после перезагрузки.
Сначала дождитесь startup complete в терминалах. Если страница открылась раньше
агента, после успешных health-проверок обновите её: старый статус `Disconnected`
может остаться на бейдже даже при работающем pipeline.

## 6. Проверить, что работает вся цепочка

В терминале подготовки:

```bash
curl --fail --silent http://127.0.0.1:18765/api/v1/health
curl --fail --silent http://127.0.0.1:18800/health
curl --fail --silent http://127.0.0.1:18812/health
curl --fail --silent http://127.0.0.1:18790/api/config
curl --fail --silent http://127.0.0.1:18790/api/pipeline/status
redis-cli -h 127.0.0.1 -p 16379 ping
```

Ожидается: пять HTTP 200, `FixtureEngine`, `demo_agent=false`,
`pipeline_enabled=true`, все URL с `127.0.0.1`. После открытия UI pipeline должен
иметь импортированные записи. `platform_connected=false` в health агента означает
выключенный отдельный poller, а не сбой gateway-owned импорта.

В браузере:

1. На паузе видны первые три датчика; будущее радио ещё не опубликовано.
2. Нажмите **Sound off**, чтобы включить звук, затем **Play** при **1×**.
3. Две цветные камеры проигрывают 0–6 секунд. Затем камера остаётся без новых кадров:
   это конец тестового файла, не ошибка сети.
4. Радио продолжает играть; первая транскрипция появляется после соответствующей
   реплики, приблизительно к 00:11. `Radio traffic` и `Event feed` пополняются.
5. Нажмите **Pause**: часы и аудио останавливаются. Спросите
   `What do the latest sensor readings and radio reports say?` через **Ask Copilot**.
   В режиме Fixture ответ перечисляет источники и явно говорит, что смыслового
   анализа нет. Нажмите **Source** и проверьте ID/исходное описание.
6. Снова **Play**. Для быстрой проверки конца можно выбрать 60×: ожидается 43
   транскрипции и конец 03:26. Для прослушивания используйте 1×.
7. **Reset** увеличивает generation и очищает показ предыдущего контекста.
   Старые записи БД сохраняются; новый импорт не должен использовать старые ответы.

Телеметрия должна присутствовать в собственной БД:

```bash
psql -h 127.0.0.1 -p 15439 -U firewatch -d firewatch \
  -c 'SELECT count(*) AS stored_readings FROM telemetry_readings;'
cd "$APP"
npm run verify
```

`npm run verify` — отдельные 112 offline-тестов и проверки mock adapters, не
подмена live-проверки выше. Ненулевой счётчик БД подтверждает сохранение, не точность
интерпретации. Проверьте, что в `$RUN/logs/network.log` нет строк `BLOCKED`;
если файл не создан, запрещённых Python-соединений не было. Это не аудит трафика
всей машины: браузер и нативные БД имеют собственные процессы. В существующем CSS
есть Google Fonts import; браузер может обращаться за шрифтами к Google. Для
отключённого интернета предусмотрены системные fallback fonts. К серверной
доставке источников это отношения не имеет; CSS по этой инструкции не меняется.

## 7. Настоящий локальный LLM без внешнего API

Базовый стек выше не требует LLM. Для реального SDK анализа нужен локальный
OpenAI-compatible сервер. Проверен **LM Studio**, `http://127.0.0.1:1234/v1`,
**`google/gemma-4-e2b`**, context length **32768**.

На новой машине установите LM Studio, найдите и скачайте эту модель, загрузите её
с контекстом 32768, затем включите **Start server** во вкладке **Developer** на
порту 1234. См. [скачивание модели](https://lmstudio.ai/docs/app/basics/download-model)
и [запуск сервера](https://lmstudio.ai/docs/developer/core/server).
Используйте loopback, без публикации сервера в сеть. В проверке веса уже были
скачаны, их загрузка с нуля не проверялась. Нужны память и вычислительные ресурсы
под выбранную модель. Не выгружайте чужую работающую модель и не меняйте настройки
других проектов. После скачивания inference не требует интернета.

```bash
curl --fail --silent http://127.0.0.1:1234/v1/models
```

Скопируйте точный model ID. В `FIRE_MODEL` добавляется префикс `openai/` для
маршрутизации **SDK**, например `openai/google/gemma-4-e2b`. SDK удаляет первый
префикс перед запросом. Это не внешний OpenAI: URL ниже остаётся loopback.
`OPENAI_API_KEY=local-only` — заглушка SDK, не реальный ключ.

Поставьте локальный replay на паузу. Остановите **только свои** agent и gateway
через Ctrl+C. State/Platform/Redis/PostgreSQL продолжают работать. Запустите агент
с отдельной SQLite БД, сохранив прежний fixture-контекст:

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$APP/agent-service"
export FIRE_ENGINE=sdk
export FIRE_PROVIDER=openai
export FIRE_MODEL=openai/google/gemma-4-e2b
export FIRE_FALLBACK_MODEL=
export FIRE_OUTPUT_LANGUAGE=en
export FIRE_EVENT_WORKERS=1
export FIRE_DB_PATH="$RUN/private/agent-e2b.sqlite3"
export OPENAI_BASE_URL=http://127.0.0.1:1234/v1
export OPENAI_API_KEY=local-only
export OPENAI_AGENTS_DISABLE_TRACING=1
"$APP/agent-service/.venv/bin/python" - <<'PYMODEL'
import json
import os
from agents import ModelSettings, set_default_openai_api, set_default_openai_client
from openai import AsyncOpenAI
from openai.types.shared import Reasoning
from fire_agents.api import create_app
from fire_agents.engines import SDKEngine
from fire_agents.models import Extraction

set_default_openai_api('responses')
set_default_openai_client(AsyncOpenAI(
    base_url=os.environ['OPENAI_BASE_URL'], api_key='local-only',
    max_retries=0, timeout=28,
), use_for_tracing=False)
engine=SDKEngine(os.environ['FIRE_MODEL'])
settings=ModelSettings(max_tokens=400, temperature=0,
                       reasoning=Reasoning(effort='none'))
engine.extractor.model_settings=settings
engine.responder.model_settings=settings
engine.responder.instructions += (
    ' Return ONLY a valid JSON object with keys claims and limitations.'
    ' claims is an array of objects, each with text (string) and evidence_ids'
    ' (array of input event ID strings). limitations is an array of strings.'
    ' No Markdown or surrounding commentary.'
)
engine.extractor.instructions += (
    ' Return ONLY valid JSON matching this schema, without Markdown: '
    + json.dumps(Extraction.model_json_schema())
)
import uvicorn
uvicorn.run(create_app(engine=engine), host='127.0.0.1', port=18812)
PYMODEL
```

Это конфигурация SDK Agent через существующий `create_app(engine=...)`,
без изменения исходников, методов классов или глобальных настроек LM Studio.
Добавленные инструкции требуют уже существующие JSON-контракты; содержание
доказательств и алгоритм их выборки не меняются. Таймаут приложения остаётся 28 с.

Gateway запускается с **новым journal**, соответствующим новой БД агента:

```bash
source "$HOME/firewatch-local-reproduction/runtime/env.sh"
cd "$APP"
"$APP/agent-service/.venv/bin/python" dashboard/live/server.py --port 18790 \
  --scenario palisades-focus --state-config "$RUN/private/client.json" \
  --platform-config "$RUN/private/platform.json" --agent-url http://127.0.0.1:18812 \
  --live-pipeline --analysis-interval 30 --pipeline-work-dir "$RUN/pipeline-e2b"
```

Дождитесь startup и `/health`, затем откройте новый локальный run с URL **без**
`?run=`. В `/health` должен быть `SDKEngine`, в UI — имя локальной модели.
Надпись провайдера `OpenAI` в UI относится к совместимому протоколу; запросы в
этом режиме идут на 127.0.0.1. Играйте при 1×; можно ставить паузу, пока
обрабатываются записи. 30 секунд — интервал автоматического вопроса, не SLA.
Проверяйте не только готовность ответа, но и его Source-ссылки и ограничения.

Почему именно этот профиль: на полном контексте Chat Completions игнорировал
`reasoning_effort=none`, `reasoning=off` и `enable_thinking=false` в этой установке.
Токены расходовались на рассуждения, JSON не получался. Responses с
`Reasoning(effort='none')` отключил reasoning, но без явной инструкции JSON модель
могла ответить обычным текстом. В рабочем профиле выше получен типизированный
Answer на **14 настоящих событиях из выборки UIService, 23917 символов** за
**12,286 с**: 10724 входных токена, 296 выходных, 0 reasoning, 0 cached input.
Ответ содержит сенсорные/радио-выводы, валидные event IDs и ограничения.
Контекст **16384 не использовать как проверенный профиль**: отдельный Q&A на нём
прошёл за 6,938 с, но сквозной запуск затем получил HTTP 500
`Context size has been exceeded`. После загрузки E2B с 32768 та же проба прошла.
Это параметр загрузки модели в LM Studio, а не лимит выборки приложения.
Отдельно extractor по настоящей реплике с запросом рабочего канала вернул
`channel_requested` с правильным event ID за **1,758 с**, без reasoning tokens.
Неуказанные team/channel/task_ref остались null. Это отдельные измерения, не
гарантия непрерывной обработки без отставания.

Ранее Gemma 12B успешно ответила за 5,710 с на трёх коротких тестовых событиях,
но на реальном контексте превысила 28-секундный таймаут, в том числе с полным
профилем Responses/none/JSON. Такой короткий smoke-test
недостаточен для выбора модели. Маленькая E2B также может ошибаться в интерпретации;
проверка JSON и ссылок не доказывает правильность каждого вывода. В пробах она
обобщала synthetic provenance на независимое радио и ошибочно интерпретировала
некоторые числовые/адресные реплики как назначения радиоканалов. Этот профиль
подтверждает локальную исполнимость LLM-ветки, не качество конкурсной облачной модели.
Неверный JSON, неизвестный ID и таймаут должны оставаться видимыми ошибками;
не заменяйте их незаметно FixtureEngine и не выдавайте prerecorded transcript за ASR.

## 8. Остановить и повторить

- Ctrl+C в терминалах gateway, agent, State, Platform и Redis.
- В терминале подготовки: `pg_ctl -D "$RUN/postgres" -m fast stop`.
- Не используйте `killall`, `docker compose down -v`, `DROP DATABASE` и удаление
  исходных данных как универсальный способ починить запуск.
- Для продолжения того же run сохраняйте `private/`, bundle и соответствующий
  journal. Поднимите свой PostgreSQL/Redis и процессы раздела 5, откройте сохранённый
  локальный URL. State после перезапуска восстанавливает replay на паузе.
  Время жизни run по умолчанию — 24 часа; после истечения откройте URL без
  `?run=` для нового воспроизведения. Срок run отличается от 30-дневного токена.
- Для полностью нового воспроизведения выберите новый `FIREWATCH_HOME`; сначала
  остановите предыдущие собственные процессы, чтобы освободить шесть портов.
- `git -C "$APP" status --porcelain` и аналогичная команда для `state-source`
  должны быть пустыми: исходники не изменялись. Результаты проверки хранятся снаружи.

## 9. Ошибки, обнаруженные при проверке

| Ошибка | Исправление без изменений исходников |
|---|---|
| `uv`: permission denied в общем cache | Отдельный `UV_CACHE_DIR` внутри `FIREWATCH_HOME`; не делать chown глобального кэша |
| Docker: отсутствуют цепочки `DOCKER-INTERNAL`/`DOCKER-FORWARD` | Основная инструкция использует собственные нативные PostgreSQL/Redis; Docker других проектов не перезапускается |
| State scenario not found | `--scenario palisades-focus`, предварительно выполнить importer; Base2 в открытом bundle отсутствует |
| State медиа ведут на неправильный host/port | `setup_local.py --public-url` должен совпасть с локальным сервером; существующий config скрипт намеренно не перезаписывает |
| После замены agent DB нет sources | Не переиспользовать старый journal с пустой новой БД: выбрать новый `--pipeline-work-dir` |
| SDK `Unknown prefix: google` | `FIRE_MODEL=openai/google/...`, endpoint — `OPENAI_BASE_URL` |
| SDK timeout / ответ не JSON | Проверенный профиль: E2B + Responses + `Reasoning(effort='none')` + явные JSON-инструкции раздела 7; Chat Completions off-флаги на полном контексте не помогли |
| LM Studio `Context size has been exceeded` | Загрузить E2B с context length 32768; профиль 16384 прошёл короткую пробу, но не сквозную проверку |
| Ошибка bind / занятый порт | Проверить владельца; остановить только собственный тестовый процесс или согласованно сменить порты |
| Камеры остановились после 6 секунд | Это штатная длительность цветных fixtures, радио продолжается до 206 секунд |
| Platform health OK, ingestion ошибается | Проверить миграции, собственный DATABASE_URL/Redis; одного health недостаточно |
| Бейдж `Disconnected`, но `/health` и импорт работают | Страница была открыта до готовности agent; обновить после завершения startup |

Для будущего resolver drift платформы в проверке установлены: FastAPI 0.141.1,
Uvicorn 0.52.4, SQLAlchemy 2.0.52, asyncpg 0.31.0, Alembic 1.20.0, Pydantic 2.13.5,
pydantic-settings 2.15.0, Redis Python 8.1.0, MCP 2.2.0, httpx 0.28.1,
httpx-sse 0.4.3. Если новые версии несовместимы, задайте constraints в отдельном
runtime-файле и пересоздайте только тестовый venv; приложение и requirements не менять.

## 10. Протокол фактической проверки

Проверено 12 сентября 2026 года на macOS, Apple M4 Max, 128 GiB RAM.
После исправлений инструкции её Bash-блоки
извлечены из этого файла и выполнены последовательно из новых публичных клонов
указанных выше commits, с новыми virtualenv и собственным PostgreSQL. Менялся
только выбранный внешний рабочий путь. Оба checkout остались чистыми.

| Проверка | Фактический результат |
|---|---|
| Чистая установка, сборка bundle, миграции, запуск всех пяти процессов | Успешно; health/config/status отвечают, Redis возвращает PONG, PostgreSQL сохраняет readings |
| `npm run verify` из свежего клона | 112 тестов: 15 JavaScript, 23 pipeline, 74 agent; проверки adapters также прошли |
| Полный replay в базовом FixtureEngine, включая UI | Завершён на 206000 мс; 43 транскрипции; Play/Pause/Reset работают |
| История полного replay | 186 observations: 33 measurement, 103 radio_audio, 6 camera, 1 access, 43 radio_transcript |
| Доставка в Platform/agent | 83 импортированные записи; 103 audio chunk metadata пропущены importer по его контракту, сами аудиобайты идут отдельным медиапотоком |
| Сохранность расшифровки | Все 43 текста точно совпали со строками исходного JSON, включая пробелы; новое ASR не выполнялось |
| Медиатранспорт | Оба H.264 fMP4 по 6 с и радио AAC fMP4 полностью декодированы FFmpeg без ошибок; AAC-контейнер 206,064 с с учётом encoder padding |
| Браузер | Видео и незаглушённое радио достигли readyState=4 без media errors; открыты источник ответа и исходный аудиоинтервал; ошибок JS в этом прогоне не было |
| Reset | Generation 0 → 1; прежний контекст UI очищен, старые 83 readings сохранены |
| Повторный запуск | State/gateway/agent перезапущены теми же командами; UUID, generation и позиция replay сохранены, в том числе пауза на 99751 мс |
| Локальная модель в UI, окончательный профиль E2B/32768/Responses | Извлечённые из этого файла launcher-блоки запущены с новой agent DB/journal. При 83 импортированных источниках автоматический ответ готов за 10,723 с, ранее падавший ручной вопрос — за 12,945 с; в каждом по три Source-ссылки |
| Изоляция Python runtime | Все адреса собственных сервисов — loopback; попыток запрещённых внешних соединений в журнале не было; 1Password и production-токены не использовались |

Полный 206-секундный медиапрогон выполнен в первой репетиции; затем итоговые команды
установки/запуска и тесты повторены буквально на ещё одной свежей копии. Это проверка
публичной локальной поставки с видеозаглушками, не приёмка закрытых Base2-видео и
не измерение точности модели.

Для повторения ручного модельного вопроса использовался текст:
`Give one brief sensor fact and one brief radio report, citing sources. State one limitation. Keep the answer under 100 words.`
В окончательном UI-прогоне открытая Source-ссылка совпала с исходной радиорепликой.
Измерения UI включают очередь обработки. Ранее профиль 16384 при продолжении
с 99,751 до 206 с сохранил весь поток, но давал ошибки модели и отставание; это
не было принято за успешную проверку inference. После исправления 32768 проверены
автоматический и ручной ответы на накопленном полном replay; устойчивый inference
при 1× на протяжении всего сценария этим не подтверждён. Обработка всех 43 радио
extractor-заданий без ошибок также не подтверждена: в финальной проверке
обнаруживались отдельные ошибки разбора. Смысловые ограничения модели перечислены
в разделе 7; они не скрыты за FixtureEngine и не исправлялись изменением приложения.
