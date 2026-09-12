# 0007. Isolate the test database from the live/dev database

**Status:** Accepted

## Context

`pytest` was running against whatever `DATABASE_URL` the live app/bridge were also using. This
surfaced as real damage: dozens of `test-*`/`radio-ch-*` junk device rows accumulating in the
same database a live demo was writing real State Machine data into, visible in `GET /devices`
alongside genuine `sm-*` rows.

## Decision

Tests get their own database (`platform_test` by default, or `TEST_DATABASE_URL` override),
auto-created and auto-migrated at test-session start via a `pytest_configure` hook (not a
fixture — `app/core/db.py` builds its `engine`/`async_session` at *import* time, and other
modules bind that name into their own namespace at import time too, so a fixture-based override
would run too late; `pytest_configure` runs before test collection/import, which is early enough).

## Consequences

- A full `pytest tests/ -v` run leaves the live/dev database's row counts provably unchanged —
  verified by counting rows before and after, twice, as part of accepting this fix.
- Test runs are now self-sufficient from a clean environment (no manual `createdb` step) since
  the hook creates the test database and runs migrations against it if missing.
- The junk rows that had already accumulated in the live database *before* this fix existed were
  cleaned up separately, carefully respecting a foreign-key dependency (`incident_evidence` rows
  referencing test devices had to be deleted before the devices themselves; the real `incidents`
  table was never touched).
