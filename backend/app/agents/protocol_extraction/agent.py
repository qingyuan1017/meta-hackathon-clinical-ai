from pathlib import Path

from ..base import AgentDefinition


AGENT = AgentDefinition(
    id="clinical-protocol-extraction-agent",
    workflow="protocol-extraction",
    name="Clinical Protocol Extraction Agent",
    description="Investigates every protocol source chunk and submits a traceable structured study summary.",
    instruction_file=Path(__file__).with_name("instructions.md"),
)
