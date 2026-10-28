from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..agents import AgentDefinition, AgentOutcome, ClinicalAgentRunner, get_agent
from ..agents.protocol_extraction import PERSPECTIVE_AGENTS
from ..artifacts import render_protocol
from ..parsers import parse_source
from ..schemas import StudySummary
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor


class ProtocolExtractionUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="protocol-extraction",
        title="Clinical protocol extraction",
        description=(
            "Extract study design, objectives, endpoints, visits, criteria, assessments, and ambiguities, "
            "then emit USDM 4.0 only through the complete CDISC CORE conformance gate."
        ),
        skill_name="clinical-protocol-extraction",
        accepted_extensions=(".pdf", ".docx", ".txt", ".md"),
        required_inputs=("One protocol document",),
        output_formats=("json", "markdown", "zip"),
    )
    result_model = StudySummary

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        if len(filenames) != 1:
            raise ValueError("Protocol extraction requires exactly one protocol file.")

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        source = parse_source(context.inputs[0])
        perspective_results = await asyncio.gather(
            *(
                self._run_perspective(
                    context,
                    key=key,
                    definition=definition,
                    source=source,
                )
                for key, definition in PERSPECTIVE_AGENTS
            ),
            return_exceptions=True,
        )
        peer_drafts: list[str] = []
        warnings: list[str] = []
        for (_key, definition), result in zip(PERSPECTIVE_AGENTS, perspective_results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                warnings.append(
                    f"{definition.name} was unavailable; the lead reconciler completed an independent review."
                )
                continue
            peer_drafts.append(
                f"PERSPECTIVE: {definition.name}\n{result.value.model_dump_json(indent=2)}"
            )
            warnings.extend(result.warnings)

        objective = (
            "Produce the final traceable clinical protocol summary. Independently verify every field against "
            "the original source, reconcile the fallible specialist drafts below, and preserve every unresolved "
            "conflict or uncertainty.\n\n"
            + ("\n\n".join(peer_drafts) if peer_drafts else "No specialist draft was available.")
        )
        lead_outcome = await ClinicalAgentRunner(
            definition=get_agent(self.descriptor.id),
            result_model=self.result_model,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(objective=objective, source=source, options=context.options)
        warnings.extend(lead_outcome.warnings)
        warnings.extend(self.result_warnings(lead_outcome.value))
        return GeneratedContent(
            value=lead_outcome.value,
            warnings=list(dict.fromkeys(warnings)),
        )

    async def _run_perspective(
        self,
        context: UseCaseContext,
        *,
        key: str,
        definition: AgentDefinition,
        source: str,
    ) -> AgentOutcome:
        progress_path = None
        if context.agent_progress_path is not None:
            progress_path = context.agent_progress_path.with_name(f"perspective-{key}.json")
        return await ClinicalAgentRunner(
            definition=definition,
            result_model=self.result_model,
            ai=context.ai,
            settings=context.settings,
            progress_path=progress_path,
        ).run(
            objective=f"Extract the {definition.name} perspective for later reconciliation by the lead agent.",
            source=source,
            options=context.options,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_protocol(cast(StudySummary, result), output_dir)
