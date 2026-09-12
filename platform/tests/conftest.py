"""Session-wide test setup.

Isolates the test suite onto its own Postgres database (by default the same server as
`DATABASE_URL`, just a different db name -- `<name>_test`) so `pytest` never reads or
writes whatever database the live app/bridge are actually using.

This has to happen in `pytest_configure`, NOT in a fixture (even a session-scoped
autouse one), because of how the app wires up its DB layer:

- `app/core/db.py` builds `engine`/`async_session` exactly once, at MODULE IMPORT TIME,
  from `app.core.config.settings.database_url`.
- `app/ingestion/ws.py` and `app/mcp/server.py` do `from app.core.db import
  async_session`, which binds that name in their OWN module namespace at import time
  too -- reassigning `app.core.db.async_session` later would not change what those two
  modules already grabbed.
- Test collection (which imports `app.main`, and transitively `app.core.db`,
  `app.mcp.server`, `app.ingestion.ws`, ...) happens BEFORE any fixture ever runs.

So by the time a fixture could override `settings.database_url`, every module that
cares about it has already read the wrong (live) value and built its engine/session
factory from it. `pytest_configure` runs before collection, so setting
`settings.database_url` there means every module sees the test database the first and
only time it reads the setting.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parent.parent

# Shared-secret auth header required by app.core.security.ApiKeyMiddleware for every
# non-exempt HTTP request. Import this into any test module that builds an AsyncClient
# against `app.main.app`.
AUTH_HEADERS = {"X-API-Key": settings.api_key}


def _derive_test_database_url(live_url: str) -> str:
    """`.../platform` -> `.../platform_test` on the same server, same credentials."""
    parts = urlsplit(live_url)
    db_name = (parts.path.lstrip("/") or "platform").removesuffix("_test") + "_test"
    return urlunsplit((parts.scheme, parts.netloc, f"/{db_name}", parts.query, parts.fragment))


def _asyncpg_url(sqlalchemy_url: str) -> str:
    # asyncpg wants a plain `postgresql://` DSN, not SQLAlchemy's driver-qualified one.
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _ensure_database_exists(test_url: str) -> None:
    parts = urlsplit(_asyncpg_url(test_url))
    db_name = parts.path.lstrip("/")
    # CREATE DATABASE can't run against the database being created -- connect to
    # Postgres's own always-present maintenance database instead.
    maintenance_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))
    conn = await asyncpg.connect(maintenance_url)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            # db_name is derived from our own DATABASE_URL/TEST_DATABASE_URL, never
            # from request input, so this is safe despite not being parameterizable.
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


def _run_migrations(test_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env=env,
        check=True,
    )


def pytest_configure(config) -> None:
    test_url = os.environ.get("TEST_DATABASE_URL") or _derive_test_database_url(
        settings.database_url
    )

    asyncio.run(_ensure_database_exists(test_url))
    _run_migrations(test_url)

    # Mutates the shared `settings` singleton in place (everyone holds the same object)
    # before anything imports app.core.db/app.mcp.server/app.ingestion.ws -- see the
    # module docstring for why that ordering is what makes this actually take effect.
    settings.database_url = test_url
    os.environ["DATABASE_URL"] = test_url
