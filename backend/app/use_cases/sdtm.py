from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents import ClinicalAgentRunner
from ..agents.runtime import verify_result
from ..agents.sdtm import SOURCE_NORMALIZATION_AGENT, STAGE_AGENTS
from ..artifacts import render_sdtm
from ..csdrg import render_csdrg
from ..edc_normalization import EDCJSONNormalization, normalize_edc_json
from ..parsers import chunk_text, parse_edc_source, parse_source
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
            if edc.suffix.lower() == ".json":
                normalized = normalize_edc_json(edc)
                if normalized is not None:
                    problems = verify_result("sdtm-source-normalization", normalized.specification)
                    if problems:
                        raise ValueError(" ".join(problems))
                    self._write_normalization_trace(context, edc, normalized)
                    review_warning = []
                    if context.options.get("review_feedback"):
                        review_warning.append(
                            "The complete JSON inventory was regenerated deterministically after review feedback; "
                            "confirm the revised source draft at the human approval gate."
                        )
                    return GeneratedContent(
                        value=normalized.specification,
                        warnings=[
                            *normalized.warnings,
                            *review_warning,
                            *self.result_warnings(normalized.specification),
                        ],
                        review_stage="edc_source",
                    )

                extracted = parse_edc_source(edc)
                chunk_count = len(chunk_text(extracted, context.settings.chunk_characters))
                complete_read_limit = min(
                    context.settings.max_source_chunks,
                    max(context.settings.agent_max_turns - 2, 1),
                )
                if chunk_count > complete_read_limit:
                    raise ValueError(
                        "The complete EDC JSON uses an unrecognized metadata structure and requires "
                        f"{chunk_count} source chunks, exceeding the configured complete-read limit of "
                        f"{complete_read_limit}. The source was not truncated. Provide a supported "
                        "dataset/variable structure or normalize it at the source-review gate."
                    )
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
        context_inputs = self._mapping_context_inputs(context, crf, edc)
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
                source=self._domain_mapping_source(source_spec, context_inputs),
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
            variable_mapping, variable_warnings = await self._generate_variable_mapping_batches(
                context,
                source_spec=source_spec,
                domain_mapping=domain_mapping,
                context_inputs=context_inputs,
                crf=crf,
                agent_options=agent_options,
                stage_count=stage_count,
            )
            self.validate_variable_mapping(source_spec, domain_mapping, variable_mapping)
            return GeneratedContent(
                value=SDTMVariableMappingReview(
                    source_spec=source_spec,
                    domain_mapping=domain_mapping,
                    variable_mapping=variable_mapping,
                ),
                warnings=[*variable_warnings, *self.result_warnings(variable_mapping)],
                review_stage="variable_mapping",
            )

        self._approved_variable_mapping(context.options, source_spec, domain_mapping)
        return None

    async def _generate_variable_mapping_batches(
        self,
        context: UseCaseContext,
        *,
        source_spec: EDCSourceSpecification,
        domain_mapping: SDTMDomainMappingPlan,
        context_inputs: list[Path],
        crf: Path | None,
        agent_options: dict[str, Any],
        stage_count: int,
    ) -> tuple[SDTMVariableMappingPlan, list[str]]:
        source_by_name = {dataset.name.casefold(): dataset for dataset in source_spec.datasets}
        target_domains = list(
            dict.fromkeys(item.target_domain.upper() for item in domain_mapping.domain_mappings)
        )
        datasets = []
        assumptions: list[str] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        standard: str | None = None
        define_standard: str | None = None
        prior_events: list[dict[str, Any]] | None = None

        for target_domain in target_domains:
            batch_mappings = [
                item
                for item in domain_mapping.domain_mappings
                if item.target_domain.upper() == target_domain
            ]
            batch_sources = [
                source_by_name[item.source_dataset.casefold()]
                for item in batch_mappings
            ]
            referenced_codelists = {
                variable.codelist.casefold()
                for dataset in batch_sources
                for variable in dataset.variables
                if variable.codelist
            }
            batch_spec = EDCSourceSpecification(
                study_name=source_spec.study_name,
                datasets=batch_sources,
                codelists=[
                    item
                    for item in source_spec.codelists
                    if item.name.casefold() in referenced_codelists
                ],
                assumptions=source_spec.assumptions,
                unresolved_items=source_spec.unresolved_items,
            )
            batch_domain_mapping = SDTMDomainMappingPlan(
                study_name=domain_mapping.study_name,
                standard=domain_mapping.standard,
                domain_mappings=batch_mappings,
                assumptions=domain_mapping.assumptions,
                unresolved_mappings=domain_mapping.unresolved_mappings,
            )
            outcome = await ClinicalAgentRunner(
                definition=_STAGE_AGENTS["variable-mapping"],
                result_model=SDTMVariableMappingPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    f"Stage 2 of 3, complete-data batch for target {target_domain}: preserve the supplied "
                    "approved domain relationships and return exactly one target dataset for this domain. "
                    "Determine its complete variable and value-level mapping. When no blank CRF is supplied, "
                    "leave crf_source_label null. Do not generate code."
                ),
                source=self._variable_mapping_source(
                    target_domain=target_domain,
                    source_spec=batch_spec,
                    domain_mapping=batch_domain_mapping,
                    context_inputs=context_inputs,
                    crf=crf,
                ),
                options=agent_options,
                stage=self.descriptor.stages[1],
                stage_index=2,
                stage_count=stage_count,
                completed_stages=[self.descriptor.stages[0]],
                prior_events=prior_events,
            )
            batch_plan = cast(SDTMVariableMappingPlan, outcome.value)
            self.validate_variable_mapping(batch_spec, batch_domain_mapping, batch_plan)
            if [item.domain.upper() for item in batch_plan.datasets] != [target_domain]:
                raise ValueError(
                    f"Variable-mapping batch {target_domain} must return exactly that target domain."
                )
            if standard is not None and batch_plan.standard != standard:
                raise ValueError("Variable-mapping batches returned inconsistent SDTM standards.")
            if define_standard is not None and batch_plan.define_standard != define_standard:
                raise ValueError("Variable-mapping batches returned inconsistent Define-XML standards.")
            standard = batch_plan.standard
            define_standard = batch_plan.define_standard
            datasets.extend(batch_plan.datasets)
            assumptions.extend(batch_plan.assumptions)
            unresolved.extend(batch_plan.unresolved_mappings)
            warnings.extend(outcome.warnings)
            prior_events = outcome.events

        return (
            SDTMVariableMappingPlan(
                study_name=source_spec.study_name,
                standard=standard or domain_mapping.standard,
                define_standard=define_standard or "Define-XML 2.1",
                datasets=datasets,
                assumptions=list(dict.fromkeys(assumptions)),
                unresolved_mappings=list(dict.fromkeys(unresolved)),
            ),
            list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _write_normalization_trace(
        context: UseCaseContext,
        source: Path,
        normalized: EDCJSONNormalization,
    ) -> None:
        path = context.agent_progress_path
        if path is None:
            return
        prior: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    prior = loaded
            except (OSError, json.JSONDecodeError):
                prior = {}
        events = [event for event in prior.get("events", []) if isinstance(event, dict)]
        turns = [event.get("turn", 0) for event in events]
        turn = max(
            [
                int(prior.get("turn", 0)),
                *[int(value) for value in turns if isinstance(value, int)],
            ]
        ) + 1
        now = datetime.now(timezone.utc).isoformat()
        dataset_count = len(normalized.specification.datasets)
        variable_count = sum(len(dataset.variables) for dataset in normalized.specification.datasets)
        events.append(
            {
                "turn": turn,
                "type": "deterministic",
                "name": "normalize_json_source",
                "stage": "EDC source normalization",
                "ok": True,
                "summary": "Parsed the complete JSON source into an editable EDC metadata draft.",
                "intent": "Inventory every discoverable source dataset and variable without model truncation.",
                "input_summary": f"Parsed the complete {source.name} JSON document.",
                "output_summary": f"Discovered {dataset_count} dataset(s) and {variable_count} variable(s).",
                "input_details": {
                    "File": source.name,
                    "Adapter": normalized.adapter,
                    "Complete document read": True,
                },
                "output_details": {
                    "Datasets": dataset_count,
                    "Variables": variable_count,
                    "Human approval required": True,
                },
                "evidence": [
                    f"{source.name} · {dataset_count} dataset path(s) discovered deterministically"
                ],
                "occurred_at": now,
            }
        )
        trace = {
            "agent_id": SOURCE_NORMALIZATION_AGENT.id,
            "workflow": SOURCE_NORMALIZATION_AGENT.workflow,
            "model": "deterministic-json-normalizer",
            "status": "completed",
            "turn": turn,
            "max_turns": max(int(prior.get("max_turns", 0)), turn),
            "stage": "EDC source normalization",
            "stage_index": 1,
            "stage_count": 1,
            "completed_stages": ["EDC source normalization"],
            "total_source_chunks": 0,
            "read_source_chunks": [],
            "started_at": prior.get("started_at", now),
            "updated_at": now,
            "completed_at": now,
            "messages": [],
            "events": events,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        crf, _ = self._workflow_inputs(context.inputs)
        source_spec = self._approved_source_spec(context.options)
        domain_mapping = self._approved_domain_mapping(context.options, source_spec)
        variable_mapping = self._approved_variable_mapping(context.options, source_spec, domain_mapping)
        rule_plan, rule_warnings = await self._generate_rule_batches(
            context,
            domain_mapping=domain_mapping,
            variable_mapping=variable_mapping,
        )
        result = SDTMPlan(
            study_name=variable_mapping.study_name,
            standard=variable_mapping.standard,
            define_standard=variable_mapping.define_standard,
            datasets=variable_mapping.datasets,
            domain_mappings=domain_mapping.domain_mappings,
            domain_rule_augmentations=rule_plan.domain_rule_augmentations,
            rule_augmentations=rule_plan.rule_augmentations,
            assumptions=list(
                dict.fromkeys(
                    [
                        *domain_mapping.assumptions,
                        *variable_mapping.assumptions,
                        *rule_plan.assumptions,
                    ]
                )
            ),
            unresolved_mappings=list(
                dict.fromkeys(
                    [
                        *domain_mapping.unresolved_mappings,
                        *variable_mapping.unresolved_mappings,
                        *rule_plan.unresolved_mappings,
                    ]
                )
            ),
        )
        problems = verify_result("sdtm", result)
        if problems:
            raise ValueError(" ".join(problems))
        warnings = [
            *rule_warnings,
            *self.result_warnings(result),
        ]
        if crf is None:
            warnings.append("Blank CRF was not supplied; annotated-crf.pdf was not generated.")
        return GeneratedContent(value=result, warnings=list(dict.fromkeys(warnings)))

    async def _generate_rule_batches(
        self,
        context: UseCaseContext,
        *,
        domain_mapping: SDTMDomainMappingPlan,
        variable_mapping: SDTMVariableMappingPlan,
    ) -> tuple[SDTMRuleAugmentationPlan, list[str]]:
        domain_rules = []
        variable_rules = []
        assumptions: list[str] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        prior_events: list[dict[str, Any]] | None = None
        agent_options = self._agent_options(context.options)
        stage_count = len(self.descriptor.stages)

        for dataset in variable_mapping.datasets:
            target_domain = dataset.domain.upper()
            batch_mappings = [
                item
                for item in domain_mapping.domain_mappings
                if item.target_domain.upper() == target_domain
            ]
            outcome = await ClinicalAgentRunner(
                definition=_STAGE_AGENTS["rule-augmentation"],
                result_model=SDTMRuleAugmentationPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    f"Stage 3 of 3, target {target_domain}: add exactly one source-preparation rule for this "
                    "target domain and exactly one implementation rule for every supplied target variable. "
                    "Do not restate or change the approved mappings."
                ),
                source=self._rule_mapping_source(
                    target_domain=target_domain,
                    domain_mappings=batch_mappings,
                    dataset=dataset,
                ),
                options=agent_options,
                stage=self.descriptor.stages[2],
                stage_index=3,
                stage_count=stage_count,
                completed_stages=list(self.descriptor.stages[:2]),
                prior_events=prior_events,
            )
            batch_plan = cast(SDTMRuleAugmentationPlan, outcome.value)
            problems = verify_result("sdtm-rule-augmentation", batch_plan)
            domain_targets = [item.target_domain.upper() for item in batch_plan.domain_rule_augmentations]
            if domain_targets != [target_domain]:
                problems.append(
                    f"Rule-augmentation batch {target_domain} must return exactly one domain rule for that target."
                )
            expected_variables = {item.name.upper() for item in dataset.variables}
            actual_variables = {
                item.target_variable.upper()
                for item in batch_plan.rule_augmentations
                if item.target_domain.upper() == target_domain
            }
            foreign_targets = sorted(
                {
                    item.target_domain.upper()
                    for item in batch_plan.rule_augmentations
                    if item.target_domain.upper() != target_domain
                }
            )
            if foreign_targets:
                problems.append(
                    f"Rule-augmentation batch {target_domain} returned other targets: {', '.join(foreign_targets)}."
                )
            missing = sorted(expected_variables - actual_variables)
            extra = sorted(actual_variables - expected_variables)
            if missing:
                problems.append(
                    f"Rule-augmentation batch {target_domain} is missing variables: {', '.join(missing)}."
                )
            if extra:
                problems.append(
                    f"Rule-augmentation batch {target_domain} returned unknown variables: {', '.join(extra)}."
                )
            if problems:
                raise ValueError(" ".join(problems))
            domain_rules.extend(batch_plan.domain_rule_augmentations)
            variable_rules.extend(batch_plan.rule_augmentations)
            assumptions.extend(batch_plan.assumptions)
            unresolved.extend(batch_plan.unresolved_mappings)
            warnings.extend(outcome.warnings)
            prior_events = outcome.events

        return (
            SDTMRuleAugmentationPlan(
                study_name=variable_mapping.study_name,
                standard=variable_mapping.standard,
                domain_rule_augmentations=domain_rules,
                rule_augmentations=variable_rules,
                assumptions=list(dict.fromkeys(assumptions)),
                unresolved_mappings=list(dict.fromkeys(unresolved)),
            ),
            list(dict.fromkeys(warnings)),
        )

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
    def _mapping_context_inputs(
        context: UseCaseContext,
        crf: Path | None,
        edc: Path,
    ) -> list[Path]:
        excluded_inputs = {edc, *([crf] if crf is not None else [])}
        return [
            path for path in context.inputs
            if path not in excluded_inputs
            and path.suffix.lower() not in {".csv", ".xpt"}
            and not path.name.startswith("validation-")
        ]

    @classmethod
    def _domain_mapping_source(
        cls,
        source_spec: EDCSourceSpecification,
        context_inputs: list[Path],
    ) -> str:
        inventory = {
            "study_name": source_spec.study_name,
            "datasets": [
                {
                    "name": dataset.name,
                    "label": dataset.label,
                    "source_type": dataset.source_type,
                    "structure": dataset.structure,
                    "key_variables": dataset.key_variables,
                    "variable_names": [variable.name for variable in dataset.variables],
                }
                for dataset in source_spec.datasets
            ],
            "assumptions": source_spec.assumptions,
            "unresolved_items": source_spec.unresolved_items,
        }
        return (
            "COMPLETE USER-APPROVED EDC DATASET INVENTORY\n"
            f"{cls._compact_json(inventory)}\n\n"
            "OPTIONAL STUDY CONTEXT\n"
            f"{cls.join_sources(context_inputs)}"
        )

    @classmethod
    def _variable_mapping_source(
        cls,
        *,
        target_domain: str,
        source_spec: EDCSourceSpecification,
        domain_mapping: SDTMDomainMappingPlan,
        context_inputs: list[Path],
        crf: Path | None,
    ) -> str:
        source_payload = {
            "study_name": source_spec.study_name,
            "datasets": [
                {
                    "name": dataset.name,
                    "label": dataset.label,
                    "source_type": dataset.source_type,
                    "structure": dataset.structure,
                    "key_variables": dataset.key_variables,
                    "variables": [
                        variable.model_dump(mode="json", exclude={"provenance"})
                        for variable in dataset.variables
                    ],
                }
                for dataset in source_spec.datasets
            ],
            "codelists": [item.model_dump(mode="json") for item in source_spec.codelists],
            "assumptions": source_spec.assumptions,
            "unresolved_items": source_spec.unresolved_items,
        }
        return (
            f"COMPLETE APPROVED SOURCE BATCH FOR TARGET {target_domain}\n"
            f"{cls._compact_json(source_payload)}\n\n"
            "USER-APPROVED DOMAIN MAPPING FOR THIS BATCH — PRESERVE\n"
            f"{cls._compact_json(domain_mapping.model_dump(mode='json'))}\n\n"
            f"{cls._crf_source(crf)}\n\n"
            "OPTIONAL STUDY CONTEXT\n"
            f"{cls.join_sources(context_inputs)}"
        )

    @classmethod
    def _rule_mapping_source(
        cls,
        *,
        target_domain: str,
        domain_mappings: list[Any],
        dataset: Any,
    ) -> str:
        return (
            f"APPROVED DOMAIN MAPPING BATCH FOR {target_domain} — PRESERVE\n"
            f"{cls._compact_json([item.model_dump(mode='json') for item in domain_mappings])}\n\n"
            f"APPROVED VARIABLE MAPPING BATCH FOR {target_domain} — PRESERVE\n"
            f"{cls._compact_json(dataset.model_dump(mode='json'))}"
        )

    @staticmethod
    def _compact_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
