from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents import ClinicalAgentRunner, get_agent
from ..agents.runtime import verify_result
from ..agents.sdtm import SOURCE_NORMALIZATION_AGENT, STAGE_AGENTS
from ..artifacts import render_sdtm
from ..parsers import parse_edc_source, parse_source
from ..schemas import EDCSourceSpecification, SDTMDomainMappingPlan, SDTMPlan, SDTMRuleAugmentationPlan, SDTMVariableMappingPlan
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor
from .utilities import normalize_languages


_STAGE_AGENTS = dict(STAGE_AGENTS)


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

    async def prepare_review(self, context: UseCaseContext) -> GeneratedContent | None:
        if context.options.get("edc_source_spec") is not None:
            self._approved_source_spec(context.options)
            return None
        _, edc = self._required_inputs(context.inputs)
        outcome = await ClinicalAgentRunner(
            definition=SOURCE_NORMALIZATION_AGENT,
            result_model=EDCSourceSpecification,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Normalize the deterministically extracted EDC metadata into a complete source dataset and "
                "variable specification for human review. Preserve file, sheet, and row provenance; do not "
                "perform any SDTM target mapping."
            ),
            source=parse_edc_source(edc),
            options=context.options,
            stage="EDC source normalization",
        )
        return GeneratedContent(
            value=outcome.value,
            warnings=[*outcome.warnings, *self.result_warnings(outcome.value)],
        )

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        crf, edc = self._required_inputs(context.inputs)
        source_spec = self._approved_source_spec(context.options)
        agent_options = {key: value for key, value in context.options.items() if key != "edc_source_spec"}
        context_inputs = [path for path in context.inputs if path not in {crf, edc}]
        source = (
            f"USER-APPROVED EDC SOURCE SPECIFICATION\n{source_spec.model_dump_json(indent=2)}\n\n"
            f"OPTIONAL STUDY CONTEXT\n{self.join_sources(context_inputs)}"
        )
        stage_count = len(self.descriptor.stages)
        domain_outcome = await ClinicalAgentRunner(
            definition=_STAGE_AGENTS["domain-mapping"],
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
            options=agent_options,
            stage=self.descriptor.stages[0],
            stage_index=1,
            stage_count=stage_count,
        )

        domain_json = domain_outcome.value.model_dump_json(indent=2)
        variable_outcome = await ClinicalAgentRunner(
            definition=_STAGE_AGENTS["variable-mapping"],
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
            options=agent_options,
            stage=self.descriptor.stages[1],
            stage_index=2,
            stage_count=stage_count,
            completed_stages=[self.descriptor.stages[0]],
            prior_events=domain_outcome.events,
        )

        variable_json = variable_outcome.value.model_dump_json(indent=2)
        rule_outcome = await ClinicalAgentRunner(
            definition=_STAGE_AGENTS["rule-augmentation"],
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
            options=agent_options,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages[:2]),
            prior_events=variable_outcome.events,
        )
        rule_json = rule_outcome.value.model_dump_json(indent=2)
        lead_outcome = await ClinicalAgentRunner(
            definition=get_agent(self.descriptor.id),
            result_model=self.result_model,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Produce the final traceable SDTM artifact plan. Independently verify every field against the "
                "user-approved EDC source specification and blank CRF, reconcile the fallible ordered stage drafts below, and preserve "
                "every unresolved conflict or uncertainty. Domain and variable mappings must remain consistent "
                "with the augmented implementation rules.\n\n"
                f"CANDIDATE STAGE 1 DOMAIN MAPPING\n{domain_json}\n\n"
                f"CANDIDATE STAGE 2 VARIABLE AND VALUE-LEVEL MAPPING\n{variable_json}\n\n"
                f"CANDIDATE STAGE 3 RULE AUGMENTATION\n{rule_json}"
            ),
            source=f"{source}\n\nBLANK CRF TEXT\n{parse_source(crf)}",
            options=agent_options,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages),
            prior_events=rule_outcome.events,
        )
        result = cast(SDTMPlan, lead_outcome.value)
        problems = verify_result("sdtm", result)
        if problems:
            raise ValueError(" ".join(problems))
        warnings = [
            *domain_outcome.warnings,
            *variable_outcome.warnings,
            *rule_outcome.warnings,
            *lead_outcome.warnings,
            *self.result_warnings(result),
        ]
        return GeneratedContent(value=result, warnings=list(dict.fromkeys(warnings)))

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        crf, _ = self._required_inputs(inputs)
        source_spec = self._approved_source_spec(options)
        source_spec_path = output_dir / "edc-source-specification.json"
        source_spec_path.write_text(
            json.dumps(source_spec.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return [
            source_spec_path,
            *render_sdtm(cast(SDTMPlan, result), crf, output_dir, normalize_languages(options.get("languages"))),
        ]

    @staticmethod
    def _required_inputs(inputs: list[Path]) -> tuple[Path, Path]:
        crf = next((path for path in inputs if path.suffix.lower() == ".pdf"), None)
        edc = next((path for path in inputs if path.suffix.lower() in {".json", ".xlsx"}), None)
        if crf is None or edc is None:
            raise ValueError("SDTM generation requires a blank CRF PDF and an EDC JSON or XLSX specification.")
        return crf, edc

    @staticmethod
    def _approved_source_spec(options: dict[str, Any]) -> EDCSourceSpecification:
        raw = options.get("edc_source_spec")
        if not isinstance(raw, dict):
            raise ValueError("SDTM generation requires an approved EDC source specification.")
        validated = EDCSourceSpecification.model_validate(raw)
        problems = verify_result("sdtm-source-normalization", validated)
        if problems:
            raise ValueError(" ".join(problems))
        return validated
