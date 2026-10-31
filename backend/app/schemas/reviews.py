from __future__ import annotations

from pydantic import BaseModel, Field

from .edc import EDCSourceSpecification
from .sdtm import SDTMDomainMappingPlan, SDTMVariableMappingPlan
from .tlf import TLFAnalysisPlan, TLFInventoryPlan, TLFPlan


class ReviewFeedbackUpdate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


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


class TLFShellPlanUpdate(BaseModel):
    shell_plan: TLFAnalysisPlan


class TLFInventoryPlanUpdate(BaseModel):
    inventory_plan: TLFInventoryPlan


class TLFProgrammingPlanUpdate(BaseModel):
    programming_plan: TLFPlan
