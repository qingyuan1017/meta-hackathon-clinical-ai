from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_protocol
from ..parsers import parse_source
from ..schemas import StudySummary
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor


class ProtocolExtractionUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="protocol-extraction",
        title="Clinical protocol extraction",
        description="Extract study design, objectives, endpoints, visits, criteria, assessments, and ambiguities.",
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
        return await self.generate_with_agent(
            context,
            objective="Extract a traceable, concise clinical protocol summary and preserve every uncertainty.",
            source=source,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_protocol(cast(StudySummary, result), output_dir)
