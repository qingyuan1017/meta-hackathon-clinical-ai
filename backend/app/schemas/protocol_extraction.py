from __future__ import annotations

from pydantic import BaseModel, Field


class Objective(BaseModel):
    category: str = "Other"
    objective: str
    endpoint: str = "Not specified"


class StudySummary(BaseModel):
    study_title: str = "Untitled study"
    protocol_number: str = "Not specified"
    phase: str = "Not specified"
    indication: str = "Not specified"
    sponsor: str = "Not specified"
    study_design: str = "Not specified"
    population: str = "Not specified"
    sample_size: str = "Not specified"
    duration: str = "Not specified"
    arms: list[str] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    visits: list[str] = Field(default_factory=list)
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    assessments: list[str] = Field(default_factory=list)
    safety_monitoring: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
