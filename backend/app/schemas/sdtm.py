from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .edc import EDCSourceSpecification


class SDTMDomainMapping(BaseModel):
    source_dataset: str = Field(description="Raw or existing-SDTM source dataset identifier")
    source_type: Literal["raw", "sdtm"] = "raw"
    target_domain: str = Field(description="Target SDTM dataset/domain identifier, such as DM or VS")
    relationship: Literal["direct", "stack", "join", "split", "derived"] = "direct"
    rationale: str


class SDTMUnmappedDataset(BaseModel):
    source_dataset: str = Field(description="Source dataset intentionally not mapped to SDTM")
    rationale: str = Field(description="Human-reviewable reason the source is outside the SDTM mapping scope")


class SDTMDomainMappingPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    domain_mappings: list[SDTMDomainMapping] = Field(min_length=1)
    unmapped_datasets: list[SDTMUnmappedDataset] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMSourceReference(BaseModel):
    dataset: str = Field(description="Approved source dataset identifier")
    variable: str = Field(description="Approved source variable identifier")
    role: Literal["value", "join_key", "lookup", "filter", "timing", "grouping", "sequence"] = "value"


class SDTMJoinKey(BaseModel):
    left: str
    right: str


class SDTMStackColumnSource(BaseModel):
    input: str = Field(description="Source dataset or earlier step identifier")
    variable: str


class SDTMStackColumn(BaseModel):
    target: str
    sources: list[SDTMStackColumnSource] = Field(min_length=1)


class SDTMTransposeValue(BaseModel):
    source_variable: str
    name_value: str


class SDTMAggregation(BaseModel):
    output_variable: str
    operation: Literal["count", "sum", "min", "max", "mean", "first", "last"]
    source_variable: str | None = None


class SDTMRecordStep(BaseModel):
    step_id: str
    operation: Literal["read", "stack", "join", "transpose", "filter", "deduplicate", "aggregate"]
    description: str
    output: str
    inputs: list[str] = Field(default_factory=list)
    source_dataset: str | None = None
    column_alignment: list[SDTMStackColumn] = Field(default_factory=list)
    left: str | None = None
    right: str | None = None
    join_type: Literal["left", "inner", "full", "right"] | None = None
    join_keys: list[SDTMJoinKey] = Field(default_factory=list)
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"] | None = None
    id_variables: list[str] = Field(default_factory=list)
    value_variables: list[str] = Field(default_factory=list)
    name_variable: str | None = None
    value_variable: str | None = None
    transpose_values: list[SDTMTransposeValue] = Field(default_factory=list)
    condition: str | None = None
    sas_condition: str | None = None
    keys: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    keep: Literal["first", "last"] = "first"
    group_by: list[str] = Field(default_factory=list)
    aggregations: list[SDTMAggregation] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)


class SDTMRecordPlan(BaseModel):
    steps: list[SDTMRecordStep] = Field(min_length=1)
    output_step: str


class SDTMValueLevelMetadata(BaseModel):
    where_clause: str
    label: str
    data_type: Literal["Char", "Num"] = "Char"
    origin: str = "CRF"
    mapping_expression: str
    sources: list[SDTMSourceReference] = Field(default_factory=list)
    controlled_terms: list[str] = Field(default_factory=list)


class SDTMVariable(BaseModel):
    name: str
    label: str
    data_type: Literal["Char", "Num"] = "Char"
    mapping_type: Literal["direct", "assigned", "derived", "coalesce", "lookup", "transpose", "aggregate"] = "direct"
    sources: list[SDTMSourceReference] = Field(default_factory=list)
    origin: str = "CRF"
    mapping_expression: str = "Direct"
    controlled_terms: list[str] = Field(default_factory=list)
    value_level_metadata: list[SDTMValueLevelMetadata] = Field(default_factory=list)
    crf_source_label: str | None = None
    length: int | None = Field(default=None, ge=1, le=32767)
    format: str | None = None
    role: str | None = None
    core: Literal["Req", "Exp", "Perm"] | None = None
    comment: str | None = None


class SDTMVariableDataset(BaseModel):
    domain: str
    description: str
    structure: str = "One record per subject per event"
    key_variables: list[str] = Field(default_factory=lambda: ["STUDYID", "USUBJID"])
    dataset_class: str = "Special Purpose"
    purpose: str = "Tabulation"
    variables: list[SDTMVariable] = Field(min_length=1)
    review_assumptions: list[str] = Field(
        default_factory=list,
        description="Human-reviewable assumptions owned by this target-domain mapping batch",
    )
    review_unresolved_mappings: list[str] = Field(
        default_factory=list,
        description="Human-reviewable unresolved decisions owned by this target-domain mapping batch",
    )


class SDTMDataset(SDTMVariableDataset):
    record_plan: SDTMRecordPlan = Field(
        description="Deterministic record-construction pipeline supplied by the rule/code stage",
    )


class SDTMVariableMappingPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    define_standard: str = "Define-XML 2.1"
    datasets: list[SDTMVariableDataset] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMDomainMappingReview(BaseModel):
    source_spec: EDCSourceSpecification
    domain_mapping: SDTMDomainMappingPlan


class SDTMVariableMappingReview(BaseModel):
    source_spec: EDCSourceSpecification
    domain_mapping: SDTMDomainMappingPlan
    variable_mapping: SDTMVariableMappingPlan


class SDTMRuleAugmentation(BaseModel):
    rule_id: str
    target_domain: str
    target_variable: str
    description: str
    logic: str
    r_expression: str
    sas_expression: str
    review_notes: list[str] = Field(default_factory=list)


class SDTMDomainRecordPlan(BaseModel):
    target_domain: str
    record_plan: SDTMRecordPlan


class SDTMRuleAugmentationPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    record_plans: list[SDTMDomainRecordPlan] = Field(min_length=1)
    rule_augmentations: list[SDTMRuleAugmentation] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)


class SDTMPlan(BaseModel):
    study_name: str
    standard: str = "SDTMIG 3.4"
    define_standard: str = "Define-XML 2.1"
    datasets: list[SDTMDataset] = Field(min_length=1)
    domain_mappings: list[SDTMDomainMapping] = Field(min_length=1)
    unmapped_datasets: list[SDTMUnmappedDataset] = Field(default_factory=list)
    rule_augmentations: list[SDTMRuleAugmentation] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    unresolved_mappings: list[str] = Field(default_factory=list)
