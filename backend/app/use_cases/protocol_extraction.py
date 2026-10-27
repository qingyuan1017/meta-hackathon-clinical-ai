from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_protocol
from ..parsers import chunk_text, parse_source
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
        chunks = chunk_text(source)[: context.settings.max_source_chunks]
        if len(chunks) == 1:
            result = await context.ai.generate_structured(
                schema=StudySummary,
                task="Extract a traceable, concise clinical protocol summary. Preserve uncertainty.",
                source=chunks[0],
                context=context.options,
            )
        else:
            partials: list[StudySummary] = []
            for index, chunk in enumerate(chunks, 1):
                partials.append(
                    await context.ai.generate_structured(
                        schema=StudySummary,
                        task=f"Extract only protocol facts present in source chunk {index} of {len(chunks)}.",
                        source=chunk,
                        context=context.options,
                    )
                )
            result = await context.ai.generate_structured(
                schema=StudySummary,
                task="Consolidate chunk extractions, remove duplicates, and preserve conflicts as ambiguities.",
                source=json.dumps([item.model_dump() for item in partials], ensure_ascii=False),
                context=context.options,
            )
        return GeneratedContent(value=result, warnings=result.ambiguities)

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_protocol(cast(StudySummary, result), output_dir)
