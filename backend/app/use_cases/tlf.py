from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents.runtime import ClinicalAgentRunner, verify_result
from ..agents.tlf.agent import ANALYSIS_AGENT, INVENTORY_AGENT, PROGRAMMING_AGENT
from ..artifacts import render_tlf
from ..schemas import TLFAnalysisPlan, TLFInventoryPlan, TLFPlan, TLFProgrammingPlan
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor
from .utilities import normalize_languages


class TLFUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="tlf",
        title="TLF artifact generation",
        description="Generate table, listing, and figure specifications, shells, and program scaffolds.",
        skill_name="clinical-tlf-artifacts",
        accepted_extensions=(".pdf", ".docx", ".txt", ".md", ".json", ".xlsx"),
        required_inputs=("SAP or protocol", "Optional ADaM metadata"),
        output_formats=("json", "xlsx", "docx", "r", "sas", "zip"),
        mcp_dependencies=("cdisc-library",),
        stages=("Output inventory", "Analysis & display specification", "Programming augmentation"),
        supports_languages=True,
    )
    result_model = TLFPlan

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        super().validate_submission(filenames, options)
        narrative = {".pdf", ".docx", ".txt", ".md"}
        if not any(Path(name).suffix.lower() in narrative for name in filenames):
            raise ValueError("TLF generation requires at least one SAP or protocol file (PDF, DOCX, TXT, or Markdown).")

    def validate_result(self, value: dict[str, Any]) -> BaseModel:
        plan = cast(TLFPlan, super().validate_result(value))
        plan = self._with_readiness(plan)
        problems = verify_result("tlf", plan)
        if problems:
            raise ValueError(" ".join(problems))
        return plan

    async def prepare_review(self, context: UseCaseContext) -> GeneratedContent | None:
        if context.options.get("tlf_shell_plan") is not None:
            return None
        source = self.join_sources(context.inputs)
        stage_count = len(self.descriptor.stages)
        inventory_outcome = await ClinicalAgentRunner(
            definition=INVENTORY_AGENT,
            result_model=TLFInventoryPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 1 of 3: extract only the table, listing, and figure inventory supported by the source. "
                "Do not map analysis variables or generate program logic."
            ),
            source=source,
            options=context.options,
            stage=self.descriptor.stages[0],
            stage_index=1,
            stage_count=stage_count,
        )
        inventory_json = inventory_outcome.value.model_dump_json(indent=2)
        analysis_outcome = await ClinicalAgentRunner(
            definition=ANALYSIS_AGENT,
            result_model=TLFAnalysisPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 2 of 3: preserve the inventory exactly and add population, ADaM source, analysis, and "
                "display specifications. Do not generate R or SAS code."
            ),
            source=f"{source}\n\nSTAGE 1 OUTPUT INVENTORY — PRESERVE\n{inventory_json}",
            options=context.options,
            stage=self.descriptor.stages[1],
            stage_index=2,
            stage_count=stage_count,
            completed_stages=[self.descriptor.stages[0]],
            prior_events=inventory_outcome.events,
        )
        analysis_plan = cast(TLFAnalysisPlan, analysis_outcome.value)
        inventory_identity = [
            (item.output_id.casefold(), item.output_type, item.title.strip())
            for item in inventory_outcome.value.outputs
        ]
        analysis_identity = [
            (item.output_id.casefold(), item.output_type, item.title.strip())
            for item in analysis_plan.outputs
        ]
        if inventory_identity != analysis_identity:
            raise ValueError(
                "Analysis specification must preserve the ordered stage-1 output identifiers, types, and titles."
            )
        analysis_plan = self._with_shell_readiness(analysis_plan)
        warnings = [
            *inventory_outcome.warnings,
            *analysis_outcome.warnings,
            *self.result_warnings(analysis_plan),
        ]
        return GeneratedContent(
            value=analysis_plan,
            warnings=list(dict.fromkeys(warnings)),
            review_stage="tlf_shell",
        )

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        source = self.join_sources(context.inputs)
        stage_count = len(self.descriptor.stages)
        analysis_plan = self._approved_shell_plan(context.options)
        analysis_json = analysis_plan.model_dump_json(indent=2)
        programming_outcome = await ClinicalAgentRunner(
            definition=PROGRAMMING_AGENT,
            result_model=TLFProgrammingPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 3 of 3: preserve the TLF specification and add exactly one non-executed R/SAS program "
                "scaffold per output."
            ),
            source=(
                f"ORIGINAL STUDY SOURCES\n{source}\n\n"
                f"USER-APPROVED TLF SHELL — PRESERVE\n{analysis_json}"
            ),
            options=context.options,
            stage=self.descriptor.stages[2],
            stage_index=3,
            stage_count=stage_count,
            completed_stages=list(self.descriptor.stages[:2]),
        )

        programming_plan = cast(TLFProgrammingPlan, programming_outcome.value)
        plan = TLFPlan(
            study_name=analysis_plan.study_name,
            analysis_standard=analysis_plan.analysis_standard,
            outputs=analysis_plan.outputs,
            programs=programming_plan.programs,
            assumptions=list(dict.fromkeys([
                *analysis_plan.assumptions,
                *programming_plan.assumptions,
            ])),
            unresolved_items=list(dict.fromkeys([
                *analysis_plan.unresolved_items,
                *programming_plan.unresolved_items,
            ])),
        )
        plan = self._with_readiness(plan)
        problems = verify_result("tlf", plan)
        if problems:
            raise ValueError(" ".join(problems))
        warnings = [
            *programming_outcome.warnings,
            *self.result_warnings(plan),
        ]
        return GeneratedContent(value=plan, warnings=list(dict.fromkeys(warnings)))

    @staticmethod
    def validate_shell_plan(plan: TLFAnalysisPlan) -> None:
        problems = verify_result("tlf-analysis-specification", plan)
        for output in plan.outputs:
            if not output.output_id.strip():
                problems.append("Every TLF shell needs an output identifier.")
            if not output.title.strip():
                problems.append(f"TLF output {output.output_id or '[unnamed]'} needs a title.")
            if output.output_type == "table" and (not output.columns or not output.rows):
                problems.append(f"Table {output.output_id} needs at least one row and one column.")
            if output.output_type == "listing" and not output.columns:
                problems.append(f"Listing {output.output_id} needs at least one column.")
            if output.output_type == "figure" and output.figure is None:
                problems.append(f"Figure {output.output_id} needs a figure specification.")
        if problems:
            raise ValueError(" ".join(dict.fromkeys(problems)))

    @staticmethod
    def _approved_shell_plan(options: dict[str, Any]) -> TLFAnalysisPlan:
        value = options.get("tlf_shell_plan")
        if not isinstance(value, dict):
            raise ValueError("TLF generation requires a user-approved shell plan.")
        plan = TLFAnalysisPlan.model_validate(value)
        TLFUseCase.validate_shell_plan(plan)
        return plan

    @staticmethod
    def _with_shell_readiness(plan: TLFAnalysisPlan) -> TLFAnalysisPlan:
        outputs = []
        for output in plan.outputs:
            blockers = list(output.blocking_items)
            if "TODO" in output.model_dump_json().upper() and not blockers:
                blockers.append("Complete all TODO analysis and display metadata.")
            outputs.append(output.model_copy(update={
                "readiness": "blocked" if blockers else "ready",
                "blocking_items": blockers,
            }))
        return plan.model_copy(update={"outputs": outputs})

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_tlf(cast(TLFPlan, result), output_dir, normalize_languages(options.get("languages")))

    @staticmethod
    def _with_readiness(plan: TLFPlan) -> TLFPlan:
        programs = {program.output_id.casefold(): program for program in plan.programs}
        outputs = []
        for output in plan.outputs:
            program = programs.get(output.output_id.casefold())
            serialized = output.model_dump_json()
            if program is not None:
                serialized += program.model_dump_json()
            blockers = list(output.blocking_items)
            if "TODO" in serialized.upper() and not blockers:
                blockers.append("Complete all TODO analysis, display, and programming metadata.")
            outputs.append(output.model_copy(update={
                "readiness": "blocked" if blockers else "ready",
                "blocking_items": blockers,
            }))
        return plan.model_copy(update={"outputs": outputs})
