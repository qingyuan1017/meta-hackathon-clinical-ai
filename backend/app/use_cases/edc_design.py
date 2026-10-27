from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_edc
from ..schemas import EDCDesign
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor


class EDCDesignUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="edc-design",
        title="EDC database design",
        description="Design visits, forms, fields, codelists, derivations, and edit checks.",
        skill_name="clinical-edc-design",
        accepted_extensions=(".pdf", ".docx", ".txt", ".md", ".json"),
        required_inputs=("Protocol or protocol-extraction JSON",),
        output_formats=("json", "xlsx", "zip"),
        mcp_dependencies=("cdisc-library",),
    )
    result_model = EDCDesign

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        source = self.join_sources(context.inputs)
        return await self.generate_with_agent(
            context,
            objective=(
                "Design a pragmatic EDC build specification from the supplied protocol material. Include visits, "
                "forms, atomic fields, codelists, derivations, and actionable edit checks. Do not collect data "
                "that is not justified by the source."
            ),
            source=source,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_edc(cast(EDCDesign, result), output_dir)
