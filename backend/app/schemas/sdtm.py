from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .edc import EDCSourceSpecification


class SDTMDomainMapping(BaseModel):
    source_dataset: str = Field(description="Raw or existing-SDTM source dataset identifier")
    source_type: Literal["raw", "sdtm"] = "raw"
    target_domain: str = Field(description="Target SDTM dataset/domain identifier, such as DM or VS")
    relationship: Literal["direct", "split", "merge", "derived"] = "direct"
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
    source_dataset: str | None = Field(
        default=None,
        description="Approved source dataset when the target has a direct single-field source; null for assigned or derived values without one raw source",
    )
    source_field: str | None = Field(
        default=None,
        description="Source field paired with source_dataset; null for assigned or derived values without one raw source",
    )
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


class SDTMDataset(BaseModel):
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
    unmapped_datasets: list[SDTMUnmappedDataset] = Field(default_factory=list)
    domain_rule_augmentations: list[SDTMDomainRuleAugmentation] = Field(min_length=1)
    rule_augmentations: list[SDTMRuleAugmentation] = Field(min_length=1)
