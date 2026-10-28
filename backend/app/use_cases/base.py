from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..agents import ClinicalAgentRunner, get_agent
from ..ai import MetaAIClient
from ..config import Settings
from ..parsers import chunk_text, parse_source


@dataclass(frozen=True)
class UseCaseDescriptor:
    id: str
    title: str
    description: str
    skill_name: str
    accepted_extensions: tuple[str, ...]
    required_inputs: tuple[str, ...]
    output_formats: tuple[str, ...]
    mcp_dependencies: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    supports_languages: bool = False
    supports_result_editing: bool = True


@dataclass
class UseCaseContext:
    inputs: list[Path]
    options: dict[str, Any]
    ai: MetaAIClient
    settings: Settings
    agent_progress_path: Path | None = None


@dataclass
class GeneratedContent:
    value: BaseModel
    warnings: list[str]


class ClinicalUseCase(ABC):
    descriptor: UseCaseDescriptor
    result_model: type[BaseModel]

    @abstractmethod
    async def generate(self, context: UseCaseContext) -> GeneratedContent:
        """Generate and validate structured content with the configured model."""

    @abstractmethod
    def render(
        self,
        result: BaseModel,
        *,
        inputs: list[Path],
        options: dict[str, Any],
        output_dir: Path,
    ) -> list[Path]:
        """Render deterministic artifacts from an already validated result."""

    def validate_submission(self, filenames: list[str], options: dict[str, Any]) -> None:
        if not filenames:
            raise ValueError("At least one source file is required.")

    def validate_result(self, value: dict[str, Any]) -> BaseModel:
        return self.result_model.model_validate(value)

    async def prepare_review(self, context: UseCaseContext) -> GeneratedContent | None:
        """Optionally produce a human-review gate before final generation."""

        return None

    def result_warnings(self, result: BaseModel) -> list[str]:
        warnings: list[str] = []
        for field in ("ambiguities", "assumptions", "unresolved_items", "unresolved_mappings"):
            values = getattr(result, field, None)
            if isinstance(values, list):
                warnings.extend(str(value) for value in values if str(value).strip())
        return list(dict.fromkeys(warnings))

    def public_definition(self) -> dict[str, Any]:
        descriptor = self.descriptor
        agent = get_agent(descriptor.id)
        return {
            "id": descriptor.id,
            "title": descriptor.title,
            "description": descriptor.description,
            "skill_name": descriptor.skill_name,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "accepted_extensions": list(descriptor.accepted_extensions),
            "required_inputs": list(descriptor.required_inputs),
            "output_formats": list(descriptor.output_formats),
            "mcp_dependencies": list(descriptor.mcp_dependencies),
            "stages": list(descriptor.stages),
            "supports_languages": descriptor.supports_languages,
            "supports_result_editing": descriptor.supports_result_editing,
            "result_schema": self.result_model.model_json_schema(),
        }

    async def generate_with_agent(
        self,
        context: UseCaseContext,
        *,
        objective: str,
        source: str,
    ) -> GeneratedContent:
        outcome = await ClinicalAgentRunner(
            definition=get_agent(self.descriptor.id),
            result_model=self.result_model,
            ai=context.ai,
            settings=context.settings,
            progress_path=context.agent_progress_path,
        ).run(objective=objective, source=source, options=context.options)
        return GeneratedContent(
            value=outcome.value,
            warnings=[*outcome.warnings, *self.result_warnings(outcome.value)],
        )

    @staticmethod
    def join_sources(inputs: list[Path]) -> str:
        sections = [f"FILE: {path.name}\n{parse_source(path)}" for path in inputs]
        return "\n\n---\n\n".join(sections)

    @staticmethod
    def bounded_source(source: str, settings: Settings) -> str:
        chunks = chunk_text(source)[: settings.max_source_chunks]
        return "\n\n[CONTINUED]\n\n".join(chunks)
