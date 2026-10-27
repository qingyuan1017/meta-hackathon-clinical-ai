from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


DISCLAIMER = (
    "DRAFT — HACKATHON DEMONSTRATION ONLY. Not validated for clinical or regulatory use. "
    "Qualified experts must review all content."
)


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


class DocumentSection(BaseModel):
    heading: str
    body: str
    review_notes: list[str] = Field(default_factory=list)


class ClinicalDocument(BaseModel):
    document_type: str
    title: str
    version: str = "Draft 0.1"
    executive_summary: str
    sections: list[DocumentSection]
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class EDCVisit(BaseModel):
    name: str
    timing: str = "Not specified"
    forms: list[str] = Field(default_factory=list)


class EDCField(BaseModel):
    field_id: str
    label: str
    data_type: Literal["text", "integer", "decimal", "date", "datetime", "boolean", "coded"] = "text"
    required: bool = False
    codelist: str | None = None
    derivation: str | None = None
    instructions: str | None = None


class EDCForm(BaseModel):
    form_id: str
    name: str
    purpose: str = ""
    fields: list[EDCField]


class CodeList(BaseModel):
    name: str
    values: list[str]


class EditCheck(BaseModel):
    check_id: str
    form: str
    field: str
    condition: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class EDCDesign(BaseModel):
    study_name: str
    visits: list[EDCVisit]
    forms: list[EDCForm]
    codelists: list[CodeList] = Field(default_factory=list)
    edit_checks: list[EditCheck] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SDTMVariable(BaseModel):
    name: str
    label: str
    data_type: Literal["Char", "Num"] = "Char"
    source_field: str
    origin: str = "CRF"
    mapping_expression: str = "Direct"
    controlled_terms: list[str] = Field(default_factory=list)


class SDTMDataset(BaseModel):
    domain: str
    description: str
    structure: str = "One record per subject per event"
    key_variables: list[str] = Field(default_factory=lambda: ["STUDYID", "USUBJID"])
    variables: list[SDTMVariable]


class SDTMPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    define_standard: str = "Define-XML 2.1"
    datasets: list[SDTMDataset]
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class TLFColumn(BaseModel):
    heading: str
    source: str = "TODO: confirm source"
    statistic: str = ""


class TLFSpec(BaseModel):
    output_id: str
    output_type: Literal["table", "listing", "figure"]
    title: str
    population: str = "TODO: confirm population"
    columns: list[TLFColumn] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    programming_notes: list[str] = Field(default_factory=list)


class TLFPlan(BaseModel):
    study_name: str
    analysis_standard: str = "ADaM metadata supplied by user"
    outputs: list[TLFSpec]
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class ArtifactRead(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    download_url: str


class JobRead(BaseModel):
    id: str
    workflow: str
    title: str
    status: str
    model_name: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    result: dict | list | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    artifacts: list[ArtifactRead] = Field(default_factory=list)


class JobList(BaseModel):
    items: list[JobRead]
    total: int
    page: int
    page_size: int


class JobResultUpdate(BaseModel):
    result: dict[str, Any]


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
    supports_languages: bool
    supports_result_editing: bool
    result_schema: dict[str, Any]


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
    name: str | None = None
    ok: bool | None = None
    error: str | None = None


class AgentProgressRead(BaseModel):
    agent_id: str
    workflow: str
    status: str
    turn: int
    max_turns: int
    total_source_chunks: int
    read_source_chunks: list[int]
    events: list[AgentEventRead]


class HealthRead(BaseModel):
    status: str
    database: str
    storage: str
    meta_configured: bool
    meta_base_url: str
    meta_model: str | None
    disclaimer: str = DISCLAIMER
