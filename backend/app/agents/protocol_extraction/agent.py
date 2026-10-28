from pathlib import Path

from ..base import AgentDefinition


PROTOCOL_POLICY = Path(__file__).with_name("extraction_policy.md")


AGENT = AgentDefinition(
    id="clinical-protocol-extraction-agent",
    workflow="protocol-extraction",
    name="Clinical Protocol Extraction Agent",
    description="Reconciles parallel specialist reviews into one traceable structured study summary.",
    instruction_file=Path(__file__).with_name("instructions.md"),
    policy_files=(PROTOCOL_POLICY,),
)


PERSPECTIVE_AGENTS = (
    (
        "design-endpoints",
        AgentDefinition(
            id="protocol-design-endpoints-agent",
            workflow="protocol-extraction",
            name="Protocol Design and Endpoints Specialist",
            description="Extracts study identity, design, objectives, endpoints, arms, population, size, and duration.",
            instruction_file=Path(__file__).with_name("design_endpoints.md"),
            policy_files=(PROTOCOL_POLICY,),
        ),
    ),
    (
        "conduct-eligibility",
        AgentDefinition(
            id="protocol-conduct-eligibility-agent",
            workflow="protocol-extraction",
            name="Protocol Conduct and Eligibility Specialist",
            description="Extracts visits, eligibility criteria, assessments, and operational timing.",
            instruction_file=Path(__file__).with_name("conduct_eligibility.md"),
            policy_files=(PROTOCOL_POLICY,),
        ),
    ),
    (
        "safety-ambiguity",
        AgentDefinition(
            id="protocol-safety-ambiguity-agent",
            workflow="protocol-extraction",
            name="Protocol Safety and Ambiguity Specialist",
            description="Extracts safety monitoring and independently audits contradictions, omissions, and unclear definitions.",
            instruction_file=Path(__file__).with_name("safety_ambiguity.md"),
            policy_files=(PROTOCOL_POLICY,),
        ),
    ),
)
