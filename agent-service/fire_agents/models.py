from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Event(BaseModel):
    session_id: str
    generation: int = Field(ge=0)
    event_id: str
    time_ms: int = Field(ge=0)
    source_id: str
    kind: Literal['radio', 'sensor', 'system']
    description: str = ''
    payload: dict = Field(default_factory=dict)
    media_url: str | None = None
    media_start_ms: int | None = Field(default=None, ge=0)
    media_end_ms: int | None = Field(default=None, ge=0)
    reading_id: int | None = None
    @model_validator(mode='after')
    def interval(self):
        if self.media_end_ms is not None and (self.media_start_ms is None or self.media_end_ms < self.media_start_ms):
            raise ValueError('Invalid media interval')
        return self

class Claim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)

class Extraction(BaseModel):
    action: Literal['none', 'assigned', 'accepted', 'completed', 'cancelled']
    task_ref: str | None = None
    team: str | None = None
    claim: Claim | None = None

class Answer(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

class Question(BaseModel):
    session_id: str
    generation: int
    text: str = Field(min_length=1, max_length=4000)

class ClockUpdate(BaseModel):
    time_ms: int = Field(ge=0)
