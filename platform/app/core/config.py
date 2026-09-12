from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/platform"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = "dev-secret-change-me"

    # State Machine bridge (app/adapter) — pulls live sensor data from the simulator team's
    # State Machine API and re-posts it to our own /ingest/telemetry. Never hardcode the real
    # bearer token; it belongs in the user's own .env, sourced from 1Password
    # (vault "aitinkerers-hack", item "State Machine API").
    state_machine_base_url: str = "https://api.aitinkerers.space/api/v1"
    state_machine_bearer_token: str = ""
    state_machine_scenario_id: str = "degraded"
    our_api_base_url: str = "http://localhost:8000"

    # Production mode: subscribe read-only to one externally-agreed, shared run instead
    # of creating our own (per the simulator team's deployment handoff,
    # raw-source/state-consumer-handoff/START_HERE.ru.md section 3: consumers must not
    # create a run per worker/reconnect and must not send Play to a shared run). When
    # set, use STATE_MACHINE_BEARER_TOKEN=<read_token> here, not control_token, since no
    # run-creation or command-sending happens in this mode. Leave unset for local
    # dev/integration testing, where creating our own run (and sending Play) is fine and
    # is the existing, unchanged default behavior.
    state_machine_run_id: str | None = None


settings = Settings()
