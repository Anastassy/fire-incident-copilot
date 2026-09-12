#!/usr/bin/env sh
# Entrypoint for the `app` service: apply pending Alembic migrations, then exec the
# real command (uvicorn). `set -e` makes a failed migration abort the container with a
# non-zero exit instead of silently starting the app against a stale schema.
set -e

echo "[entrypoint] running: alembic upgrade head"
alembic upgrade head
echo "[entrypoint] migrations applied, starting: $*"

exec "$@"
