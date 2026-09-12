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


settings = Settings()
