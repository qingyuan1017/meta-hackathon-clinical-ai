from .base import AgentDefinition
from .clinical_document import AGENT as CLINICAL_DOCUMENT_AGENT
from .edc_design import AGENT as EDC_DESIGN_AGENT
from .protocol_extraction import AGENT as PROTOCOL_EXTRACTION_AGENT
from .sdtm import AGENT as SDTM_AGENT
from .tlf import AGENT as TLF_AGENT


_REGISTERED = (
    PROTOCOL_EXTRACTION_AGENT,
    CLINICAL_DOCUMENT_AGENT,
    EDC_DESIGN_AGENT,
    SDTM_AGENT,
    TLF_AGENT,
)

AGENTS: dict[str, AgentDefinition] = {agent.workflow: agent for agent in _REGISTERED}


def get_agent(workflow: str) -> AgentDefinition:
    try:
        return AGENTS[workflow]
    except KeyError as exc:
        raise ValueError(f"No agent is registered for workflow: {workflow}") from exc
