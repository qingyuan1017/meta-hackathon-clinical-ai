from __future__ import annotations

from .agents.runtime import verify_result
from .schemas import (
    EDCSourceSpecification,
    SDTMDomainMappingReview,
    SDTMPlan,
    SDTMVariableMappingReview,
    TLFAnalysisPlan,
    TLFInventoryPlan,
    TLFPlan,
)
from .use_cases.sdtm import SDTMUseCase
from .use_cases.tlf import TLFUseCase


def validate_review_result(
    workflow: str,
    stage: str,
    value: dict,
    options: dict,
    *,
    allow_repairable_sdtm_variable_mapping: bool = False,
) -> dict:
    if workflow == "sdtm" and stage == "edc_source":
        source = EDCSourceSpecification.model_validate(value)
        problems = verify_result("sdtm-source-normalization", source)
        if problems:
            raise ValueError(" ".join(problems))
        return source.model_dump(mode="json")
    if workflow == "sdtm" and stage == "domain_mapping":
        review = SDTMDomainMappingReview.model_validate(value)
        SDTMUseCase.validate_domain_mapping(review.source_spec, review.domain_mapping)
        return review.model_dump(mode="json")
    if workflow == "sdtm" and stage == "variable_mapping":
        review = SDTMVariableMappingReview.model_validate(value)
        SDTMUseCase.validate_domain_mapping(review.source_spec, review.domain_mapping)
        if not allow_repairable_sdtm_variable_mapping:
            SDTMUseCase.validate_variable_mapping(
                review.source_spec,
                review.domain_mapping,
                review.variable_mapping,
            )
        return review.model_dump(mode="json")
    if workflow == "sdtm" and stage in {"variable_mapping_domain", "rule_augmentation_domain"}:
        plan = SDTMPlan.model_validate(value)
        validated = SDTMUseCase().validate_result(plan.model_dump(mode="json"))
        return validated.model_dump(mode="json")
    if workflow == "tlf" and stage == "tlf_inventory":
        plan = TLFInventoryPlan.model_validate(value)
        TLFUseCase.validate_inventory_plan(plan)
        return plan.model_dump(mode="json")
    if workflow == "tlf" and stage == "tlf_shell":
        plan = TLFAnalysisPlan.model_validate(value)
        inventory_raw = options.get("tlf_inventory_plan")
        inventory = TLFInventoryPlan.model_validate(inventory_raw) if isinstance(inventory_raw, dict) else None
        TLFUseCase.validate_shell_plan(plan, inventory)
        return plan.model_dump(mode="json")
    if workflow == "tlf" and stage == "tlf_programming":
        plan = TLFPlan.model_validate(value)
        shell_raw = options.get("tlf_shell_plan")
        shell = TLFAnalysisPlan.model_validate(shell_raw) if isinstance(shell_raw, dict) else None
        TLFUseCase.validate_programming_plan(plan, shell)
        return plan.model_dump(mode="json")
    raise ValueError(f"Scoped revisions are not supported for {workflow} stage {stage}.")
