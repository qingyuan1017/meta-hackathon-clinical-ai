from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_sdtm
from ..parsers import parse_source
from ..schemas import SDTMPlan
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor
from .utilities import normalize_languages


class SDTMUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="sdtm",
        title="SDTM artifact generation",
        description="Generate mappings, programs, draft Define-XML, and annotated CRF artifacts.",
        skill_name="clinical-sdtm-artifacts",
        accepted_extensions=(".pdf", ".json", ".xlsx", ".docx", ".txt", ".md"),
        required_inputs=("Blank CRF PDF", "EDC JSON or XLSX", "Optional protocol context"),
        output_formats=("json", "xlsx", "xml", "pdf", "r", "sas", "zip"),
        mcp_dependencies=("cdisc-library",),
        supports_languages=True,
    )
    result_model = SDTMPlan

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        suffixes = [Path(name).suffix.lower() for name in filenames]
        if ".pdf" not in suffixes or not any(suffix in {".json", ".xlsx"} for suffix in suffixes):
            raise ValueError("SDTM generation requires a blank CRF PDF and EDC JSON or XLSX.")

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        crf, edc = self._required_inputs(context.inputs)
        context_inputs = [path for path in context.inputs if path not in {crf, edc}]
        source = f"EDC SPECIFICATION\n{parse_source(edc)}\n\nOPTIONAL CONTEXT\n{self.join_sources(context_inputs)}"
        return await self.generate_with_agent(
            context,
            objective=(
                "Create a draft SDTMIG 3.4 mapping plan for the supplied EDC fields. Use plausible domain and "
                "variable names, explain derived mappings, and place uncertainty in unresolved_mappings."
            ),
            source=source,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        crf, _ = self._required_inputs(inputs)
        return render_sdtm(cast(SDTMPlan, result), crf, output_dir, normalize_languages(options.get("languages")))

    @staticmethod
    def _required_inputs(inputs: list[Path]) -> tuple[Path, Path]:
        crf = next((path for path in inputs if path.suffix.lower() == ".pdf"), None)
        edc = next((path for path in inputs if path.suffix.lower() in {".json", ".xlsx"}), None)
        if crf is None or edc is None:
            raise ValueError("SDTM generation requires a blank CRF PDF and an EDC JSON or XLSX specification.")
        return crf, edc
