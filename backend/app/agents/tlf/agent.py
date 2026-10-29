from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import CDISC_TOOLS, PUBMED_TOOLS


_DIRECTORY = Path(__file__).parent


INVENTORY_AGENT = AgentDefinition(
    id="clinical-tlf-output-inventory-agent",
    workflow="tlf-output-inventory",
    name="Clinical TLF Output Inventory Agent",
    description="Extracts the source-supported TLF inventory without inventing conventional outputs.",
    instruction_file=_DIRECTORY / "output_inventory.md",
    remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
)


ANALYSIS_AGENT = AgentDefinition(
    id="clinical-tlf-analysis-specification-agent",
    workflow="tlf-analysis-specification",
    name="Clinical TLF Analysis Specification Agent",
    description="Maps inventory outputs to populations, ADaM inputs, methods, and display metadata.",
    instruction_file=_DIRECTORY / "analysis_specification.md",
    remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
)


PROGRAMMING_AGENT = AgentDefinition(
    id="clinical-tlf-programming-augmentation-agent",
    workflow="tlf-programming-augmentation",
    name="Clinical TLF Programming Augmentation Agent",
    description="Adds reviewable R and SAS scaffolds to the fixed TLF specification.",
    instruction_file=_DIRECTORY / "programming_augmentation.md",
    remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
)


AGENT = AgentDefinition(
    id="clinical-tlf-artifacts-agent",
    workflow="tlf",
    name="Clinical TLF Artifacts Pipeline",
    description="Runs output inventory, analysis/display specification, and programming augmentation in sequence.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
)
