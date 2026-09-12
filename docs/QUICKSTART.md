# Run Firewatch

Run commands from the repository root unless a step says otherwise. This starts a loopback application, not a public deployment.

## Prerequisites and verification

Git, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 18+ and npm. Use a recent Chrome for the demonstrated H.264/AAC playback path; other browsers were not validated. Docker Compose is needed only for a local Data Platform.

```bash
git clone https://github.com/Anastassy/fire-incident-copilot.git
cd fire-incident-copilot
uv sync --project agent-service --locked
npm run verify
```

No root `npm install` is needed. Dependency installation needs network access. Verification then uses local fixtures and mocked providers; Python tests permit loopback HTTP fixtures and reject external connections. Platform database integration tests and live API/model calls are outside this command.

## Fixture UI without keys

With ports 8010 and 8790 free:

```bash
FIRE_ENGINE=fixture python3 dashboard/live/run_local.py
```

Open **http://127.0.0.1:8790/**. The launcher starts an agent on 8010, or reuses an existing agent there, and starts the gateway on 8790. If an SDK agent occupies 8010, stop your own process or use the separate live setup below; fixture controls require `FixtureEngine`.

Use **Request**, **Assign channel**, then **Acknowledge** in the `dashboard-channel-demo-en` fixture session. Inspect the check and its sources. Questions exercise the API and return deterministic output, not model interpretation. State authentication errors are expected without credentials; this mode provides no live camera/radio material.

Ctrl+C stops only the processes the launcher started. Agent state persists under ignored `agent-service/work/`. The fixture Reset control resets its own test context.

## Live stream and model analysis

### 1. Services and credentials

| Dependency | Configuration | Purpose |
|---|---|---|
| State API | Base URL + read token | Catalog, observations, history, SSE and media |
| State controls | Control token | Create, Play, pause, seek or reset a run |
| Data Platform | Base URL + API key | Store observations and return reading IDs |
| OpenRouter | `OPENROUTER_API_KEY` in agent environment | Billable model extraction and answers |

The team's hosted endpoints are `https://api.aitinkerers.space/api/v1` and `https://platform.aitinkerers.space`. Cloning does not grant access. Obtain authorized credentials from the team or configure compatible services. The simulator/media server is a separate deployment, not recreated by this quickstart.

For a **local** Platform, start only the app and its database/cache dependencies:

```bash
cd platform
API_KEY=local-demo-only docker compose up --build -d app
cd ..
```

This development setup publishes ports 8000, 5433 and 6379. `local-demo-only` is an example development key, not a deployment secret. Migrations run at startup; health is at http://127.0.0.1:8000/health and API docs at http://127.0.0.1:8000/docs. The database is empty until ingestion. Do not start the standalone `bridge` service in this workflow: the dashboard gateway owns ingestion.

Create a private configuration directory outside the checkout:

```bash
mkdir -p "$HOME/.config/firewatch"
chmod 700 "$HOME/.config/firewatch"
```

Save `state-client.json` there, replacing the placeholders:

```json
{
  "base_url": "https://api.aitinkerers.space/api/v1",
  "read_token": "<State read token>",
  "control_token": "<State control token>"
}
```

Save `platform-client.json` there. For the local Platform above:

```json
{
  "base_url": "http://127.0.0.1:8000",
  "api_key": "local-demo-only"
}
```

For a hosted Platform, replace both fields with its URL and authorized key. Protect the files:

```bash
chmod 600 "$HOME/.config/firewatch/state-client.json" "$HOME/.config/firewatch/platform-client.json"
```

### 2. Model agent — terminal A

Inject `OPENROUTER_API_KEY` through your secret manager into this terminal's process environment. A plain `.env` file is **not** loaded automatically. For 1Password, the [existing `op run` setup](../agent-service/docs/OPENROUTER.md) resolves a vault reference without copying the API key into source code.

```bash
cd agent-service
FIRE_ENGINE=sdk \
FIRE_PROVIDER=openrouter \
FIRE_MODEL=google/gemini-3.1-flash-lite \
FIRE_FALLBACK_MODEL=openai/gpt-5.6-luna \
FIRE_REASONING_EFFORT=minimal \
FIRE_FALLBACK_REASONING_EFFORT=none \
FIRE_PROVIDER_SORT=latency \
FIRE_MAX_OUTPUT_TOKENS=1200 \
FIRE_EVENT_WORKERS=4 \
FIRE_OUTPUT_LANGUAGE=en \
FIRE_DB_PATH=work/live.sqlite3 \
uv run uvicorn fire_agents.api:create_app --factory --host 127.0.0.1 --port 8012
```

Health is at http://127.0.0.1:8012/health. Inspect `engine` and `model_configuration` for the actual backend/models. Preserve `work/live.sqlite3` on restart; choose another filename for a separate experiment instead of deleting an existing database.

### 3. Gateway — terminal B, repository root

```bash
python3 dashboard/live/server.py --port 8790 \
  --state-config "$HOME/.config/firewatch/state-client.json" \
  --platform-config "$HOME/.config/firewatch/platform-client.json" \
  --agent-url http://127.0.0.1:8012 \
  --live-pipeline --analysis-interval 3 \
  --pipeline-work-dir agent-service/work/live-pipeline
```

Do not use `--demo-agent` or `run_local.py` for this live path. No `FIRE_PLATFORM_SCOPE` importer is required. If configured, supply the same `FIRE_UI_SESSION_TOKEN` to agent and gateway.

### 4. Complete interaction

1. Open http://127.0.0.1:8790/ and create your own paused run. An agreed existing run can be opened using `?run=<run-id>`; its controls affect every subscriber.
2. Select Base2 × Palisades and press **Play** at **1×**. Enable radio sound with the player control; audible browser autoplay requires user interaction.
3. Watch metrics, CCTV windows, transcripts and the automatic briefing. Scheduling permits one automatic analysis at a time, at least three seconds apart; model latency is additional.
4. Ask what changed in Gradas and whether the records establish occupancy. Inspect sources and unknowns. Open an available radio source to hear the original interval.
5. Pause your run. Seek/reset only your own run. A new generation creates a separate agent context while preserving previous records.

Keep the journal in `agent-service/work/live-pipeline` with the agent database. Run only one importer per run. Transport and inference are separate: CCTV pixels do not enter a vision model, and the radio transcript was prepared previously.

### Troubleshooting

| Symptom | Check |
|---|---|
| State unavailable / 401 / 403 | State URL and read token; creation/controls additionally require the control token |
| Streams present, briefing missing | Gateway `--live-pipeline`, Platform credentials, agent health and visible pipeline status |
| Agent health says `platform_connected=false` | This describes its optional standalone poller. For the gateway-owned path inspect `/api/pipeline/status` on port 8790 |
| Model request fails | OpenRouter credentials/account model access and provider details. Fallback is bounded; errors are not replaced with fixture claims |
| Video gaps / no sound at high speed | Camera assets cover selected windows; use 1× for radio and unmute explicitly |
| Unexpected shared run position | A run ID shares state. Use your own run and preserve other participants' databases/journals |

## Verification scope

[Recorded live validation](../dashboard/live/VALIDATION.md) covers actual hosted State/Platform services and local SDK/browser behavior. `npm run verify` covers 15 JavaScript, 23 gateway/pipeline Python and 74 agent tests, plus design adapter assertions.

A separate no-key HTTP smoke test exercised the actual fixture gateway and agent: request → insufficient data, assignment → insufficient data, acknowledgement → supported, with three synthetic evidence records. It used temporary ports/SQLite and no external connections. It was not a browser or fresh-install test.

Commands were checked against locked dependencies and executable options. A new participant machine and fresh Docker install were not exercised during this documentation update. Tests do not establish semantic accuracy, an inference SLA or access through another person's external accounts.
