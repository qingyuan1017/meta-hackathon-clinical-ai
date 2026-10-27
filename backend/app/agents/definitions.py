from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


INTERNAL_TOOLS = ("inspect_workflow_contract", "read_source_chunk", "submit_result")
CDISC_TOOLS = (
    "cdisc_list_products",
    "cdisc_search",
    "cdisc_get_standard",
    "cdisc_get_dataset",
    "cdisc_get_variable",
    "cdisc_list_ct_packages",
    "cdisc_get_codelist",
    "cdisc_list_biomedical_concepts",
    "cdisc_get_biomedical_concept",
    "cdisc_list_sdtm_specializations",
    "cdisc_get_sdtm_specialization",
)
CLINICALGOV_TOOLS = (
    "clinicalgov_search_studies",
    "clinicalgov_get_study",
    "clinicalgov_get_api_info",
)
OPENFDA_TOOLS = (
    "list_openfda_endpoints",
    "describe_openfda_endpoint",
    "search_openfda",
    "lookup_openfda",
    "count_openfda",
)
BIOPORTAL_TOOLS = (
    "bioportal_get_ontology",
    "bioportal_search_classes",
    "bioportal_get_class",
    "bioportal_get_class_related",
    "bioportal_annotate_text",
    "bioportal_recommend_ontologies",
)
PUBMED_TOOLS = ("pubmed_search", "pubmed_get_articles")


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    workflow: str
    name: str
    description: str
    instruction_file: str
    remote_tools: tuple[str, ...] = ()

    @property
    def tools(self) -> tuple[str, ...]:
        return (*INTERNAL_TOOLS, *self.remote_tools)

    def instructions(self) -> str:
        root = Path(__file__).parent
        shared = (root / "shared_instructions.md").read_text(encoding="utf-8")
        specific = (root / self.instruction_file).read_text(encoding="utf-8")
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


_REGISTERED = (
    AgentDefinition(
        id="clinical-protocol-extraction-agent",
        workflow="protocol-extraction",
        name="Clinical Protocol Extraction Agent",
        description="Investigates every protocol source chunk and submits a traceable structured study summary.",
        instruction_file="protocol_extraction.md",
    ),
    AgentDefinition(
        id="clinical-document-generation-agent",
        workflow="clinical-document",
        name="Clinical Document Generation Agent",
        description="Plans and drafts one supported clinical document while preserving missing facts and review items.",
        instruction_file="clinical_document.md",
        remote_tools=(*CLINICALGOV_TOOLS, *OPENFDA_TOOLS, *BIOPORTAL_TOOLS, *PUBMED_TOOLS),
    ),
    AgentDefinition(
        id="clinical-edc-design-agent",
        workflow="edc-design",
        name="Clinical EDC Design Agent",
        description="Builds and verifies visits, forms, fields, codelists, derivations, and edit checks.",
        instruction_file="edc_design.md",
        remote_tools=(*CDISC_TOOLS, *BIOPORTAL_TOOLS),
    ),
    AgentDefinition(
        id="clinical-sdtm-artifacts-agent",
        workflow="sdtm",
        name="Clinical SDTM Artifacts Agent",
        description="Develops a traceable draft SDTM mapping plan using versioned CDISC metadata when available.",
        instruction_file="sdtm.md",
        remote_tools=CDISC_TOOLS,
    ),
    AgentDefinition(
        id="clinical-tlf-artifacts-agent",
        workflow="tlf",
        name="Clinical TLF Artifacts Agent",
        description="Designs TLF specifications and explicitly tracks analysis metadata gaps.",
        instruction_file="tlf.md",
        remote_tools=(*CDISC_TOOLS, *PUBMED_TOOLS),
    ),
)

AGENTS: dict[str, AgentDefinition] = {agent.workflow: agent for agent in _REGISTERED}


def get_agent(workflow: str) -> AgentDefinition:
    try:
        return AGENTS[workflow]
    except KeyError as exc:
        raise ValueError(f"No agent is registered for workflow: {workflow}") from exc
