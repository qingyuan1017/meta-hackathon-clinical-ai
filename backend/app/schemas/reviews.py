from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .edc import EDCSourceSpecification
from .sdtm import SDTMDomainMappingPlan, SDTMVariableMappingPlan
from .tlf import TLFAnalysisPlan, TLFInventoryPlan, TLFPlan


class ReviewVariableScope(BaseModel):
    domain: str = Field(min_length=1, max_length=8)
    variable: str = Field(min_length=1, max_length=32)
    fields: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("domain", "variable")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().upper()


class ReviewScope(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=200)
    source_datasets: list[str] = Field(default_factory=list, max_length=100)
    target_domains: list[str] = Field(default_factory=list, max_length=50)
    variables: list[ReviewVariableScope] = Field(default_factory=list, max_length=200)

    @field_validator("source_datasets", "target_domains")
    @classmethod
    def normalize_identifiers(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))

    @field_validator("paths")
    @classmethod
    def normalize_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            path = value.strip()
            if not path.startswith("/") or ".." in path:
                raise ValueError("Review scope paths must be absolute JSON pointers.")
            normalized.append(path.rstrip("/") or "/")
        return list(dict.fromkeys(normalized))


class ReviewFeedbackUpdate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    scope: ReviewScope | None = None
    baseline_revision: str | None = Field(default=None, min_length=64, max_length=64)
    current_result: dict[str, Any] | None = None


class ReviewScopeProposalRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    current_result: dict[str, Any] | None = None


class ReviewScopeProposal(BaseModel):
    stage: str
    scope: ReviewScope
    matched_terms: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    explanation: str


class ReviewPatchOperation(BaseModel):
    path: str
    before: Any = None
    after: Any = None


class ReviewPatchRead(BaseModel):
    transaction_id: str
    status: Literal["generating", "proposed", "approved", "rejected", "conflict"]
    stage: str
    message: str
    scope: ReviewScope
    baseline_revision: str
    proposed_revision: str | None = None
    operations: list[ReviewPatchOperation] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    submitted_at: datetime
    decided_at: datetime | None = None
    reviewer: str | None = None


class ReviewPatchDecision(BaseModel):
    approved: bool
    expected_revision: str = Field(min_length=64, max_length=64)
    current_result: dict[str, Any]
    reviewer: str = Field(default="Workbench reviewer", min_length=1, max_length=160)


class VoiceTranscriptionRead(BaseModel):
    transcript: str
    model: str
    duration_ms: int | None = None
    session_id: str | None = None


class EDCSourceSpecificationUpdate(BaseModel):
    source_spec: EDCSourceSpecification


class SDTMDomainMappingUpdate(BaseModel):
    domain_mapping: SDTMDomainMappingPlan


class SDTMVariableMappingUpdate(BaseModel):
    variable_mapping: SDTMVariableMappingPlan


class SDTMDomainRerunRequest(BaseModel):
    stage: Literal["domain_mapping", "variable_mapping", "rule_augmentation"]
    domain: str | None = Field(default=None, min_length=2, max_length=8)
    guidance: str | None = Field(default=None, min_length=1, max_length=4000)
    execution_attempt_id: str | None = Field(default=None, pattern=r"^attempt-[a-f0-9]{12}$")
    scope: ReviewScope | None = None

    @field_validator("guidance")
    @classmethod
    def normalize_guidance(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None

    @model_validator(mode="after")
    def require_domain_for_domain_scoped_stages(self):
        if self.stage != "domain_mapping" and self.domain is None:
            raise ValueError("A target domain is required for variable or rule/code revision.")
        if self.stage == "domain_mapping" and self.domain is not None:
            raise ValueError("Domain mapping revision operates on the complete source-to-domain plan.")
        if self.execution_attempt_id and self.stage != "rule_augmentation":
            raise ValueError("Execution evidence can be attached only to a rule/code revision.")
        return self


class CSDRGAgentRevisionRequest(BaseModel):
    guidance: str = Field(min_length=1, max_length=4000)
    scope: ReviewScope | None = None

    @field_validator("guidance")
    @classmethod
    def normalize_csdrg_guidance(cls, value: str) -> str:
        return value.strip()


class TLFShellPlanUpdate(BaseModel):
    shell_plan: TLFAnalysisPlan


class TLFInventoryPlanUpdate(BaseModel):
    inventory_plan: TLFInventoryPlan


class TLFProgrammingPlanUpdate(BaseModel):
    programming_plan: TLFPlan
