from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import CDISC_TOOLS


AGENT = AgentDefinition(
    id="clinical-sdtm-artifacts-agent",
    workflow="sdtm",
    name="Clinical SDTM Artifacts Agent",
    description="Develops a traceable draft SDTM mapping plan using versioned CDISC metadata when available.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=CDISC_TOOLS,
)
