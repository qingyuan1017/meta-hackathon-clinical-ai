from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from ..artifacts import render_clinical_document
from ..schemas import ClinicalDocument
from .base import ClinicalUseCase, GeneratedContent, UseCaseContext, UseCaseDescriptor


DOCUMENT_TYPES = {
    "protocol-synopsis": "Protocol Synopsis",
    "full-protocol": "Full Protocol Draft",
    "sap": "Statistical Analysis Plan",
    "csr-shell": "Clinical Study Report Shell",
    "informed-consent": "Informed Consent Form Draft",
    "data-management-plan": "Data Management Plan",
    "data-review-plan": "Data Review Plan",
    "aggregate-risk-profile": "Aggregate Study Risk Profile",
    "potential-important-deviations": "Potential Important Protocol Deviations",
    "potential-amendments": "Potential Protocol Amendments",
}


class ClinicalDocumentUseCase(ClinicalUseCase):
    descriptor = UseCaseDescriptor(
        id="clinical-document",
        title="Clinical document generation",
        description="Draft a selected clinical document from a study brief and optional reference material.",
        skill_name="clinical-document-generation",
        accepted_extensions=(".pdf", ".docx", ".txt", ".md", ".json"),
        required_inputs=("Study brief and/or protocol reference",),
        output_formats=("json", "docx", "pdf", "zip"),
    )
    result_model = ClinicalDocument

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        if not filenames and not str(options.get("study_brief", "")).strip():
            raise ValueError("A study brief or source file is required.")
        if str(options.get("document_type", "protocol-synopsis")) not in DOCUMENT_TYPES:
            raise ValueError("Unsupported clinical document type.")

    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        document_key = str(context.options.get("document_type", "protocol-synopsis"))
        document_type = DOCUMENT_TYPES.get(document_key)
        if not document_type:
            raise ValueError("Unsupported clinical document type.")
        source = self.join_sources(context.inputs)
        brief = str(context.options.get("study_brief", "")).strip()
        combined = f"STUDY BRIEF\n{brief}\n\nREFERENCE MATERIAL\n{source}".strip()
        return await self.generate_with_agent(
            context,
            objective=(
                f"Draft a structured {document_type}. Include a useful section outline and substantive draft text. "
                "Mark missing facts for review; do not fabricate patient-level information."
            ),
            source=combined,
        )

    def render(self, result: BaseModel, *, inputs: list[Path], options: dict[str, Any], output_dir: Path) -> list[Path]:
        return render_clinical_document(cast(ClinicalDocument, result), output_dir)
