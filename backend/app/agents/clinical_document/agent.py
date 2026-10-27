from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import BIOPORTAL_TOOLS, CLINICALGOV_TOOLS, OPENFDA_TOOLS, PUBMED_TOOLS


AGENT = AgentDefinition(
    id="clinical-document-generation-agent",
    workflow="clinical-document",
    name="Clinical Document Generation Agent",
    description="Plans and drafts one supported clinical document while preserving missing facts and review items.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=(*CLINICALGOV_TOOLS, *OPENFDA_TOOLS, *BIOPORTAL_TOOLS, *PUBMED_TOOLS),
)
