from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents import ClinicalAgentRunner, get_agent
from ..agents.runtime import verify_result
from ..agents.sdtm import SOURCE_NORMALIZATION_AGENT, STAGE_AGENTS
from ..artifacts import render_sdtm
from ..csdrg import render_csdrg
from ..parsers import parse_edc_source, parse_source
from ..schemas import (
    EDCSourceSpecification,
    SDTMDomainMappingPlan,
    SDTMDomainMappingReview,
    SDTMPlan,
    SDTMRuleAugmentationPlan,
    SDTMVariableMappingPlan,
    SDTMVariableMappingReview,
)
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor
from .utilities import normalize_languages


_STAGE_AGENTS = dict(STAGE_AGENTS)


class SDTMUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="sdtm",
        title="SDTM mapping and code generation",
        description="Generate reviewed SDTM mappings, metadata, and code from EDC JSON/XLSX, with an optional blank CRF for aCRF output.",
        skill_name="clinical-sdtm-artifacts",
        accepted_extensions=(".pdf", ".json", ".xlsx", ".csv", ".xpt", ".docx", ".txt", ".md"),
        required_inputs=("EDC JSON or XLSX", "Optional blank CRF PDF", "Optional raw CSV/XPT datasets", "Optional validation report"),
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
        if not any(suffix in {".json", ".xlsx"} for suffix in suffixes):
            raise ValueError("SDTM generation requires an EDC JSON or XLSX specification. A blank CRF PDF is optional.")

    async def prepare_review(self, context: UseCaseContext) -> GeneratedContent | None:
        crf, edc = self._workflow_inputs(context.inputs)
        if context.options.get("edc_source_spec") is None:
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
                options=self._agent_options(context.options),
                stage="EDC source normalization",
            )
            return GeneratedContent(
                value=outcome.value,
                warnings=[*outcome.warnings, *self.result_warnings(outcome.value)],
                review_stage="edc_source",
            )

        source_spec = self._approved_source_spec(context.options)
        source, context_inputs = self._mapping_source(context, source_spec, crf, edc)
        agent_options = self._agent_options(context.options)
        stage_count = len(self.descriptor.stages)
        if context.options.get("sdtm_domain_mapping") is None:
            outcome = await ClinicalAgentRunner(
                definition=_STAGE_AGENTS["domain-mapping"],
                result_model=SDTMDomainMappingPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    "Stage 1 of 3: determine every raw/SDTM source dataset to target SDTM dataset/domain mapping. "
                    "Do not perform variable mapping or code generation. Return a draft for human review."
                ),
                source=f"{source}\n\nOPTIONAL STUDY CONTEXT\n{self.join_sources(context_inputs)}",
                options=agent_options,
                stage=self.descriptor.stages[0],
                stage_index=1,
                stage_count=stage_count,
            )
            mapping = cast(SDTMDomainMappingPlan, outcome.value)
            self.validate_domain_mapping(source_spec, mapping)
            return GeneratedContent(
                value=SDTMDomainMappingReview(source_spec=source_spec, domain_mapping=mapping),
                warnings=[*outcome.warnings, *self.result_warnings(mapping)],
                review_stage="domain_mapping",
            )

        domain_mapping = self._approved_domain_mapping(context.options, source_spec)
        if context.options.get("sdtm_variable_mapping") is None:
            crf_source = self._crf_source(crf)
            outcome = await ClinicalAgentRunner(
                definition=_STAGE_AGENTS["variable-mapping"],
                result_model=SDTMVariableMappingPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    "Stage 2 of 3: preserve the user-approved domain plan and determine variable-level mappings, "
                    "value-level metadata, and, only when a blank CRF is supplied, its exact labels for aCRF "
                    "annotations. When no blank CRF is supplied, leave crf_source_label null. Do not generate "
                    "code. Return a draft for human review."
                ),
                source=(
                    f"{source}\n\nUSER-APPROVED DOMAIN MAPPING — PRESERVE\n"
                    f"{domain_mapping.model_dump_json(indent=2)}\n\n{crf_source}\n\n"
                    f"OPTIONAL STUDY CONTEXT\n{self.join_sources(context_inputs)}"
                ),
                options=agent_options,
                stage=self.descriptor.stages[1],
                stage_index=2,
                stage_count=stage_count,
                completed_stages=[self.descriptor.stages[0]],
            )
            variable_mapping = cast(SDTMVariableMappingPlan, outcome.value)
            self.validate_variable_mapping(source_spec, domain_mapping, variable_mapping)
            return GeneratedContent(
                value=SDTMVariableMappingReview(
                    source_spec=source_spec,
                    domain_mapping=domain_mapping,
                    variable_mapping=variable_mapping,
                ),
                warnings=[*outcome.warnings, *self.result_warnings(variable_mapping)],
                review_stage="variable_mapping",
            )

        self._approved_variable_mapping(context.options, source_spec, domain_mapping)
        return None

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        crf, edc = self._workflow_inputs(context.inputs)
        source_spec = self._approved_source_spec(context.options)
        domain_mapping = self._approved_domain_mapping(context.options, source_spec)
        variable_mapping = self._approved_variable_mapping(context.options, source_spec, domain_mapping)
        agent_options = self._agent_options(context.options)
        source, context_inputs = self._mapping_source(context, source_spec, crf, edc)
        source = f"{source}\n\nOPTIONAL STUDY CONTEXT\n{self.join_sources(context_inputs)}"
        crf_source = self._crf_source(crf)
        stage_count = len(self.descriptor.stages)
        domain_json = domain_mapping.model_dump_json(indent=2)
        variable_json = variable_mapping.model_dump_json(indent=2)
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
                "user-approved EDC source specification and any supplied blank CRF, reconcile the fallible "
                "ordered stage drafts below, and preserve "
                "every unresolved conflict or uncertainty. Domain and variable mappings must remain consistent "
                "with the augmented implementation rules.\n\n"
                f"CANDIDATE STAGE 1 DOMAIN MAPPING\n{domain_json}\n\n"
                f"CANDIDATE STAGE 2 VARIABLE AND VALUE-LEVEL MAPPING\n{variable_json}\n\n"
                f"CANDIDATE STAGE 3 RULE AUGMENTATION\n{rule_json}"
            ),
            source=f"{source}\n\n{crf_source}",
            options=agent_options,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages),
            prior_events=rule_outcome.events,
        )
        result = cast(SDTMPlan, lead_outcome.value)
        problems = verify_result("sdtm", result)
        if result.domain_mappings != domain_mapping.domain_mappings:
            problems.append("Final generation changed the user-approved domain mapping.")
        if result.datasets != variable_mapping.datasets:
            problems.append("Final generation changed the user-approved variable or value-level mapping.")
        if result.study_name != variable_mapping.study_name:
            problems.append("Final generation changed the user-approved study name.")
        if result.standard != variable_mapping.standard or result.define_standard != variable_mapping.define_standard:
            problems.append("Final generation changed the user-approved SDTM or Define-XML standard.")
        if problems:
            raise ValueError(" ".join(problems))
        warnings = [
            *rule_outcome.warnings,
            *lead_outcome.warnings,
            *self.result_warnings(result),
        ]
        if crf is None:
            warnings.append("Blank CRF was not supplied; annotated-crf.pdf was not generated.")
        return GeneratedContent(value=result, warnings=list(dict.fromkeys(warnings)))

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        crf, _ = self._workflow_inputs(inputs)
        source_spec = self._approved_source_spec(options)
        source_spec_path = output_dir / "edc-source-specification.json"
        source_spec_path.write_text(
            json.dumps(source_spec.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        paths = [
            source_spec_path,
            *render_sdtm(cast(SDTMPlan, result), crf, output_dir, normalize_languages(options.get("languages"))),
        ]
        paths.extend(render_csdrg(output_dir.parent, cast(SDTMPlan, result), output_dir))
        return paths

    @staticmethod
    def _workflow_inputs(inputs: list[Path]) -> tuple[Path | None, Path]:
        crf = next((path for path in inputs if path.suffix.lower() == ".pdf"), None)
        edc = next((path for path in inputs if path.suffix.lower() in {".json", ".xlsx"}), None)
        if edc is None:
            raise ValueError("SDTM generation requires an EDC JSON or XLSX specification. A blank CRF PDF is optional.")
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

    @classmethod
    def _approved_domain_mapping(
        cls,
        options: dict[str, Any],
        source_spec: EDCSourceSpecification,
    ) -> SDTMDomainMappingPlan:
        raw = options.get("sdtm_domain_mapping")
        if not isinstance(raw, dict):
            raise ValueError("SDTM generation requires an approved domain mapping.")
        validated = SDTMDomainMappingPlan.model_validate(raw)
        cls.validate_domain_mapping(source_spec, validated)
        return validated

    @classmethod
    def _approved_variable_mapping(
        cls,
        options: dict[str, Any],
        source_spec: EDCSourceSpecification,
        domain_mapping: SDTMDomainMappingPlan,
    ) -> SDTMVariableMappingPlan:
        raw = options.get("sdtm_variable_mapping")
        if not isinstance(raw, dict):
            raise ValueError("SDTM generation requires an approved variable and value-level mapping.")
        validated = SDTMVariableMappingPlan.model_validate(raw)
        cls.validate_variable_mapping(source_spec, domain_mapping, validated)
        return validated

    @staticmethod
    def validate_domain_mapping(
        source_spec: EDCSourceSpecification,
        mapping: SDTMDomainMappingPlan,
    ) -> None:
        problems = verify_result("sdtm-domain-mapping", mapping)
        sources = {dataset.name.upper(): dataset for dataset in source_spec.datasets}
        mapped_sources = {item.source_dataset.upper() for item in mapping.domain_mappings}
        missing = sorted(set(sources) - mapped_sources)
        unknown = sorted(mapped_sources - set(sources))
        if missing:
            problems.append(f"Every source dataset must be mapped; missing: {', '.join(missing)}.")
        if unknown:
            problems.append(f"Domain mapping references unknown source datasets: {', '.join(unknown)}.")
        for item in mapping.domain_mappings:
            source_dataset = sources.get(item.source_dataset.upper())
            if source_dataset and item.source_type != source_dataset.source_type:
                problems.append(
                    f"{item.source_dataset} source type must remain {source_dataset.source_type}, not {item.source_type}."
                )
        if problems:
            raise ValueError(" ".join(problems))

    @staticmethod
    def validate_variable_mapping(
        source_spec: EDCSourceSpecification,
        domain_mapping: SDTMDomainMappingPlan,
        mapping: SDTMVariableMappingPlan,
    ) -> None:
        problems = verify_result("sdtm-variable-mapping", mapping)
        mapped_sources: dict[str, set[str]] = {}
        for item in domain_mapping.domain_mappings:
            mapped_sources.setdefault(item.target_domain.upper(), set()).add(item.source_dataset.upper())
        dataset_domains = {dataset.domain.upper() for dataset in mapping.datasets}
        target_domains = set(mapped_sources)
        missing = sorted(target_domains - dataset_domains)
        extra = sorted(dataset_domains - target_domains)
        if missing:
            problems.append(f"Every approved target domain needs variable mapping; missing: {', '.join(missing)}.")
        if extra:
            problems.append(f"Variable mapping contains unapproved target domains: {', '.join(extra)}.")
        known_sources = {dataset.name.upper() for dataset in source_spec.datasets}
        for dataset in mapping.datasets:
            allowed_sources = mapped_sources.get(dataset.domain.upper(), set())
            for variable in dataset.variables:
                source_name = variable.source_dataset.upper()
                if source_name not in known_sources:
                    problems.append(
                        f"{dataset.domain}.{variable.name} references unknown source dataset {variable.source_dataset}."
                    )
                elif source_name not in allowed_sources:
                    problems.append(
                        f"{dataset.domain}.{variable.name} source {variable.source_dataset} is not approved for {dataset.domain}."
                    )
        if problems:
            raise ValueError(" ".join(problems))

    @staticmethod
    def _agent_options(options: dict[str, Any]) -> dict[str, Any]:
        excluded = {"edc_source_spec", "sdtm_domain_mapping", "sdtm_variable_mapping"}
        return {key: value for key, value in options.items() if key not in excluded and not key.startswith("_")}

    @staticmethod
    def _crf_source(crf: Path | None) -> str:
        if crf is None:
            return "BLANK CRF NOT SUPPLIED\nDo not invent CRF labels or annotations. Leave crf_source_label null."
        return f"BLANK CRF TEXT\n{parse_source(crf)}"

    @staticmethod
    def _mapping_source(
        context: UseCaseContext,
        source_spec: EDCSourceSpecification,
        crf: Path | None,
        edc: Path,
    ) -> tuple[str, list[Path]]:
        excluded_inputs = {edc, *([crf] if crf is not None else [])}
        context_inputs = [
            path for path in context.inputs
            if path not in excluded_inputs
            and path.suffix.lower() not in {".csv", ".xpt"}
            and not path.name.startswith("validation-")
        ]
        source = f"USER-APPROVED EDC SOURCE SPECIFICATION\n{source_spec.model_dump_json(indent=2)}"
        return source, context_inputs
