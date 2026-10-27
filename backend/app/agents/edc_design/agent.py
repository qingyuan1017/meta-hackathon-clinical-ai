from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import BIOPORTAL_TOOLS, CDISC_TOOLS


AGENT = AgentDefinition(
    id="clinical-edc-design-agent",
    workflow="edc-design",
    name="Clinical EDC Design Agent",
    description="Builds and verifies visits, forms, fields, codelists, derivations, and edit checks.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=(*CDISC_TOOLS, *BIOPORTAL_TOOLS),
)
