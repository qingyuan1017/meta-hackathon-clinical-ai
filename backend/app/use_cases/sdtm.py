from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents.runtime import ClinicalAgentRunner, verify_result
from ..agents.sdtm.agent import DOMAIN_MAPPING_AGENT, RULE_AUGMENTATION_AGENT, VARIABLE_MAPPING_AGENT
from ..artifacts import render_sdtm
from ..parsers import parse_source
from ..schemas import SDTMDomainMappingPlan, SDTMPlan, SDTMRuleAugmentationPlan, SDTMVariableMappingPlan
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor
from .utilities import normalize_languages


class SDTMUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="sdtm",
        title="SDTM mapping and code generation",
        description="Run domain mapping, variable/value-level mapping, and rule augmentation before rendering code and metadata artifacts.",
        skill_name="clinical-sdtm-artifacts",
        accepted_extensions=(".pdf", ".json", ".xlsx", ".docx", ".txt", ".md"),
        required_inputs=("Blank CRF PDF", "EDC JSON or XLSX", "Optional protocol context"),
        output_formats=("json", "xlsx", "xml", "pdf", "r", "sas", "zip"),
        mcp_dependencies=("cdisc-library",),
        stages=("Domain mapping", "Variable & value-level mapping", "Rule augmentation"),
        supports_languages=True,
    )
    result_model = SDTMPlan

    def validate_result(self, value: dict[str, Any]) -> BaseModel:
        validated = super().validate_result(value)
        problems = verify_result("sdtm", validated)
        if problems:
            raise ValueError(" ".join(problems))
        return validated

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        suffixes = [Path(name).suffix.lower() for name in filenames]
        if ".pdf" not in suffixes or not any(suffix in {".json", ".xlsx"} for suffix in suffixes):
            raise ValueError("SDTM generation requires a blank CRF PDF and EDC JSON or XLSX.")

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        crf, edc = self._required_inputs(context.inputs)
        context_inputs = [path for path in context.inputs if path not in {crf, edc}]
        source = (
            f"SOURCE DATA SPECIFICATION\n{parse_source(edc)}\n\n"
            f"OPTIONAL STUDY CONTEXT\n{self.join_sources(context_inputs)}"
        )
        stage_count = len(self.descriptor.stages)
        domain_outcome = await ClinicalAgentRunner(
            definition=DOMAIN_MAPPING_AGENT,
            result_model=SDTMDomainMappingPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 1 of 3: determine every raw/SDTM source dataset to target SDTM dataset/domain mapping. "
                "Do not perform variable mapping or code generation."
            ),
            source=source,
            options=context.options,
            stage=self.descriptor.stages[0],
            stage_index=1,
            stage_count=stage_count,
        )

        domain_json = domain_outcome.value.model_dump_json(indent=2)
        variable_outcome = await ClinicalAgentRunner(
            definition=VARIABLE_MAPPING_AGENT,
            result_model=SDTMVariableMappingPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 2 of 3: preserve the domain plan and determine variable-level mappings, value-level "
                "metadata, and the exact blank-CRF labels used for aCRF annotations. Do not generate code."
            ),
            source=(
                f"{source}\n\nSTAGE 1 DOMAIN MAPPING — PRESERVE\n{domain_json}\n\n"
                f"BLANK CRF TEXT\n{parse_source(crf)}"
            ),
            options=context.options,
            stage=self.descriptor.stages[1],
            stage_index=2,
            stage_count=stage_count,
            completed_stages=[self.descriptor.stages[0]],
            prior_events=domain_outcome.events,
        )

        variable_json = variable_outcome.value.model_dump_json(indent=2)
        rule_outcome = await ClinicalAgentRunner(
            definition=RULE_AUGMENTATION_AGENT,
            result_model=SDTMRuleAugmentationPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 3 of 3: add one source-preparation rule per target domain and one implementation rule per "
                "target variable. The augmented R and SAS expressions determine the rendered draft programs; "
                "do not restate or change prior mappings."
            ),
            source=(
                f"STAGE 1 DOMAIN MAPPING — PRESERVE\n{domain_json}\n\n"
                f"STAGE 2 VARIABLE AND VALUE-LEVEL MAPPING — PRESERVE\n{variable_json}"
            ),
            options=context.options,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages[:2]),
            prior_events=variable_outcome.events,
        )
        domain_plan = cast(SDTMDomainMappingPlan, domain_outcome.value)
        variable_plan = cast(SDTMVariableMappingPlan, variable_outcome.value)
        rule_plan = cast(SDTMRuleAugmentationPlan, rule_outcome.value)
        result = SDTMPlan(
            study_name=domain_plan.study_name,
            standard=domain_plan.standard,
            define_standard=variable_plan.define_standard,
            domain_mappings=domain_plan.domain_mappings,
            datasets=variable_plan.datasets,
            domain_rule_augmentations=rule_plan.domain_rule_augmentations,
            rule_augmentations=rule_plan.rule_augmentations,
            assumptions=list(
                dict.fromkeys(
                    [
                        *domain_plan.assumptions,
                        *variable_plan.assumptions,
                        *rule_plan.assumptions,
                    ]
                )
            ),
            unresolved_mappings=list(
                dict.fromkeys(
                    [
                        *domain_plan.unresolved_mappings,
                        *variable_plan.unresolved_mappings,
                        *rule_plan.unresolved_mappings,
                    ]
                )
            ),
        )
        problems = verify_result("sdtm", result)
        if problems:
            raise ValueError(" ".join(problems))
        warnings = [
            *domain_outcome.warnings,
            *variable_outcome.warnings,
            *rule_outcome.warnings,
            *self.result_warnings(result),
        ]
        return GeneratedContent(value=result, warnings=list(dict.fromkeys(warnings)))

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        crf, _ = self._required_inputs(inputs)
        return render_sdtm(cast(SDTMPlan, result), crf, output_dir, normalize_languages(options.get("languages")))

    @staticmethod
    def _required_inputs(inputs: list[Path]) -> tuple[Path, Path]:
        crf = next((path for path in inputs if path.suffix.lower() == ".pdf"), None)
        edc = next((path for path in inputs if path.suffix.lower() in {".json", ".xlsx"}), None)
        if crf is None or edc is None:
            raise ValueError("SDTM generation requires a blank CRF PDF and an EDC JSON or XLSX specification.")
        return crf, edc
