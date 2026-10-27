from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_tlf
from ..schemas import TLFPlan
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
        output_formats=("json", "docx", "r", "sas", "zip"),
        mcp_dependencies=("cdisc-library",),
        supports_languages=True,
    )
    result_model = TLFPlan

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        source = self.join_sources(context.inputs)
        return await self.generate_with_agent(
            context,
            objective=(
                "Create draft table, listing, and figure specifications from the SAP/protocol and optional ADaM "
                "metadata. Use TODO markers where populations, variables, methods, or display details are missing."
            ),
            source=source,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_tlf(cast(TLFPlan, result), output_dir, normalize_languages(options.get("languages")))
