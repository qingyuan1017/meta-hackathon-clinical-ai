from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import CDISC_TOOLS, PUBMED_TOOLS


AGENT = AgentDefinition(
    id="clinical-tlf-artifacts-agent",
    workflow="tlf",
    name="Clinical TLF Artifacts Agent",
    description="Designs TLF specifications and explicitly tracks analysis metadata gaps.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
)
