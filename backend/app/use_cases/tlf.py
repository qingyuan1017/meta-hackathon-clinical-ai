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
        description="Review an output table of contents, detailed shells, and ADaM-linked program scaffolds in three gated stages.",
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
        source = self.join_sources(context.inputs)
        stage_count = len(self.descriptor.stages)
        if context.options.get("tlf_inventory_plan") is None:
            inventory_outcome = await ClinicalAgentRunner(
                definition=INVENTORY_AGENT,
                result_model=TLFInventoryPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    "Stage 1 of 3: build the ordered table, listing, and figure table of contents. Include every "
                    "source-supported output, then propose a conventional clinical-study TLF package for missing "
                    "coverage. Clearly distinguish conventional proposals from source-supported items and retain "
                    "TODOs for unsupported decisions. Stop for user approval before adding shell or program details."
                ),
                source=source,
                options=context.options,
                stage=self.descriptor.stages[0],
                stage_index=1,
                stage_count=stage_count,
            )
            inventory_plan = cast(TLFInventoryPlan, inventory_outcome.value)
            self.validate_inventory_plan(inventory_plan)
            return GeneratedContent(
                value=inventory_plan,
                warnings=list(dict.fromkeys([
                    *inventory_outcome.warnings,
                    *self.result_warnings(inventory_plan),
                ])),
                review_stage="tlf_inventory",
            )

        inventory_plan = self._approved_inventory_plan(context.options)
        if context.options.get("tlf_shell_plan") is None:
            inventory_json = inventory_plan.model_dump_json(indent=2)
            analysis_outcome = await ClinicalAgentRunner(
                definition=ANALYSIS_AGENT,
                result_model=TLFAnalysisPlan,
                ai=context.ai,
                settings=context.settings,
                progress_path=context.agent_progress_path,
            ).run(
                objective=(
                    "Stage 2 of 3: preserve every user-approved inventory item exactly and generate a detailed "
                    "analysis and display shell for each output. Stop for user approval before programming."
                ),
                source=f"{source}\n\nUSER-APPROVED OUTPUT TABLE OF CONTENTS — PRESERVE\n{inventory_json}",
                options=context.options,
                stage=self.descriptor.stages[1],
                stage_index=2,
                stage_count=stage_count,
                completed_stages=[self.descriptor.stages[0]],
            )
            analysis_plan = cast(TLFAnalysisPlan, analysis_outcome.value)
            self.validate_shell_plan(analysis_plan, inventory_plan)
            analysis_plan = self._with_shell_readiness(analysis_plan)
            return GeneratedContent(
                value=analysis_plan,
                warnings=list(dict.fromkeys([
                    *analysis_outcome.warnings,
                    *self.result_warnings(analysis_plan),
                ])),
                review_stage="tlf_shell",
            )

        analysis_plan = self._approved_shell_plan(context.options)
        if context.options.get("tlf_programming_plan") is not None:
            return None
        analysis_json = analysis_plan.model_dump_json(indent=2)
        programming_outcome = await ClinicalAgentRunner(
            definition=PROGRAMMING_AGENT,
            result_model=TLFProgrammingPlan,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(
            objective=(
                "Stage 3 of 3: preserve the user-approved shells, link every program to the approved ADaM "
                "dataset-variable schema, and add exactly one non-executed R/SAS scaffold per output. "
                "Stop for final user review."
            ),
            source=(
                f"ORIGINAL STUDY AND ADAM SOURCES\n{source}\n\n"
                f"USER-APPROVED TLF SHELLS — PRESERVE\n{analysis_json}"
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
        self.validate_programming_plan(plan, analysis_plan)
        return GeneratedContent(
            value=plan,
            warnings=list(dict.fromkeys([
                *programming_outcome.warnings,
                *self.result_warnings(plan),
            ])),
            review_stage="tlf_programming",
        )

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        plan = self._approved_programming_plan(context.options)
        plan = self._with_readiness(plan)
        return GeneratedContent(
            value=plan,
            warnings=self.result_warnings(plan),
        )

    @staticmethod
    def validate_inventory_plan(plan: TLFInventoryPlan) -> None:
        problems = verify_result("tlf-output-inventory", plan)
        for output in plan.outputs:
            if not output.output_id.strip():
                problems.append("Every TLF inventory item needs an output identifier.")
            if not output.title.strip():
                problems.append(f"TLF output {output.output_id or '[unnamed]'} needs a title.")
        if problems:
            raise ValueError(" ".join(dict.fromkeys(problems)))

    @staticmethod
    def validate_shell_plan(plan: TLFAnalysisPlan, inventory: TLFInventoryPlan | None = None) -> None:
        problems = verify_result("tlf-analysis-specification", plan)
        if inventory is not None and TLFUseCase._inventory_identity(inventory) != TLFUseCase._inventory_identity(plan):
            problems.append(
                "The shell plan must preserve the ordered, approved output identifiers, types, titles, and basis values."
            )
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
    def validate_programming_plan(plan: TLFPlan, shell: TLFAnalysisPlan | None = None) -> None:
        problems = verify_result("tlf", plan)
        if shell is not None:
            approved_outputs = [
                output.model_dump(mode="json", exclude={"readiness", "blocking_items"})
                for output in shell.outputs
            ]
            reviewed_outputs = [
                output.model_dump(mode="json", exclude={"readiness", "blocking_items"})
                for output in plan.outputs
            ]
            if approved_outputs != reviewed_outputs:
                problems.append("Programming review must preserve every approved shell without changes.")
        if problems:
            raise ValueError(" ".join(dict.fromkeys(problems)))

    @staticmethod
    def _approved_inventory_plan(options: dict[str, Any]) -> TLFInventoryPlan:
        value = options.get("tlf_inventory_plan")
        if not isinstance(value, dict):
            raise ValueError("TLF shell generation requires a user-approved output table of contents.")
        plan = TLFInventoryPlan.model_validate(value)
        TLFUseCase.validate_inventory_plan(plan)
        return plan

    @staticmethod
    def inventory_from_shell(plan: TLFAnalysisPlan) -> TLFInventoryPlan:
        return TLFInventoryPlan.model_validate({
            "study_name": plan.study_name,
            "analysis_standard": plan.analysis_standard,
            "outputs": [
                output.model_dump(
                    mode="json",
                    include={
                        "output_id",
                        "output_type",
                        "title",
                        "basis",
                        "section",
                        "purpose",
                        "population",
                        "source_reference",
                    },
                )
                for output in plan.outputs
            ],
            "assumptions": plan.assumptions,
            "unresolved_items": plan.unresolved_items,
        })

    @staticmethod
    def _approved_shell_plan(options: dict[str, Any]) -> TLFAnalysisPlan:
        value = options.get("tlf_shell_plan")
        if not isinstance(value, dict):
            raise ValueError("TLF generation requires a user-approved shell plan.")
        plan = TLFAnalysisPlan.model_validate(value)
        TLFUseCase.validate_shell_plan(plan, TLFUseCase._approved_inventory_plan(options))
        return plan

    @staticmethod
    def _approved_programming_plan(options: dict[str, Any]) -> TLFPlan:
        value = options.get("tlf_programming_plan")
        if not isinstance(value, dict):
            raise ValueError("TLF artifact rendering requires a user-approved programming plan.")
        plan = TLFPlan.model_validate(value)
        TLFUseCase.validate_programming_plan(plan, TLFUseCase._approved_shell_plan(options))
        return plan

    @staticmethod
    def _inventory_identity(plan: TLFInventoryPlan | TLFAnalysisPlan) -> list[tuple[str, str, str, str]]:
        return [
            (output.output_id.casefold(), output.output_type, output.title.strip(), output.basis)
            for output in plan.outputs
        ]

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
