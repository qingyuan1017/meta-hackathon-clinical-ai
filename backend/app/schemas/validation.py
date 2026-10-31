from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


FindingStatus = Literal["open", "accepted", "corrected", "not_applicable", "explained"]


class ValidationFinding(BaseModel):
    finding_id: str
    provider: str
    provider_version: str = "not reported"
    standard_version: str | None = None
    controlled_terminology_version: str | None = None
    rule_id: str
    severity: str
    dataset: str | None = None
    variable: str | None = None
    record_keys: str | None = None
    message: str
    finding_status: FindingStatus = "open"
    disposition: str | None = None
    explanation: str | None = None
    reviewer: str | None = None
    approved_at: datetime | None = None


class ValidationFindingUpdate(BaseModel):
    finding_status: FindingStatus
    disposition: str | None = Field(default=None, max_length=4000)
    explanation: str | None = Field(default=None, max_length=8000)
    approved: bool = False
    reviewer: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_approval_evidence(self):
        if self.approved and not (self.reviewer or "").strip():
            raise ValueError("Reviewer is required for an approved disposition.")
        if self.finding_status in {"accepted", "not_applicable", "explained"} and not (self.explanation or "").strip():
            raise ValueError("An explanation is required for this finding status.")
        return self


class ValidationImportDiagnostics(BaseModel):
    source_name: str
    format: str
    rows_read: int = 0
    findings_imported: int = 0
    recognized_columns: dict[str, str] = Field(default_factory=dict)
    unknown_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ValidationRecord(BaseModel):
    validation_id: str
    provider: str
    provider_version: str = "not reported"
    status: Literal["imported", "running", "review_required", "completed_with_findings", "passed", "failed", "unavailable"]
    created_at: datetime
    source_artifact: str | None = None
    diagnostics: ValidationImportDiagnostics | None = None
    findings: list[ValidationFinding] = Field(default_factory=list)
    message: str | None = None


class ValidationRunRequest(BaseModel):
    provider: Literal["internal", "pinnacle21-cli"]


class CSDRGSection(BaseModel):
    heading: str
    body: str
    todos: list[str] = Field(default_factory=list)


class CSDRGDocument(BaseModel):
    study_name: str
    title: str = "Study Data Reviewer's Guide (Draft)"
    sections: list[CSDRGSection]
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime

