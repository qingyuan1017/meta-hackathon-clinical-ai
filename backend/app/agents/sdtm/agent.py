from pathlib import Path

from ..base import AgentDefinition
from ..tool_catalog import CDISC_TOOLS


_DIRECTORY = Path(__file__).parent


DOMAIN_MAPPING_AGENT = AgentDefinition(
    id="clinical-sdtm-domain-mapping-agent",
    workflow="sdtm-domain-mapping",
    name="Clinical SDTM Domain Mapping Agent",
    description="Maps raw or existing SDTM source datasets to target SDTM domains.",
    instruction_file=_DIRECTORY / "domain_mapping.md",
    remote_tools=CDISC_TOOLS,
)


VARIABLE_MAPPING_AGENT = AgentDefinition(
    id="clinical-sdtm-variable-mapping-agent",
    workflow="sdtm-variable-mapping",
    name="Clinical SDTM Variable Mapping Agent",
    description="Maps variables and value-level metadata and determines draft aCRF annotations.",
    instruction_file=_DIRECTORY / "variable_mapping.md",
    remote_tools=CDISC_TOOLS,
)


RULE_AUGMENTATION_AGENT = AgentDefinition(
    id="clinical-sdtm-rule-augmentation-agent",
    workflow="sdtm-rule-augmentation",
    name="Clinical SDTM Rule Augmentation Agent",
    description="Augments approved mappings with implementation rules used to render draft R and SAS code.",
    instruction_file=_DIRECTORY / "rule_augmentation.md",
    remote_tools=CDISC_TOOLS,
)


AGENT = AgentDefinition(
    id="clinical-sdtm-artifacts-agent",
    workflow="sdtm",
    name="Clinical SDTM Mapping Pipeline",
    description="Runs domain mapping, variable/value-level mapping, and rule augmentation in sequence.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    remote_tools=CDISC_TOOLS,
)
