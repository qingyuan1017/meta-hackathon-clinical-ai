from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ProgramGenerationStatus = Literal["not_started", "running", "review_required", "completed", "failed"]
ExecutionStatus = Literal[
    "not_applicable", "not_run", "queued", "running", "review_required", "passed", "failed"
]
ValidationStatus = Literal[
    "not_run", "imported", "running", "review_required", "completed_with_findings", "passed", "failed", "unavailable"
]
SubmissionReadinessStatus = Literal["not_assessed", "blocked", "review_required", "ready"]


class SDTMLifecycle(BaseModel):
    program_generation: ProgramGenerationStatus = "not_started"
    execution: ExecutionStatus = "not_run"
    validation: ValidationStatus = "not_run"
    submission_readiness: SubmissionReadinessStatus = "not_assessed"


class SourceColumnProfile(BaseModel):
    name: str
    data_type: str


class RawDatasetInventory(BaseModel):
    stored_name: str
    original_name: str
    logical_name: str
    format: Literal["csv", "xpt"]
    size_bytes: int
    sha256: str
    row_count: int | None = None
    columns: list[SourceColumnProfile] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class SDTMInputManifest(BaseModel):
    metadata_files: list[str] = Field(default_factory=list)
    blank_crf: str | None = None
    raw_datasets: list[RawDatasetInventory] = Field(default_factory=list)
    validation_report: str | None = None
    study_metadata: dict[str, str] = Field(default_factory=dict)


class ArtifactEvidence(BaseModel):
    name: str
    sha256: str
    size_bytes: int
    kind: str
    attempt_id: str | None = None


class SDTMWorkbenchState(BaseModel):
    lifecycle: SDTMLifecycle = Field(default_factory=SDTMLifecycle)
    inputs: SDTMInputManifest = Field(default_factory=SDTMInputManifest)
    artifacts: list[ArtifactEvidence] = Field(default_factory=list)
    updated_at: datetime | None = None
    limitations: list[str] = Field(default_factory=list)

