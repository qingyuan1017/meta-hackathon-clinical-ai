from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tool_catalog import INTERNAL_TOOLS


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    workflow: str
    name: str
    description: str
    instruction_file: Path
    remote_tools: tuple[str, ...] = ()

    @property
    def tools(self) -> tuple[str, ...]:
        return (*INTERNAL_TOOLS, *self.remote_tools)

    def instructions(self) -> str:
        shared = (Path(__file__).parent / "shared_instructions.md").read_text(encoding="utf-8")
        specific = self.instruction_file.read_text(encoding="utf-8")
        return f"{shared.rstrip()}\n\n{specific.strip()}\n"

    def public_definition(self, max_turns: int) -> dict:
        return {
            "id": self.id,
            "workflow": self.workflow,
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "max_turns": max_turns,
        }
