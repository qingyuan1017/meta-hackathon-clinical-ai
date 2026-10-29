from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class EDCSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EDCSourceProvenance(EDCSourceModel):
    file: str = Field(min_length=1)
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)


class EDCSourceVariable(EDCSourceModel):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    data_type: Literal["text", "integer", "decimal", "date", "datetime", "boolean", "coded", "unknown"] = "unknown"
    length: int | None = Field(default=None, ge=1)
    format: str | None = None
    required: bool = False
    codelist: str | None = None
    form_id: str | None = None
    question: str | None = None
    provenance: EDCSourceProvenance


class EDCSourceDataset(EDCSourceModel):
    name: str = Field(min_length=1)
    label: str = Field(min_length=1)
    source_type: Literal["raw", "sdtm"] = "raw"
    structure: str = "Not specified"
    key_variables: list[str] = Field(default_factory=list)
    variables: list[EDCSourceVariable] = Field(min_length=1)
    provenance: EDCSourceProvenance


class EDCSourceCodeList(EDCSourceModel):
    name: str = Field(min_length=1)
    values: list[str] = Field(default_factory=list)


class EDCSourceSpecification(EDCSourceModel):
    study_name: str = Field(min_length=1)
    datasets: list[EDCSourceDataset] = Field(min_length=1)
    codelists: list[EDCSourceCodeList] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class SDTMDomainMapping(BaseModel):
    source_dataset: str = Field(description="Raw or existing-SDTM source dataset identifier")
    source_type: Literal["raw", "sdtm"] = "raw"
    target_domain: str = Field(description="Target SDTM dataset/domain identifier, such as DM or VS")
    relationship: Literal["direct", "split", "merge", "derived"] = "direct"
    rationale: str


class SDTMDomainMappingPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    domain_mappings: list[SDTMDomainMapping] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMValueLevelMetadata(BaseModel):
    where_clause: str
    label: str
    data_type: Literal["Char", "Num"] = "Char"
    origin: str = "CRF"
    mapping_expression: str
    controlled_terms: list[str] = Field(default_factory=list)


class SDTMVariable(BaseModel):
    name: str
    label: str
    data_type: Literal["Char", "Num"] = "Char"
    source_dataset: str
    source_field: str
    origin: str = "CRF"
    mapping_expression: str = "Direct"
    controlled_terms: list[str] = Field(default_factory=list)
    value_level_metadata: list[SDTMValueLevelMetadata] = Field(default_factory=list)
    crf_source_label: str | None = None


class SDTMDataset(BaseModel):
    domain: str
    description: str
    structure: str = "One record per subject per event"
    key_variables: list[str] = Field(default_factory=lambda: ["STUDYID", "USUBJID"])
    variables: list[SDTMVariable] = Field(min_length=1)


class SDTMVariableMappingPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    define_standard: str = "Define-XML 2.1"
    datasets: list[SDTMDataset] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMDomainMappingReview(BaseModel):
    source_spec: EDCSourceSpecification
    domain_mapping: SDTMDomainMappingPlan


class SDTMVariableMappingReview(BaseModel):
    source_spec: EDCSourceSpecification
    domain_mapping: SDTMDomainMappingPlan
    variable_mapping: SDTMVariableMappingPlan


class SDTMDomainRuleAugmentation(BaseModel):
    rule_id: str
    target_domain: str
    source_datasets: list[str] = Field(min_length=1)
    description: str
    logic: str
    r_input_expression: str
    sas_input_statement: str
    review_notes: list[str] = Field(default_factory=list)


class SDTMRuleAugmentation(BaseModel):
    rule_id: str
    target_domain: str
    target_variable: str
    source_dependencies: list[str] = Field(default_factory=list)
    description: str
    logic: str
    r_expression: str
    sas_expression: str
    review_notes: list[str] = Field(default_factory=list)


class SDTMRuleAugmentationPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    domain_rule_augmentations: list[SDTMDomainRuleAugmentation] = Field(min_length=1)
    rule_augmentations: list[SDTMRuleAugmentation] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMPlan(SDTMVariableMappingPlan):
    domain_mappings: list[SDTMDomainMapping] = Field(min_length=1)
    domain_rule_augmentations: list[SDTMDomainRuleAugmentation] = Field(min_length=1)
    rule_augmentations: list[SDTMRuleAugmentation] = Field(min_length=1)


class TLFInventoryOutput(BaseModel):
    output_id: str
    output_type: Literal["table", "listing", "figure"]
    title: str
    section: str = "Not specified"
    purpose: str = "Not specified"
    population: str = "TODO: confirm population"
    source_reference: str = "TODO: confirm SAP/protocol reference"


class TLFInventoryPlan(BaseModel):
    study_name: str
    analysis_standard: str = "ADaM metadata supplied by user"
    outputs: list[TLFInventoryOutput] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFSourceVariable(BaseModel):
    dataset: str
    variable: str
    role: str = "Analysis input"
    derivation: str = "Direct"


class TLFColumn(BaseModel):
    column_id: str = "COL"
    heading: str
    source: str = "TODO: confirm source"
    statistic: str = ""
    format: str = "TODO: confirm format"


class TLFRow(BaseModel):
    row_id: str
    label: str
    source: str = "TODO: confirm source"
    statistic: str = ""
    condition: str = ""
    format: str = "TODO: confirm format"


class TLFFigureSpec(BaseModel):
    geometry: str = "TODO: confirm figure type"
    x_axis: str = "TODO: confirm x-axis"
    y_axis: str = "TODO: confirm y-axis"
    group: str = ""
    panel: str = ""


class TLFSpec(BaseModel):
    output_id: str
    output_type: Literal["table", "listing", "figure"]
    title: str
    section: str = "Not specified"
    purpose: str = "Not specified"
    population: str = "TODO: confirm population"
    population_filter: str = "TODO: confirm population filter"
    analysis_datasets: list[str] = Field(default_factory=list)
    source_variables: list[TLFSourceVariable] = Field(default_factory=list)
    selection_criteria: list[str] = Field(default_factory=list)
    treatment_variable: str = "TODO: confirm treatment variable"
    analysis_method: str = "TODO: confirm analysis method"
    columns: list[TLFColumn] = Field(default_factory=list)
    rows: list[TLFRow] = Field(default_factory=list)
    figure: TLFFigureSpec | None = None
    sort_order: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    display_notes: list[str] = Field(default_factory=list)
    programming_notes: list[str] = Field(default_factory=list)
    source_reference: str = "TODO: confirm SAP/protocol reference"
    readiness: Literal["ready", "blocked"] = "blocked"
    blocking_items: list[str] = Field(default_factory=list)


class TLFAnalysisPlan(BaseModel):
    study_name: str
    analysis_standard: str = "ADaM metadata supplied by user"
    outputs: list[TLFSpec] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFProgramSpec(BaseModel):
    output_id: str
    input_datasets: list[str] = Field(default_factory=list)
    derivation_steps: list[str] = Field(default_factory=list)
    r_code: str = "# TODO: implement reviewed output logic"
    sas_code: str = "/* TODO: implement reviewed output logic */"
    review_notes: list[str] = Field(default_factory=list)


class TLFProgrammingPlan(BaseModel):
    study_name: str
    programs: list[TLFProgramSpec] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)


class TLFPlan(TLFAnalysisPlan):
    programs: list[TLFProgramSpec] = Field(min_length=1)


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
    review_stage: Literal["edc_source", "domain_mapping", "variable_mapping", "tlf_shell"] | None = None
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


class EDCSourceSpecificationUpdate(BaseModel):
    source_spec: EDCSourceSpecification


class SDTMDomainMappingUpdate(BaseModel):
    domain_mapping: SDTMDomainMappingPlan


class SDTMVariableMappingUpdate(BaseModel):
    variable_mapping: SDTMVariableMappingPlan


class TLFShellPlanUpdate(BaseModel):
    shell_plan: TLFAnalysisPlan


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
    stage: str | None = None
    ok: bool | None = None
    error: str | None = None


class AgentProgressRead(BaseModel):
    agent_id: str
    workflow: str
    status: str
    turn: int
    max_turns: int
    stage: str | None = None
    stage_index: int = 1
    stage_count: int = 1
    completed_stages: list[str] = Field(default_factory=list)
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
