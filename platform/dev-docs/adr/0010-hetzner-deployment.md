# 0010. Deploy the full stack via Docker Compose on the shared Hetzner box

**Status:** Accepted

## Context

The simulator team shared a deployment handoff for putting a "state consumer" project on their
existing Hetzner server (`167.233.195.12`), which already runs their `state-api.service` behind a
shared Caddy reverse proxy. The handoff explicitly distinguished a lightweight "worker only" deploy
from a full "project with its own public API" deploy, and gave hard constraints: never touch the
existing service/its data/its Caddy block, run as an unprivileged user with resource limits (the
box has 1 CPU, ~1.4 GB free RAM), and be ready to explain/roll back only our own addition.

Two sub-decisions were needed: (a) deploy just the bridge/worker, or the full platform with a
public API; (b) if the full platform, run it natively under systemd (as the handoff's own
examples assumed) or containerized.

## Decision

- **Deploy the full stack** (Postgres, Redis, our FastAPI app, and the bridge) with its own
  public API, not just a worker — the dashboard/agent teams need a real, reachable endpoint, not
  just data silently flowing into a box nobody can query.
- **Use Docker Compose** (installing Docker Engine as the one system-level change) and reuse the
  already-tested `docker-compose.yml`, rather than hand-installing Postgres/Redis as native
  systemd services. A dedicated `docker-compose.hetzner.yml` override (kept on the server only,
  not committed) adapts it for this host: `db`/`redis` lose their host port publishing (internal-
  only), `app` publishes only on `127.0.0.1:8790` (Caddy terminates public TLS in front of it),
  and the `bridge` service runs with `network_mode: host` specifically so it can reach
  `state-api.service` on the host's own loopback (`127.0.0.1:8787`) — the handoff's own explicit
  warning that a container's loopback is not the host's loopback.
- Everything else followed the handoff's constraints literally: a dedicated unprivileged
  `state-consumer` system user (in the `docker` group, no login shell), `/opt/state-consumer/
  releases/<id>` + a `current` symlink for releases, secrets only in `/etc/state-consumer/
  service.env` (0600), a read-only recon pass and saved baseline (`state-api` PID/NRestarts,
  Caddyfile hash) *before* any change, `caddy validate` + `systemctl reload` (never `restart`)
  for the one new Caddy block, and a Cloudflare DNS-only (non-proxied) A-record for the new
  subdomain — chosen as `platform.aitinkerers.space`, not the handoff's own placeholder suggestion
  of `processor.aitinkerers.space`, per explicit user preference.
- The production bridge subscribes to one shared, pre-created `STATE_RUN_ID` using the team's
  `read_token` rather than creating its own run (see ADR-0008) — that run was created and started
  once, out-of-band, using the `control_token`.

## Consequences

- `state-api.service`'s PID and restart count were verified unchanged across every step of the
  deployment (Docker install, user/directory creation, container builds, Caddy reload) — the
  non-interference constraint held throughout, not just as an initial check.
- The stack fits comfortably in the box's resource envelope alongside the existing service.
- A real, live, TLS-terminated public endpoint (`https://platform.aitinkerers.space`) now serves
  the same contract the dashboard/agent teams had already been integrating against locally —
  no contract change was needed to go from "local docker-compose" to "real shared server."
- A full runbook (`dev-docs/hetzner-deploy-playbook.md`) was captured from the actual commands
  used, specifically so a repeat deployment (or another team member) doesn't have to rediscover
  the SSH-key-format pitfall (PKCS#8 ed25519 needs conversion to OpenSSH format — see the
  playbook's step 0) or any of the other one-off gotchas hit along the way (e.g. Docker CLI
  needing a writable `$HOME` for a home-less system user).
