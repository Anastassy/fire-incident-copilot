"""Bridge/adapter: pulls live sensor data from the simulator team's State Machine API
(SSE) and re-posts it to our own ``POST /ingest/telemetry`` so the rest of the platform
(REST/SSE, MCP) keeps consuming data through the existing, unchanged ingestion contract.

Entrypoint: ``python -m app.adapter.bridge``. Not wired into the FastAPI app — this is a
separate long-running process, just another client of our own ingestion endpoint.
"""
