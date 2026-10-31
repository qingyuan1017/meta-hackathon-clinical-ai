from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRead(BaseModel):
    id: str
    workflow: str
    name: str
    description: str
    tools: list[str]
    max_turns: int


class AgentEventRead(BaseModel):
    turn: int
    type: str
    actor: Literal["agent", "user", "system"] = "agent"
    name: str | None = None
    stage: str | None = None
    ok: bool | None = None
    error: str | None = None
    summary: str | None = None
    intent: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    input_details: dict[str, Any] = Field(default_factory=dict)
    output_details: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    occurred_at: datetime | None = None


class AgentProgressRead(BaseModel):
    agent_id: str
    workflow: str
    status: str
    model: str | None = None
    turn: int
    max_turns: int
    stage: str | None = None
    stage_index: int = 1
    stage_count: int = 1
    completed_stages: list[str] = Field(default_factory=list)
    total_source_chunks: int
    read_source_chunks: list[int]
    started_at: datetime | None = None
    updated_at: datetime | None = None
    events: list[AgentEventRead]
