# Playbook: deploy platform on Hetzner (state-consumer)

Based on steps actually performed on September 12, 2026. Server is shared with State Machine
(`state-api.service`) — all commands below were written so as not to touch it.

## Prerequisites

- Access to 1Password vault `aitinkerers-hack` (SSH key `hetzner-state-machine-ssh`,
  tokens `State Machine API`, `Cloudflare`).
- `op` CLI authorized via `OP_SERVICE_ACCOUNT_TOKEN`.
- Server: `167.233.195.12`, host key fingerprint `SHA256:cfE6m4XvJ6p3Z+fwz8Ryh6FnWErvxdSUBlpiqqGf6hA`
  (verify before first connection!).

## 0. SSH key: PKCS#8 → OpenSSH conversion

1Password provides ed25519 private key in PKCS#8 PEM format with optional public key field
(RFC 5958 OneAsymmetricKey) — `ssh`/`ssh-keygen` do not read this format directly.

```bash
mkdir -m 700 /tmp/hetzner-ssh-XXXXXX && SSH_TMP_DIR=$(mktemp -d /tmp/hetzner-ssh-XXXXXX)
op read "op://aitinkerers-hack/hetzner-state-machine-ssh/private key" > "$SSH_TMP_DIR/id_key"
chmod 600 "$SSH_TMP_DIR/id_key"

# Normalization via openssl (removes optional field that cryptography does not read)
openssl pkey -in "$SSH_TMP_DIR/id_key" -out "$SSH_TMP_DIR/id_key_norm"

# PKCS#8 -> OpenSSH format conversion via Python cryptography
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

Verify the printed public key against the `public key` field in the same 1Password item —
they should match byte-for-byte.

## 1. Host verification and reconnaissance (read-only)

```bash
ssh-keyscan -t ed25519 167.233.195.12 2>/dev/null | ssh-keygen -lf - -E sha256
# verify against the documented fingerprint above

ssh-keyscan -t ed25519 167.233.195.12 2>/dev/null > "$SSH_TMP_DIR/known_hosts"
SSH="ssh -i $SSH_TMP_DIR/id_key_openssh -o IdentitiesOnly=yes -o IdentityAgent=none \
     -o UserKnownHostsFile=$SSH_TMP_DIR/known_hosts -o StrictHostKeyChecking=yes root@167.233.195.12"

$SSH 'systemctl show state-api -p ActiveState,MainPID,NRestarts; \
      readlink -f /opt/fire-state/current; ss -tlnp; free -h; df -h /; \
      sha256sum /etc/caddy/Caddyfile'
```

Save the output (baseline) — verify after each change that `state-api`/Caddy are not affected.

## 2. Docker installation + user/directory creation (once)

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

## 3. Secrets (`/etc/state-consumer/service.env`, 0600)

Production worker uses `read_token` (not `control_token`!) and subscribes to one agreed
`STATE_MACHINE_RUN_ID` — does not create its own run.

```bash
READ_TOKEN=$(op read "op://aitinkerers-hack/State Machine API/read_token")
{
  echo "API_KEY=<shared X-API-Key, see 1Password item 'Platform API_KEY (state-consumer / X-API-Key)'>"
  echo "STATE_MACHINE_BASE_URL=http://127.0.0.1:8787/api/v1"
  echo "STATE_MACHINE_BEARER_TOKEN=${READ_TOKEN}"
  echo "STATE_MACHINE_SCENARIO_ID=palisades-full"
  echo "STATE_MACHINE_RUN_ID=<run_id of agreed shared run>"
} | $SSH 'umask 077 && cat > /etc/state-consumer/service.env && \
          chown state-consumer:state-consumer /etc/state-consumer/service.env && \
          chmod 600 /etc/state-consumer/service.env'
```

### Creating agreed shared run (once, via control_token, NOT on server)

```bash
CONTROL_TOKEN=$(op read "op://aitinkerers-hack/State Machine API/control_token")
IDEMKEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -s -X POST "https://api.aitinkerers.space/api/v1/runs" \
  -H "Authorization: Bearer $CONTROL_TOKEN" -H "Idempotency-Key: $IDEMKEY" \
  -H "Content-Type: application/json" -d '{"scenario_id":"palisades-full","speed":1}'
# save run_id, then:
CMDKEY=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -s -X POST "https://api.aitinkerers.space/api/v1/runs/<run_id>/commands" \
  -H "Authorization: Bearer $CONTROL_TOKEN" -H "Content-Type: application/json" \
  -d "{\"command_id\":\"$CMDKEY\",\"expected_generation\":0,\"action\":\"play\"}"
```

## 4. Production compose override (`docker-compose.hetzner.yml`, server-only, not in git)

Reasons: `db`/`redis` without exposing ports outside; `app` only on loopback (Caddy proxies from outside);
`bridge` with `network_mode: host` to reach `state-api` at `127.0.0.1:8787`
(loopback access from server, not container).

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

Copy into each new release on deploy (see step 5) — this file is not version-controlled
in the repo (deployment-specific, lives only on server).

## 5. Release and run

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

First release compose-override is copied manually (see step 4) — subsequent releases
carry it from `current` before git clone (as in command above).

## 6. Verification

```bash
$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8790/health; \
      docker logs platform-bridge-1 --tail 10 | grep -v "ingest/telemetry.*200"; \
      systemctl show state-api -p MainPID,NRestarts'  # NRestarts should stay 0
```

## 7. Caddy + DNS (public access) — separate confirmation before execution

```bash
# DNS (Cloudflare) -- DNS only, without proxying
CF_TOKEN=$(op read 'op://aitinkerers-hack/Cloudflare/CLOUDFLARE_API_TOKEN')
ZONE_ID=$(op read 'op://aitinkerers-hack/Cloudflare/CLOUDFLARE_ZONE_ID')
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"A","name":"platform.aitinkerers.space","content":"167.233.195.12","ttl":300,"proxied":false}'

# Caddy: backup, add one new block, validate, install, reload (NOT restart)
$SSH 'cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date -u +%Y%m%dT%H%M%SZ)'
# ... form /tmp/Caddyfile.candidate = current + new block ...
$SSH 'caddy validate --config /tmp/Caddyfile.candidate'
$SSH 'cp /tmp/Caddyfile.candidate /etc/caddy/Caddyfile && systemctl reload caddy'

# Check publicly (--resolve bypasses local DNS cache if propagation hasn't completed)
curl -s --resolve platform.aitinkerers.space:443:167.233.195.12 https://platform.aitinkerers.space/health
```

New Caddy block (example, copied from the pattern of existing `api.aitinkerers.space`):

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

## Rollback

- Application: `docker compose -f docker-compose.yml -f docker-compose.hetzner.yml down`,
  switch `current` symlink to previous release, bring up again.
- Caddy: restore `/etc/caddy/Caddyfile.bak-<timestamp>`, `systemctl reload caddy`
  (verify the file has not changed since then by another command — compare hash before rollback).
- DNS: delete A-record `platform.aitinkerers.space` via the same Cloudflare API
  (`DELETE /zones/{zone_id}/dns_records/{id}`).
- **Never**: touch `state-api.service`, its directories/DB/config, do not `restart`/`stop`
  it, do not run its `verify_state_api_live.py`.
