from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from pydantic import BaseModel

from ..agents import AgentOutcome, ClinicalAgentRunner
from ..agents.runtime import verify_result
from ..agents.sdtm import SOURCE_NORMALIZATION_AGENT, STAGE_AGENTS
from ..artifacts import render_sdtm
from ..csdrg import render_csdrg
from ..edc_normalization import EDCJSONNormalization, normalize_edc_json
from ..parsers import chunk_text, parse_edc_source, parse_source
from ..sdtm_r import normalize_r_mapping_expression
from ..sdtm_sas import normalize_sas_filter_expression
from ..schemas import (
    EDCSourceSpecification,
    SDTMDomainMappingPlan,
    SDTMDomainMappingReview,
    SDTMPlan,
    SDTMRuleAugmentationPlan,
    SDTMVariableMappingPlan,
    SDTMVariableMappingReview,
)
from ..schemas.reviews import ReviewScope
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
        patch_request = context.options.get("_review_patch_request")
        if context.options.get("edc_source_spec") is None:
            if edc.suffix.lower() == ".json" and not isinstance(patch_request, dict):
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
                    "Stage 1 of 3: consider every raw/SDTM source dataset. Map applicable sources to target "
                    "SDTM datasets/domains, and place sources that should not contribute to SDTM in "
                    "unmapped_datasets with a specific rationale. Do not force a mapping merely to cover the "
                    "inventory. Classify row-appending sources as stack and keyed column-adding sources as join; "
                    "never use an ambiguous generic merge. Do not perform variable mapping or code generation. "
                    "Return a draft for human review."
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
            scoped_domains: list[str] | None = None
            reconciliation = context.options.get("_sdtm_variable_mapping_reconcile")
            if isinstance(patch_request, dict) and patch_request.get("stage") == "variable_mapping":
                scope = ReviewScope.model_validate(patch_request.get("scope", {}))
                scoped_domains = list(dict.fromkeys([
                    *scope.target_domains,
                    *[item.domain for item in scope.variables],
                ]))
            baseline_mapping: SDTMVariableMappingPlan | None = None
            preserve_domains: list[str] = []
            if scoped_domains is None and isinstance(reconciliation, dict):
                baseline_mapping = SDTMVariableMappingPlan.model_validate(reconciliation.get("baseline"))
                preserve_domains = [str(item).upper() for item in reconciliation.get("preserve_domains", [])]
                scoped_domains = [str(item).upper() for item in reconciliation.get("regenerate_domains", [])]
                expected = list(dict.fromkeys(item.target_domain.upper() for item in domain_mapping.domain_mappings))
                if len(preserve_domains) != len(set(preserve_domains)) or len(scoped_domains) != len(set(scoped_domains)):
                    raise ValueError("Variable-mapping reconciliation contains duplicate target domains.")
                if set(preserve_domains).intersection(scoped_domains) or set([*preserve_domains, *scoped_domains]) != set(expected):
                    raise ValueError("Variable-mapping reconciliation does not cover the approved target domains exactly once.")
            generated_mapping: SDTMVariableMappingPlan | None = None
            variable_warnings: list[str] = []
            if scoped_domains is None or scoped_domains:
                generated_mapping, variable_warnings = await self._generate_variable_mapping_batches(
                    context,
                    source_spec=source_spec,
                    domain_mapping=domain_mapping,
                    context_inputs=context_inputs,
                    crf=crf,
                    agent_options=agent_options,
                    stage_count=stage_count,
                    target_domains=scoped_domains,
                )
            variable_mapping = (
                self.reconcile_variable_mapping(
                    domain_mapping,
                    baseline=baseline_mapping,
                    generated=generated_mapping,
                    preserve_domains=preserve_domains,
                )
                if baseline_mapping is not None
                else generated_mapping
            )
            if variable_mapping is None:
                raise ValueError("Variable mapping generation did not produce a review draft.")
            if scoped_domains is None:
                self.validate_variable_mapping(source_spec, domain_mapping, variable_mapping)
            elif baseline_mapping is not None:
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

        raw_variable_mapping = context.options.get("sdtm_variable_mapping")
        if not isinstance(raw_variable_mapping, dict):
            raise ValueError("SDTM generation requires an approved variable and value-level mapping.")
        variable_mapping = SDTMVariableMappingPlan.model_validate(raw_variable_mapping)
        try:
            self.validate_variable_mapping(source_spec, domain_mapping, variable_mapping)
        except ValueError as exc:
            return GeneratedContent(
                value=SDTMVariableMappingReview(
                    source_spec=source_spec,
                    domain_mapping=domain_mapping,
                    variable_mapping=variable_mapping,
                ),
                warnings=[
                    "The previously approved variable mapping no longer satisfies the executable record-plan "
                    "contract. It was preserved and reopened for human correction; rule augmentation was not run.",
                    str(exc),
                ],
                review_stage="variable_mapping",
            )
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
        target_domains: list[str] | None = None,
    ) -> tuple[SDTMVariableMappingPlan, list[str]]:
        source_by_name = {dataset.name.casefold(): dataset for dataset in source_spec.datasets}
        approved_target_domains = list(
            dict.fromkeys(item.target_domain.upper() for item in domain_mapping.domain_mappings)
        )
        target_domains = approved_target_domains if target_domains is None else target_domains
        unknown_targets = sorted(set(target_domains) - set(approved_target_domains))
        if unknown_targets:
            raise ValueError(f"Scoped variable revision references unapproved domains: {', '.join(unknown_targets)}.")
        datasets = []
        assumptions: list[str] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        standard: str | None = None
        define_standard: str | None = None

        async def generate_domain(
            target_domain: str,
            domain_progress_path: Path | None,
        ) -> AgentOutcome:
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
                progress_path=domain_progress_path,
                complete_source_chunk_limit=context.settings.sdtm_domain_max_source_chunks,
                result_validator=lambda value: self.validate_variable_mapping(
                    batch_spec,
                    batch_domain_mapping,
                    cast(SDTMVariableMappingPlan, value),
                ),
            ).run(
                objective=(
                    f"Stage 2 of 3, complete-data batch for target {target_domain}: preserve the supplied "
                    "approved domain relationships and return exactly one target dataset for this domain. "
                    "Determine its complete typed record-construction plan plus variable and value-level mapping. "
                    "Represent every read, stack, join, transpose, filter, deduplication, or aggregation as an "
                    "ordered record_plan step. Give every variable and VLM cell all of its approved raw source "
                    "references with explicit roles. Assigned constants have no sources; derived variables retain "
                    "every contributing source. When no blank CRF is supplied, leave crf_source_label null. Do not "
                    "generate target-variable R or SAS code. Every filter condition must be one executable, safe R "
                    "boolean expression and every sas_condition must be one executable SAS boolean expression; "
                    "never put prose or pseudocode in either field."
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
            )
            return outcome

        outcomes = await self._run_parallel_domain_agents(
            context,
            target_domains=target_domains,
            stage=self.descriptor.stages[1],
            stage_index=2,
            stage_count=stage_count,
            completed_stages=[self.descriptor.stages[0]],
            generate=generate_domain,
        )

        for target_domain, outcome in zip(target_domains, outcomes, strict=True):
            batch_plan = cast(SDTMVariableMappingPlan, outcome.value)
            batch_mappings = [
                item
                for item in domain_mapping.domain_mappings
                if item.target_domain.upper() == target_domain
            ]
            batch_spec = EDCSourceSpecification(
                study_name=source_spec.study_name,
                datasets=[source_by_name[item.source_dataset.casefold()] for item in batch_mappings],
                codelists=source_spec.codelists,
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
            batch_dataset = batch_plan.datasets[0].model_copy(update={
                "review_assumptions": list(batch_plan.assumptions),
                "review_unresolved_mappings": list(batch_plan.unresolved_mappings),
            })
            datasets.append(batch_dataset)
            assumptions.extend(batch_plan.assumptions)
            unresolved.extend(batch_plan.unresolved_mappings)
            warnings.extend(outcome.warnings)

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

    async def _run_parallel_domain_agents(
        self,
        context: UseCaseContext,
        *,
        target_domains: list[str],
        stage: str,
        stage_index: int,
        stage_count: int,
        completed_stages: list[str],
        generate: Callable[[str, Path | None], Awaitable[AgentOutcome]],
    ) -> list[AgentOutcome]:
        concurrency = max(
            1,
            min(context.settings.sdtm_domain_agent_concurrency, len(target_domains) or 1),
        )
        max_attempts = max(1, min(context.settings.sdtm_domain_agent_max_attempts, 3))
        semaphore = asyncio.Semaphore(concurrency)
        progress_path = context.agent_progress_path
        baseline = self._read_agent_progress(progress_path)
        stage_directory: Path | None = None
        domain_paths: dict[str, Path] = {}
        if progress_path is not None:
            stage_slug = "".join(character.lower() if character.isalnum() else "-" for character in stage)
            stage_slug = "-".join(part for part in stage_slug.split("-") if part)
            stage_directory = progress_path.parent / "domains" / stage_slug
            stage_directory.mkdir(parents=True, exist_ok=True)
            for old_trace in stage_directory.glob("*.json"):
                old_trace.unlink(missing_ok=True)
            for index, domain in enumerate(target_domains, start=1):
                domain_slug = "".join(character.lower() if character.isalnum() else "-" for character in domain)
                domain_paths[domain] = stage_directory / f"{index:03d}-{domain_slug}.json"

        async def run_domain(target_domain: str) -> AgentOutcome:
            for attempt in range(1, max_attempts + 1):
                try:
                    async with semaphore:
                        return await generate(target_domain, domain_paths.get(target_domain))
                except Exception as exc:
                    if attempt >= max_attempts or not self._is_retryable_domain_error(exc):
                        raise
                    self._record_domain_retry(
                        domain_paths.get(target_domain),
                        target_domain=target_domain,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        error=exc,
                    )
                    await asyncio.sleep(0)
            raise RuntimeError(f"{target_domain} domain agent exhausted its retry attempts.")

        stop_monitor = asyncio.Event()

        async def monitor_progress() -> None:
            if progress_path is None:
                return
            while not stop_monitor.is_set():
                self._merge_domain_progress(
                    progress_path,
                    baseline=baseline,
                    target_domains=target_domains,
                    domain_paths=domain_paths,
                    stage=stage,
                    stage_index=stage_index,
                    stage_count=stage_count,
                    completed_stages=completed_stages,
                    model=context.settings.meta_model,
                    max_turns_per_domain=context.settings.agent_max_turns,
                    status="running",
                )
                try:
                    await asyncio.wait_for(stop_monitor.wait(), timeout=0.25)
                except TimeoutError:
                    pass

        monitor = asyncio.create_task(monitor_progress(), name=f"sdtm-{stage_index}-progress")
        tasks = [
            asyncio.create_task(run_domain(domain), name=f"sdtm-{stage_index}-{domain}")
            for domain in target_domains
        ]
        final_status = "completed"
        try:
            outcomes = await asyncio.gather(*tasks)
        except BaseException:
            final_status = "failed"
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            stop_monitor.set()
            await monitor
            if progress_path is not None:
                self._merge_domain_progress(
                    progress_path,
                    baseline=baseline,
                    target_domains=target_domains,
                    domain_paths=domain_paths,
                    stage=stage,
                    stage_index=stage_index,
                    stage_count=stage_count,
                    completed_stages=completed_stages,
                    model=context.settings.meta_model,
                    max_turns_per_domain=context.settings.agent_max_turns,
                    status=final_status,
                )
        return outcomes

    @staticmethod
    def _is_retryable_domain_error(exc: BaseException) -> bool:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and (status_code == 429 or status_code >= 500):
            return True
        name = type(exc).__name__.casefold()
        message = " ".join(str(exc).split()).casefold()
        retryable_markers = (
            "timeout",
            "timed out",
            "rate limit",
            "ratelimit",
            "connection reset",
            "connection error",
            "connectionerror",
            "temporarily unavailable",
            "service unavailable",
        )
        return any(marker in name or marker in message for marker in retryable_markers)

    @staticmethod
    def _record_domain_retry(
        path: Path | None,
        *,
        target_domain: str,
        attempt: int,
        max_attempts: int,
        error: BaseException,
    ) -> None:
        if path is None:
            return
        trace: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    trace = loaded
            except (OSError, json.JSONDecodeError):
                trace = {}
        events = [event for event in trace.get("events", []) if isinstance(event, dict)]
        turns = [int(event.get("turn", 0)) for event in events if isinstance(event.get("turn"), int)]
        turn = max([int(trace.get("turn", 0)), *turns]) + 1
        now = datetime.now(timezone.utc).isoformat()
        error_text = " ".join(str(error).split())[:500] or type(error).__name__
        events.append({
            "turn": turn,
            "type": "domain_retry",
            "actor": "system",
            "name": "retry_domain_agent",
            "stage": trace.get("stage"),
            "ok": True,
            "error": None,
            "summary": f"Retrying {target_domain} after a transient model-service failure.",
            "intent": "Retry only the affected domain while retaining accepted results from other domains.",
            "input_summary": f"Attempt {attempt - 1} ended with a retryable error.",
            "output_summary": f"Starting attempt {attempt} of {max_attempts} for {target_domain}.",
            "input_details": {
                "Target domain": target_domain,
                "Prior error": error_text,
            },
            "output_details": {
                "Attempt": attempt,
                "Maximum attempts": max_attempts,
                "Other domain results retained": True,
            },
            "evidence": ["Per-domain model request trace"],
            "occurred_at": now,
        })
        trace.update({
            "status": "retrying",
            "turn": turn,
            "updated_at": now,
            "error": None,
            "last_error": error_text,
            "events": events,
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _read_agent_progress(path: Path | None) -> dict[str, Any]:
        if path is None or not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _merge_domain_progress(
        cls,
        progress_path: Path,
        *,
        baseline: dict[str, Any],
        target_domains: list[str],
        domain_paths: dict[str, Path],
        stage: str,
        stage_index: int,
        stage_count: int,
        completed_stages: list[str],
        model: str,
        max_turns_per_domain: int,
        status: str,
    ) -> None:
        baseline_events = [
            dict(event)
            for event in baseline.get("events", [])
            if isinstance(event, dict)
        ]
        traces: list[tuple[int, str, dict[str, Any]]] = []
        for domain_index, domain in enumerate(target_domains):
            trace = cls._read_agent_progress(domain_paths.get(domain))
            if trace:
                traces.append((domain_index, domain, trace))

        domain_events: list[tuple[str, int, int, dict[str, Any]]] = []
        total_chunks = 0
        read_chunks = 0
        started_values: list[str] = []
        updated_values: list[str] = []
        for domain_index, domain, trace in traces:
            total_chunks += int(trace.get("total_source_chunks", 0))
            read_chunks += len(trace.get("read_source_chunks", []))
            if trace.get("started_at"):
                started_values.append(str(trace["started_at"]))
            if trace.get("updated_at"):
                updated_values.append(str(trace["updated_at"]))
            for event_index, event in enumerate(trace.get("events", [])):
                if not isinstance(event, dict):
                    continue
                item = dict(event)
                summary = str(item.get("summary", "")).strip()
                item["summary"] = f"{domain}: {summary}" if summary else f"{domain} domain agent event"
                details = dict(item.get("input_details", {})) if isinstance(item.get("input_details"), dict) else {}
                details.setdefault("Target domain", domain)
                item["input_details"] = details
                occurred_at = str(item.get("occurred_at", ""))
                domain_events.append((occurred_at, domain_index, event_index, item))
        domain_events.sort(key=lambda item: (item[0], item[1], item[2]))

        turn = max(
            [int(baseline.get("turn", 0)), *[int(event.get("turn", 0)) for event in baseline_events]],
            default=0,
        )
        merged_events = baseline_events
        for _occurred_at, _domain_index, _event_index, event in domain_events:
            turn += 1
            event["turn"] = turn
            merged_events.append(event)

        now = datetime.now(timezone.utc).isoformat()
        completed = list(dict.fromkeys(completed_stages))
        if status == "completed" and stage not in completed:
            completed.append(stage)
        aggregate = {
            "agent_id": _STAGE_AGENTS["variable-mapping"].id if stage_index == 2 else _STAGE_AGENTS["rule-augmentation"].id,
            "workflow": "sdtm",
            "model": model,
            "status": status,
            "turn": turn,
            "max_turns": max(
                int(baseline.get("max_turns", 0)),
                turn + max_turns_per_domain * len(target_domains),
            ),
            "stage": stage,
            "stage_index": stage_index,
            "stage_count": stage_count,
            "completed_stages": completed,
            "total_source_chunks": total_chunks,
            "read_source_chunks": list(range(1, read_chunks + 1)),
            "started_at": min(started_values) if started_values else baseline.get("started_at", now),
            "updated_at": max(updated_values) if updated_values else now,
            "completed_at": now if status == "completed" else None,
            "messages": [],
            "events": merged_events,
            "domain_agents": [
                {
                    "domain": domain,
                    "status": trace.get("status", "queued"),
                    "turn": int(trace.get("turn", 0)),
                    "updated_at": trace.get("updated_at"),
                }
                for _domain_index, domain, trace in traces
            ],
        }
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = progress_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(progress_path)

    @staticmethod
    def build_variable_mapping_reconciliation(
        previous: SDTMDomainMappingPlan,
        current: SDTMDomainMappingPlan,
        baseline: SDTMVariableMappingPlan,
    ) -> dict[str, Any]:
        """Describe which domain batches remain valid after a domain-plan revision."""

        def signatures(plan: SDTMDomainMappingPlan) -> dict[str, tuple[tuple[str, str, str], ...]]:
            grouped: dict[str, list[tuple[str, str, str]]] = {}
            for item in plan.domain_mappings:
                grouped.setdefault(item.target_domain.upper(), []).append((
                    item.source_dataset.casefold(),
                    item.source_type,
                    item.relationship,
                ))
            return {domain: tuple(sorted(values)) for domain, values in grouped.items()}

        target_domains = list(dict.fromkeys(item.target_domain.upper() for item in current.domain_mappings))
        baseline_domains = {item.domain.upper() for item in baseline.datasets}
        previous_signatures = signatures(previous)
        current_signatures = signatures(current)
        compatible_header = previous.study_name == current.study_name and previous.standard == current.standard
        preserve_domains = [
            domain
            for domain in target_domains
            if compatible_header
            and domain in baseline_domains
            and previous_signatures.get(domain) == current_signatures.get(domain)
        ]
        return {
            "baseline": baseline.model_dump(mode="json"),
            "preserve_domains": preserve_domains,
            "regenerate_domains": [domain for domain in target_domains if domain not in preserve_domains],
        }

    @staticmethod
    def reconcile_variable_mapping(
        domain_mapping: SDTMDomainMappingPlan,
        *,
        baseline: SDTMVariableMappingPlan,
        generated: SDTMVariableMappingPlan | None,
        preserve_domains: list[str],
    ) -> SDTMVariableMappingPlan:
        """Merge unchanged reviewed domain batches with regenerated affected batches."""

        target_domains = list(dict.fromkeys(item.target_domain.upper() for item in domain_mapping.domain_mappings))
        preserve = {item.upper() for item in preserve_domains}
        baseline_by_domain = {item.domain.upper(): item for item in baseline.datasets}
        generated_by_domain = {item.domain.upper(): item for item in generated.datasets} if generated else {}
        datasets = []
        for domain in target_domains:
            dataset = baseline_by_domain.get(domain) if domain in preserve else generated_by_domain.get(domain)
            if dataset is None:
                raise ValueError(f"Variable-mapping reconciliation has no dataset for {domain}.")
            datasets.append(dataset)

        baseline_owned_assumptions = {
            note for dataset in baseline.datasets for note in dataset.review_assumptions
        }
        baseline_owned_unresolved = {
            note for dataset in baseline.datasets for note in dataset.review_unresolved_mappings
        }
        stage_assumptions = [note for note in baseline.assumptions if note not in baseline_owned_assumptions]
        stage_unresolved = [note for note in baseline.unresolved_mappings if note not in baseline_owned_unresolved]
        return SDTMVariableMappingPlan(
            study_name=domain_mapping.study_name,
            standard=generated.standard if generated else baseline.standard,
            define_standard=generated.define_standard if generated else baseline.define_standard,
            datasets=datasets,
            assumptions=list(dict.fromkeys([
                *stage_assumptions,
                *[note for dataset in datasets for note in dataset.review_assumptions],
            ])),
            unresolved_mappings=list(dict.fromkeys([
                *stage_unresolved,
                *[note for dataset in datasets for note in dataset.review_unresolved_mappings],
            ])),
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
            unmapped_datasets=domain_mapping.unmapped_datasets,
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

    async def regenerate_completed_domain(
        self,
        context: UseCaseContext,
        *,
        baseline: SDTMPlan,
        stage: str,
        target_domain: str,
    ) -> GeneratedContent:
        """Regenerate one completed SDTM domain while preserving every other approved domain."""

        domain = target_domain.upper()
        baseline_domains = {dataset.domain.upper() for dataset in baseline.datasets}
        if domain not in baseline_domains:
            raise ValueError(f"Completed SDTM plan does not contain target domain {domain}.")
        if stage not in {"variable_mapping", "rule_augmentation"}:
            raise ValueError(f"Unsupported completed SDTM domain rerun stage {stage}.")

        crf, edc = self._workflow_inputs(context.inputs)
        source_spec = self._approved_source_spec(context.options)
        domain_mapping = SDTMDomainMappingPlan(
            study_name=baseline.study_name,
            standard=baseline.standard,
            domain_mappings=baseline.domain_mappings,
            unmapped_datasets=baseline.unmapped_datasets,
        )
        self.validate_domain_mapping(source_spec, domain_mapping)
        baseline_variable_mapping = SDTMVariableMappingPlan(
            study_name=baseline.study_name,
            standard=baseline.standard,
            define_standard=baseline.define_standard,
            datasets=baseline.datasets,
            assumptions=baseline.assumptions,
            unresolved_mappings=baseline.unresolved_mappings,
        )
        variable_mapping = baseline_variable_mapping
        warnings: list[str] = []

        if stage == "variable_mapping":
            generated, variable_warnings = await self._generate_variable_mapping_batches(
                context,
                source_spec=source_spec,
                domain_mapping=domain_mapping,
                context_inputs=self._mapping_context_inputs(context, crf, edc),
                crf=crf,
                agent_options=self._agent_options(context.options),
                stage_count=len(self.descriptor.stages),
                target_domains=[domain],
            )
            variable_mapping = self.reconcile_variable_mapping(
                domain_mapping,
                baseline=baseline_variable_mapping,
                generated=generated,
                preserve_domains=[item for item in baseline_domains if item != domain],
            )
            self.validate_variable_mapping(source_spec, domain_mapping, variable_mapping)
            warnings.extend(variable_warnings)

        rule_plan, rule_warnings = await self._generate_rule_batches(
            context,
            domain_mapping=domain_mapping,
            variable_mapping=variable_mapping,
            target_domains=[domain],
        )
        replacement_rules = sorted(
            rule_plan.rule_augmentations,
            key=lambda rule: rule.target_variable.upper(),
        )
        existing_rules_by_domain: dict[str, list[Any]] = {}
        for rule in baseline.rule_augmentations:
            existing_rules_by_domain.setdefault(rule.target_domain.upper(), []).append(rule)
        merged_rules = []
        for dataset in variable_mapping.datasets:
            dataset_domain = dataset.domain.upper()
            merged_rules.extend(
                replacement_rules
                if dataset_domain == domain
                else existing_rules_by_domain.get(dataset_domain, [])
            )
        proposed = SDTMPlan(
            study_name=baseline.study_name,
            standard=variable_mapping.standard,
            define_standard=variable_mapping.define_standard,
            datasets=variable_mapping.datasets,
            domain_mappings=baseline.domain_mappings,
            unmapped_datasets=baseline.unmapped_datasets,
            rule_augmentations=merged_rules,
            assumptions=list(dict.fromkeys([*variable_mapping.assumptions, *rule_plan.assumptions])),
            unresolved_mappings=list(
                dict.fromkeys([*variable_mapping.unresolved_mappings, *rule_plan.unresolved_mappings])
            ),
        )
        validated = self.validate_result(proposed.model_dump(mode="json"))
        return GeneratedContent(
            value=validated,
            warnings=list(dict.fromkeys([*warnings, *rule_warnings, *self.result_warnings(validated)])),
        )

    async def _generate_rule_batches(
        self,
        context: UseCaseContext,
        *,
        domain_mapping: SDTMDomainMappingPlan,
        variable_mapping: SDTMVariableMappingPlan,
        target_domains: list[str] | None = None,
    ) -> tuple[SDTMRuleAugmentationPlan, list[str]]:
        variable_rules = []
        assumptions: list[str] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        agent_options = self._agent_options(context.options)
        stage_count = len(self.descriptor.stages)

        datasets_by_domain = {dataset.domain.upper(): dataset for dataset in variable_mapping.datasets}
        requested_domains = (
            list(datasets_by_domain)
            if target_domains is None
            else list(dict.fromkeys(item.upper() for item in target_domains))
        )
        unknown_domains = sorted(set(requested_domains) - set(datasets_by_domain))
        if unknown_domains:
            raise ValueError(f"Rule augmentation requested unknown target domains: {', '.join(unknown_domains)}.")

        async def generate_domain(
            target_domain: str,
            domain_progress_path: Path | None,
        ) -> AgentOutcome:
            dataset = datasets_by_domain[target_domain]
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
                progress_path=domain_progress_path,
                complete_source_chunk_limit=context.settings.sdtm_domain_max_source_chunks,
                result_validator=lambda value: self._validate_rule_batch(
                    target_domain,
                    dataset,
                    cast(SDTMRuleAugmentationPlan, value),
                ),
            ).run(
                objective=(
                    f"Stage 3 of 3, target {target_domain}: add exactly one implementation rule for every "
                    "supplied target variable. The approved typed record plan is compiled deterministically, so "
                    "do not restate source dependencies or generate source preparation code."
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
            )
            return outcome

        outcomes = await self._run_parallel_domain_agents(
            context,
            target_domains=requested_domains,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages[:2]),
            generate=generate_domain,
        )

        for target_domain, outcome in zip(requested_domains, outcomes, strict=True):
            dataset = datasets_by_domain[target_domain]
            batch_plan = cast(SDTMRuleAugmentationPlan, outcome.value)
            self._validate_rule_batch(target_domain, dataset, batch_plan)
            variable_rules.extend(batch_plan.rule_augmentations)
            assumptions.extend(batch_plan.assumptions)
            unresolved.extend(batch_plan.unresolved_mappings)
            warnings.extend(outcome.warnings)

        return (
            SDTMRuleAugmentationPlan(
                study_name=variable_mapping.study_name,
                standard=variable_mapping.standard,
                rule_augmentations=variable_rules,
                assumptions=list(dict.fromkeys(assumptions)),
                unresolved_mappings=list(dict.fromkeys(unresolved)),
            ),
            list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _validate_rule_batch(
        target_domain: str,
        dataset: Any,
        batch_plan: SDTMRuleAugmentationPlan,
    ) -> None:
        problems = verify_result("sdtm-rule-augmentation", batch_plan)
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
        unmapped_sources = {item.source_dataset.upper() for item in mapping.unmapped_datasets}
        considered_sources = mapped_sources | unmapped_sources
        missing = sorted(set(sources) - considered_sources)
        unknown = sorted(considered_sources - set(sources))
        conflicting = sorted(mapped_sources & unmapped_sources)
        if missing:
            problems.append(
                "Every source dataset must be explicitly mapped or marked not mapped; "
                f"missing dispositions: {', '.join(missing)}."
            )
        if unknown:
            problems.append(f"Dataset dispositions reference unknown source datasets: {', '.join(unknown)}.")
        if conflicting:
            problems.append(
                "A source dataset cannot be both mapped and marked not mapped: "
                f"{', '.join(conflicting)}."
            )
        mappings_by_target: dict[str, list[Any]] = {}
        targets_by_source: dict[str, set[str]] = {}
        for item in mapping.domain_mappings:
            mappings_by_target.setdefault(item.target_domain.upper(), []).append(item)
            targets_by_source.setdefault(item.source_dataset.upper(), set()).add(item.target_domain.upper())
        for item in mapping.domain_mappings:
            source_dataset = sources.get(item.source_dataset.upper())
            if source_dataset and item.source_type != source_dataset.source_type:
                problems.append(
                    f"{item.source_dataset} source type must remain {source_dataset.source_type}, not {item.source_type}."
                )
            if item.relationship == "split" and len(targets_by_source[item.source_dataset.upper()]) < 2:
                problems.append(
                    f"{item.source_dataset} is marked split but maps only to {item.target_domain}; "
                    "split requires one source to feed multiple target domains."
                )
        for target_domain, target_mappings in mappings_by_target.items():
            stack_sources = [item.source_dataset for item in target_mappings if item.relationship == "stack"]
            direct_sources = [item.source_dataset for item in target_mappings if item.relationship == "direct"]
            if len(stack_sources) == 1:
                problems.append(
                    f"{target_domain} has only one stack source ({stack_sources[0]}); "
                    "mark every appended source as stack."
                )
            if len(direct_sources) > 1:
                problems.append(
                    f"{target_domain} has multiple direct sources ({', '.join(direct_sources)}); "
                    "classify row appends as stack or key-based column additions as join."
                )
        for item in mapping.unmapped_datasets:
            if not item.rationale.strip():
                problems.append(f"{item.source_dataset} needs a rationale for not being mapped to SDTM.")
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
        relationships: dict[str, set[str]] = {}
        for item in domain_mapping.domain_mappings:
            mapped_sources.setdefault(item.target_domain.upper(), set()).add(item.source_dataset.upper())
            relationships.setdefault(item.target_domain.upper(), set()).add(item.relationship)
        dataset_domains = {dataset.domain.upper() for dataset in mapping.datasets}
        target_domains = set(mapped_sources)
        missing = sorted(target_domains - dataset_domains)
        extra = sorted(dataset_domains - target_domains)
        if missing:
            problems.append(f"Every approved target domain needs variable mapping; missing: {', '.join(missing)}.")
        if extra:
            problems.append(f"Variable mapping contains unapproved target domains: {', '.join(extra)}.")
        known_sources = {
            dataset.name.upper(): {variable.name.upper() for variable in dataset.variables}
            for dataset in source_spec.datasets
        }
        for dataset in mapping.datasets:
            allowed_sources = mapped_sources.get(dataset.domain.upper(), set())
            SDTMUseCase._validate_record_plan(dataset.domain, dataset.record_plan, allowed_sources, problems)
            operations = {step.operation for step in dataset.record_plan.steps}
            required_operations = relationships.get(dataset.domain.upper(), set()) & {"stack", "join"}
            missing_operations = sorted(required_operations - operations)
            if missing_operations:
                problems.append(
                    f"{dataset.domain} domain relationships require record-plan operation(s): "
                    f"{', '.join(missing_operations)}."
                )
            for variable in dataset.variables:
                SDTMUseCase._validate_source_references(
                    f"{dataset.domain}.{variable.name}", variable.sources, allowed_sources, known_sources, problems
                )
                if not variable.sources:
                    if not SDTMUseCase._allows_sourceless_variable(variable.origin):
                        problems.append(
                            f"{dataset.domain}.{variable.name} has no raw source and needs an Assigned, Derived, "
                            "Protocol, System, or Sponsor origin."
                        )
                    if not variable.mapping_expression.strip() or variable.mapping_expression.strip().casefold() == "direct":
                        problems.append(
                            f"{dataset.domain}.{variable.name} has no raw source and needs an explicit assignment "
                            "or derivation in mapping_expression."
                        )
                if variable.mapping_type == "assigned" and variable.sources:
                    problems.append(f"{dataset.domain}.{variable.name} is assigned and cannot have source references.")
                if variable.mapping_type == "direct" and len(variable.sources) != 1:
                    problems.append(f"{dataset.domain}.{variable.name} direct mapping requires exactly one source reference.")
                for index, metadata in enumerate(variable.value_level_metadata, 1):
                    SDTMUseCase._validate_source_references(
                        f"{dataset.domain}.{variable.name} VLM {index}", metadata.sources,
                        allowed_sources, known_sources, problems,
                    )
        if problems:
            raise ValueError(" ".join(problems))

    @staticmethod
    def _validate_source_references(
        label: str,
        references: list[Any],
        allowed_sources: set[str],
        known_sources: dict[str, set[str]],
        problems: list[str],
    ) -> None:
        seen: set[tuple[str, str, str]] = set()
        for reference in references:
            source_name = reference.dataset.upper()
            variable_name = reference.variable.upper()
            identity = (source_name, variable_name, reference.role)
            if identity in seen:
                problems.append(f"{label} has duplicate source reference {reference.dataset}.{reference.variable} ({reference.role}).")
            seen.add(identity)
            if source_name not in known_sources:
                problems.append(f"{label} references unknown source dataset {reference.dataset}.")
            elif variable_name not in known_sources[source_name]:
                problems.append(f"{label} references unknown source variable {reference.dataset}.{reference.variable}.")
            if source_name not in allowed_sources:
                problems.append(f"{label} source {reference.dataset} is not approved for this target domain.")

    @staticmethod
    def _validate_record_plan(domain: str, plan: Any, allowed_sources: set[str], problems: list[str]) -> None:
        step_ids = [step.step_id for step in plan.steps]
        normalized_ids = {item.casefold() for item in step_ids}
        if len(step_ids) != len(normalized_ids):
            problems.append(f"{domain} record-plan step identifiers must be unique.")
        if plan.output_step.casefold() not in normalized_ids:
            problems.append(f"{domain} record-plan output_step must reference a step identifier.")
        available: set[str] = set()
        read_sources: set[str] = set()
        for step in plan.steps:
            label = f"{domain} record step {step.step_id}"
            operation = step.operation
            if not step.step_id.strip() or not step.output.strip():
                problems.append(f"{label} needs non-empty step_id and output values.")
            if operation == "read":
                source = (step.source_dataset or "").upper()
                if not source:
                    problems.append(f"{label} read operation needs source_dataset.")
                elif source not in allowed_sources:
                    problems.append(f"{label} reads source {step.source_dataset} not approved for {domain}.")
                read_sources.add(source)
            elif operation == "stack" and len(step.inputs) < 2:
                problems.append(f"{label} stack operation needs at least two prior step inputs.")
            elif operation == "join" and (
                not step.left or not step.right or not step.join_type or not step.cardinality or not step.join_keys
            ):
                problems.append(f"{label} join operation needs left/right inputs, join type, cardinality, and keys.")
            elif operation == "transpose" and (
                len(step.inputs) != 1 or not step.value_variables or not step.name_variable or not step.value_variable
            ):
                problems.append(f"{label} transpose operation needs one input, value variables, name variable, and value variable.")
            elif operation == "filter":
                if len(step.inputs) != 1 or not step.condition or not step.sas_condition:
                    problems.append(f"{label} filter operation needs one input plus reviewed R and SAS conditions.")
                elif step.condition:
                    try:
                        normalize_r_mapping_expression(step.condition)
                    except ValueError as exc:
                        problems.append(f"{label} has an invalid executable R condition: {exc}")
                    try:
                        normalize_sas_filter_expression(step.sas_condition or "")
                    except ValueError as exc:
                        problems.append(f"{label} has an invalid executable SAS condition: {exc}")
            elif operation == "deduplicate" and (len(step.inputs) != 1 or not step.keys):
                problems.append(f"{label} deduplicate operation needs one input and keys.")
            elif operation == "aggregate" and (
                len(step.inputs) != 1 or not step.group_by or not step.aggregations
            ):
                problems.append(f"{label} aggregate operation needs one input, grouping variables, and aggregations.")
            references = [
                *step.inputs,
                *([step.left] if step.left else []),
                *([step.right] if step.right else []),
            ]
            for reference in references:
                if reference.casefold() not in available:
                    problems.append(f"{label} references unavailable or later step {reference}.")
            available.add(step.step_id.casefold())
        if read_sources != allowed_sources:
            missing = sorted(allowed_sources - read_sources)
            extra = sorted(read_sources - allowed_sources)
            details = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if extra:
                details.append(f"extra {', '.join(extra)}")
            problems.append(f"{domain} record plan must read every approved source ({'; '.join(details)}).")

    @staticmethod
    def _allows_sourceless_variable(origin: str) -> bool:
        normalized = origin.strip().casefold()
        return any(token in normalized for token in ("assigned", "derived", "protocol", "system", "sponsor"))

    @staticmethod
    def _agent_options(options: dict[str, Any]) -> dict[str, Any]:
        excluded = {"edc_source_spec", "sdtm_domain_mapping", "sdtm_variable_mapping"}
        review_context = {"_review_revision_result"}
        return {
            key: value
            for key, value in options.items()
            if key not in excluded and (not key.startswith("_") or key in review_context)
        }

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
