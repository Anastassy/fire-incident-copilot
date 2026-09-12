# Плейбук: деплой platform на Hetzner (state-consumer)

Основано на реально выполненных шагах 12 сентября 2026. Сервер общий с State Machine
(`state-api.service`) — все команды ниже писались так, чтобы её не задеть.

## Предпосылки

- Доступ к 1Password vault `aitinkerers-hack` (SSH-ключ `hetzner-state-machine-ssh`,
  токены `State Machine API`, `Cloudflare`).
- `op` CLI авторизован через `OP_SERVICE_ACCOUNT_TOKEN`.
- Сервер: `167.233.195.12`, host key fingerprint `SHA256:cfE6m4XvJ6p3Z+fwz8Ryh6FnWErvxdSUBlpiqqGf6hA`
  (сверять перед первым подключением!).

## 0. SSH-ключ: конвертация PKCS#8 → OpenSSH

1Password отдаёт ed25519 private key в PKCS#8 PEM с опциональным полем public key
(RFC 5958 OneAsymmetricKey) — `ssh`/`ssh-keygen` такой формат не читают напрямую.

```bash
mkdir -m 700 /tmp/hetzner-ssh-XXXXXX && SSH_TMP_DIR=$(mktemp -d /tmp/hetzner-ssh-XXXXXX)
op read "op://aitinkerers-hack/hetzner-state-machine-ssh/private key" > "$SSH_TMP_DIR/id_key"
chmod 600 "$SSH_TMP_DIR/id_key"

# Нормализация через openssl (убирает опциональное поле, которое cryptography не читает)
openssl pkey -in "$SSH_TMP_DIR/id_key" -out "$SSH_TMP_DIR/id_key_norm"

# Конвертация PKCS#8 -> OpenSSH формат через Python cryptography
python3 - "$SSH_TMP_DIR/id_key_norm" "$SSH_TMP_DIR/id_key_openssh" <<'PYEOF'
import sys, os
from cryptography.hazmat.primitives import serialization
src, dst = sys.argv[1], sys.argv[2]
key = serialization.load_pem_private_key(open(src, "rb").read(), password=None)
data = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.OpenSSH,
    encryption_algorithm=serialization.NoEncryption(),
)
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as f:
    f.write(data)
print(key.public_key().public_bytes(
    encoding=serialization.Encoding.OpenSSH,
    format=serialization.PublicFormat.OpenSSH,
).decode())
PYEOF
```

Сверить выведенный публичный ключ с полем `public key` в том же 1Password item — должны
совпадать побайтово.

## 1. Проверка хоста и рекогносцировка (read-only)

```bash
ssh-keyscan -t ed25519 167.233.195.12 2>/dev/null | ssh-keygen -lf - -E sha256
# сверить с задокументированным fingerprint выше

ssh-keyscan -t ed25519 167.233.195.12 2>/dev/null > "$SSH_TMP_DIR/known_hosts"
SSH="ssh -i $SSH_TMP_DIR/id_key_openssh -o IdentitiesOnly=yes -o IdentityAgent=none \
     -o UserKnownHostsFile=$SSH_TMP_DIR/known_hosts -o StrictHostKeyChecking=yes root@167.233.195.12"

$SSH 'systemctl show state-api -p ActiveState,MainPID,NRestarts; \
      readlink -f /opt/fire-state/current; ss -tlnp; free -h; df -h /; \
      sha256sum /etc/caddy/Caddyfile'
```

Сохранить вывод (baseline) — сверять после каждого изменения, что `state-api`/Caddy не задеты.

## 2. Установка Docker + создание пользователя/каталогов (один раз)

```bash
$SSH 'curl -fsSL https://get.docker.com | sh'

$SSH 'useradd --system --no-create-home --shell /usr/sbin/nologin state-consumer; \
      usermod -aG docker state-consumer; \
      mkdir -p /opt/state-consumer/releases /var/lib/state-consumer/pgdata \
               /var/lib/state-consumer/redis /var/lib/state-consumer/home/.docker \
               /etc/state-consumer; \
      chown -R state-consumer:state-consumer /opt/state-consumer /var/lib/state-consumer /etc/state-consumer; \
      chmod 750 /etc/state-consumer'
```

## 3. Секреты (`/etc/state-consumer/service.env`, 0600)

Production-воркер использует `read_token` (не `control_token`!) и подписывается на один
согласованный `STATE_MACHINE_RUN_ID` — не создаёт свой run.

```bash
READ_TOKEN=$(op read "op://aitinkerers-hack/State Machine API/read_token")
{
  echo "API_KEY=<общий X-API-Key, см. 1Password item 'Platform API_KEY (state-consumer / X-API-Key)'>"
  echo "STATE_MACHINE_BASE_URL=http://127.0.0.1:8787/api/v1"
  echo "STATE_MACHINE_BEARER_TOKEN=${READ_TOKEN}"
  echo "STATE_MACHINE_SCENARIO_ID=palisades-full"
  echo "STATE_MACHINE_RUN_ID=<run_id согласованного общего run>"
} | $SSH 'umask 077 && cat > /etc/state-consumer/service.env && \
          chown state-consumer:state-consumer /etc/state-consumer/service.env && \
          chmod 600 /etc/state-consumer/service.env'
```

### Создание согласованного общего run (один раз, через control_token, НЕ на сервере)

```bash
CONTROL_TOKEN=$(op read "op://aitinkerers-hack/State Machine API/control_token")
IDEMKEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -s -X POST "https://api.aitinkerers.space/api/v1/runs" \
  -H "Authorization: Bearer $CONTROL_TOKEN" -H "Idempotency-Key: $IDEMKEY" \
  -H "Content-Type: application/json" -d '{"scenario_id":"palisades-full","speed":1}'
# сохранить run_id, затем:
CMDKEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -s -X POST "https://api.aitinkerers.space/api/v1/runs/<run_id>/commands" \
  -H "Authorization: Bearer $CONTROL_TOKEN" -H "Content-Type: application/json" \
  -d "{\"command_id\":\"$CMDKEY\",\"expected_generation\":0,\"action\":\"play\"}"
```

## 4. Prod-compose override (`docker-compose.hetzner.yml`, лежит только на сервере, не в git)

Причины: `db`/`redis` без публикации портов наружу; `app` только на loopback (Caddy сам
проксирует снаружи); `bridge` с `network_mode: host`, чтобы достать `state-api` по
`127.0.0.1:8787` (доступ к loopback сервера, не контейнера).

```yaml
services:
  db:
    ports: []
    volumes:
      - /var/lib/state-consumer/pgdata:/var/lib/postgresql/data
  redis:
    ports: []
    volumes:
      - /var/lib/state-consumer/redis:/data
  app:
    ports:
      - "127.0.0.1:8790:8000"
  bridge:
    network_mode: host
    environment:
      OUR_API_BASE_URL: http://127.0.0.1:8790
      STATE_MACHINE_BASE_URL: http://127.0.0.1:8787/api/v1
```

Копировать в каждый новый релиз при деплое (см. шаг 5) — этот файл не version-controlled
в репозитории (деплой-специфичный, живёт только на сервере).

## 5. Релиз и запуск

```bash
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-main"
$SSH "sudo -u state-consumer git clone --depth 1 --branch main \
      https://github.com/Anastassy/fire-incident-copilot.git \
      /opt/state-consumer/releases/$RELEASE_ID && \
      sudo -u state-consumer cp /opt/state-consumer/current/platform/docker-compose.hetzner.yml \
        /opt/state-consumer/releases/$RELEASE_ID/platform/docker-compose.hetzner.yml && \
      ln -sfn /opt/state-consumer/releases/$RELEASE_ID /opt/state-consumer/current && \
      chown -h state-consumer:state-consumer /opt/state-consumer/current"

$SSH 'sudo -u state-consumer HOME=/var/lib/state-consumer/home bash -c \
      "cd /opt/state-consumer/current/platform && \
       docker compose --env-file /etc/state-consumer/service.env \
         -f docker-compose.yml -f docker-compose.hetzner.yml up -d --build"'
```

Первый релиз compose-override копируется вручную (см. шаг 4) — последующие релизы
переносят его из `current` перед git clone (как в команде выше).

## 6. Проверка

```bash
$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8790/health; \
      docker logs platform-bridge-1 --tail 10 | grep -v "ingest/telemetry.*200"; \
      systemctl show state-api -p MainPID,NRestarts'  # NRestarts должен остаться 0
```

## 7. Caddy + DNS (публичный доступ) — отдельное подтверждение перед выполнением

```bash
# DNS (Cloudflare) -- DNS only, без проксирования
CF_TOKEN=$(op read 'op://aitinkerers-hack/Cloudflare/CLOUDFLARE_API_TOKEN')
ZONE_ID=$(op read 'op://aitinkerers-hack/Cloudflare/CLOUDFLARE_ZONE_ID')
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"A","name":"platform.aitinkerers.space","content":"167.233.195.12","ttl":300,"proxied":false}'

# Caddy: бэкап, добавить один новый блок, validate, установить, reload (НЕ restart)
$SSH 'cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date -u +%Y%m%dT%H%M%SZ)'
# ... сформировать /tmp/Caddyfile.candidate = текущий + новый блок ...
$SSH 'caddy validate --config /tmp/Caddyfile.candidate'
$SSH 'cp /tmp/Caddyfile.candidate /etc/caddy/Caddyfile && systemctl reload caddy'

# Проверка публично (--resolve обходит локальный DNS-кэш, если ещё не пропагировался)
curl -s --resolve platform.aitinkerers.space:443:167.233.195.12 https://platform.aitinkerers.space/health
```

Новый блок Caddy (пример, скопирован по образцу существующего `api.aitinkerers.space`):

```
platform.aitinkerers.space {
    header {
        Referrer-Policy no-referrer
        X-Content-Type-Options nosniff
        Strict-Transport-Security "max-age=31536000"
    }
    reverse_proxy 127.0.0.1:8790 {
        flush_interval -1
    }
}
```

## Откат

- Приложение: `docker compose -f docker-compose.yml -f docker-compose.hetzner.yml down`,
  переключить symlink `current` на предыдущий release, поднять заново.
- Caddy: восстановить `/etc/caddy/Caddyfile.bak-<timestamp>`, `systemctl reload caddy`
  (свериться, что файл с тех пор не менялся другой командой — сравнить хеш перед откатом).
- DNS: удалить A-record `platform.aitinkerers.space` через тот же Cloudflare API
  (`DELETE /zones/{zone_id}/dns_records/{id}`).
- **Никогда**: не трогать `state-api.service`, её каталоги/БД/конфиг, не `restart`/`stop`
  для неё, не запускать её `verify_state_api_live.py`.
