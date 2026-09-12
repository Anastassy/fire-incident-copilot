"""Public agent→UI v1 DTOs. Keep aligned with the handoff contract."""
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field

class DTO(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Context(DTO):
    demo_context_id: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=0)
    subject_id: str = Field(min_length=1, max_length=200)

class Coverage(DTO):
    as_of_ms: int = Field(ge=0)
    checked_from_ms: int = Field(ge=0)
    checked_until_ms: int = Field(ge=0)
    completeness: Literal['complete','partial','unknown']
    limitations: list[str]

class Query(DTO):
    query_id: str
    tool: str
    filters: dict[str, Any]
    started_at: str
    completed_at: str | None
    status: Literal['running','succeeded','failed']
    completeness: Literal['complete','partial','unknown']
    error_code: str | None

class Claim(DTO):
    claim_id: str
    text: str
    kind: Literal['source_report','measurement','inference','absence_in_checked_data']
    evidence_ids: list[str] = Field(min_length=1)

class Error(DTO):
    code: str
    message: str
    retryable: bool
    request_id: str

class QuestionCreate(DTO):
    context: Context
    client_request_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=4000)
    language: Literal['en','ru']

class Answer(DTO):
    request_id: str
    context: Context
    revision: int = Field(ge=0)
    status: Literal['queued','running','ready','insufficient_data','error','cancelled']
    question: str
    language: Literal['en','ru']
    claims: list[Claim]
    unknowns: list[str]
    coverage: Coverage
    queries: list[Query]
    evidence_ids: list[str]
    created_at: str
    completed_at: str | None
    error: Error | None

class Card(DTO):
    hypothesis_id: str
    platform_incident_id: str | None
    context: Context
    revision: int = Field(ge=0)
    statement: str
    assessment: Literal['checking','supported','refuted','insufficient_data']
    lifecycle: Literal['active','closed']
    platform_status: Literal['open','acknowledged','resolved','escalated'] | None
    publication_status: Literal['pending','synced','uncertain','error']
    claims: list[Claim]
    unknowns: list[str]
    coverage: Coverage
    queries: list[Query]
    evidence_ids: list[str]
    checked_at: str
    closure_reason: str | None

class Audio(DTO):
    media_id: str
    availability: Literal['available','pending','missing','error']
    playback_url: str | None
    expires_at: str | None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    time_basis: Literal['returned_media']
    mime_type: str | None

class Evidence(DTO):
    evidence_id: str
    context: Context
    reading_id: int = Field(gt=0)
    device_id: str
    event_from_ms: int = Field(ge=0)
    event_until_ms: int = Field(ge=0)
    source_label: str
    text: str
    text_kind: Literal['description','machine_transcript','human_verified_transcript']
    verification: Literal['not_human_verified','human_verified','not_applicable']
    origin: Literal['recorded','synthetic','derived','human_report','unknown']
    audio: Audio | None
    raw_reading: dict[str, Any]

class Snapshot(DTO):
    context: Context
    snapshot_revision: int = Field(ge=0)
    answers: list[Answer]
    cards: list[Card]
    updated_at: str

class Changed(DTO):
    type: Literal['answer.changed','card.changed','context.invalidated']
    context: Context
    entity_id: str | None
    revision: int = Field(ge=0)
