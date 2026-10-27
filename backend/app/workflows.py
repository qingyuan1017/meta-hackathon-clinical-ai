from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .ai import MetaAIClient
from .artifacts import add_manifest_and_bundle
from .config import get_settings
from .use_cases import DOCUMENT_TYPES, USE_CASES, get_use_case
from .use_cases.base import UseCaseContext
from .use_cases.utilities import normalize_languages


WORKFLOWS = set(USE_CASES)


class WorkflowResult(BaseModel):
    result: dict[str, Any]
    paths: list[Path]
    warnings: list[str]


class WorkflowService:
    """Shared application service used by jobs, REST editing, and MCP adapters."""

    def __init__(self, ai_client: MetaAIClient | None = None) -> None:
        self.ai = ai_client
        self.settings = get_settings()

    async def execute(
        self,
        workflow: str,
        *,
        inputs: list[Path],
        options: dict[str, Any],
        output_dir: Path,
    ) -> WorkflowResult:
        use_case = get_use_case(workflow)
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = await use_case.generate(
            UseCaseContext(
                inputs=inputs,
                options=options,
                ai=self.ai or MetaAIClient(),
                settings=self.settings,
            )
        )
        paths = use_case.render(generated.value, inputs=inputs, options=options, output_dir=output_dir)
        paths = add_manifest_and_bundle(paths, output_dir, workflow)
        return WorkflowResult(
            result=generated.value.model_dump(),
            paths=paths,
            warnings=generated.warnings,
        )

    def render_revision(
        self,
        workflow: str,
        *,
        result: dict[str, Any],
        inputs: list[Path],
        options: dict[str, Any],
        output_dir: Path,
    ) -> WorkflowResult:
        use_case = get_use_case(workflow)
        validated = use_case.validate_result(result)
        output_dir.mkdir(parents=True, exist_ok=False)
        paths = use_case.render(validated, inputs=inputs, options=options, output_dir=output_dir)
        paths = add_manifest_and_bundle(paths, output_dir, workflow)
        return WorkflowResult(
            result=validated.model_dump(),
            paths=paths,
            warnings=use_case.result_warnings(validated),
        )


__all__ = [
    "DOCUMENT_TYPES",
    "WORKFLOWS",
    "WorkflowResult",
    "WorkflowService",
    "normalize_languages",
]
