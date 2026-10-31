from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class UseCaseRead(BaseModel):
    id: str
    title: str
    description: str
    skill_name: str
    agent_id: str
    agent_name: str
    accepted_extensions: list[str]
    required_inputs: list[str]
    output_formats: list[str]
    mcp_dependencies: list[str]
    stages: list[str] = Field(default_factory=list)
    supports_languages: bool
    supports_result_editing: bool
    result_schema: dict[str, Any]


class CDISCDatasetRead(BaseModel):
    standard: Literal["sdtm", "sdtmig"]
    version: str
    domain: str
    payload: dict[str, Any] | list[Any]
